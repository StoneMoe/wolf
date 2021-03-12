import asyncio
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING, Any

from pywebio import run_async
from pywebio.output import output
from pywebio.session import get_current_session
from pywebio.session.coroutinebased import TaskHandle

from enums import Role, PlayerStatus, LogCtrl, WitchRule, GuardRule, GameStage
from models.system import Config, Global
from stub import OutputHandler
from . import logger

if TYPE_CHECKING:
    from .room import Room


def player_action(func):
    """
    玩家操作等待解锁逻辑装饰器

    1. 仅用于 User 类下的游戏角色操作
    2. 被装饰的函数返回字符串时，将返回错误信息给当前用户，并继续锁定
    3. 返回 None / True 时，将解锁游戏阶段
    """

    def wrapper(self: 'User', *args, **kwargs):
        if self.room is None or self.room.waiting is not True:
            return
        if not self.should_act():
            return

        rv = func(self, *args, **kwargs)
        if rv in [None, True]:
            self.room.waiting = False
            self.room.enter_null_stage()
        if isinstance(rv, str):
            self.send_msg(text=rv)

        return rv

    return wrapper


@dataclass
class User:
    nick: str
    # Session
    main_task_id: Any  # 主 Task 线程 id
    input_blocking: bool

    # Game
    room: Optional['Room']  # 所在房间
    role: Optional[Role]  # 角色
    skill: dict  # 角色技能
    status: Optional[PlayerStatus]  # 玩家状态

    game_msg: OutputHandler  # 游戏日志 UI Handler
    game_msg_syncer: Optional[TaskHandle]  # 游戏日志同步线程

    def __str__(self):
        return self.nick

    __repr__ = __str__

    # 房间
    def send_msg(self, text):
        """发送仅该用户可见的房间消息"""
        if self.room:
            self.room.send_msg(text, nick=self.nick)
        else:
            logger.warning('在玩家非进入房间状态时调用了 User.send_msg()')

    async def _game_msg_syncer(self):
        """
        同步 self.game_msg 和 self.room.log

        由 Room 管理，运行在用户 session 的主 Task 线程上
        """
        last_idx = len(self.room.log)
        while True:
            for msg in self.room.log[last_idx:]:
                if msg[0] == self.nick:
                    self.game_msg.append(f'👂：{msg[1]}')
                elif msg[0] == Config.SYS_NICK:
                    self.game_msg.append(f'📢：{msg[1]}')
                elif msg[0] is None:
                    if msg[1] == LogCtrl.RemoveInput:
                        # Workaround, see https://github.com/wang0618/PyWebIO/issues/32
                        if self.input_blocking:
                            get_current_session().send_client_event({
                                'event': 'from_cancel',
                                'task_id': self.main_task_id,
                                'data': None
                            })

            # 清理记录
            if len(self.room.log) > 50000:
                self.room.log = self.room.log[len(self.room.log) // 2:]
            last_idx = len(self.room.log)

            await asyncio.sleep(0.2)

    def start_syncer(self):
        """启动游戏日志同步逻辑，由 Room 管理"""
        if self.game_msg_syncer is not None:
            raise AssertionError
        self.game_msg_syncer = run_async(self._game_msg_syncer())

    def stop_syncer(self):
        """结束游戏日志同步逻辑，由 Room 管理"""
        if self.game_msg_syncer is None or self.game_msg_syncer.closed():
            raise AssertionError
        self.game_msg_syncer.close()
        self.game_msg_syncer = None

    # 玩家状态
    def should_act(self):
        """当前处于该玩家进行操作的阶段"""
        stage_map = {
            GameStage.Day: [],
            GameStage.GUARD: [Role.GUARD],
            GameStage.WITCH: [Role.WITCH],
            GameStage.HUNTER: [Role.HUNTER],
            GameStage.DETECTIVE: [Role.DETECTIVE],
            GameStage.WOLF: [Role.WOLF, Role.WOLF_KING],
        }
        return self.role in stage_map.get(self.room.stage, []) and self.status != PlayerStatus.DEAD

    def witch_has_heal(self):
        """女巫持有解药"""
        return self.skill.get('heal') is True

    def witch_has_poison(self):
        """女巫持有毒药"""
        return self.skill.get('poison') is True

    # 玩家操作
    @player_action
    def skip(self):
        pass

    @player_action
    def wolf_kill_player(self, nick):
        self.room.players[nick].status = PlayerStatus.PENDING_DEAD

    @player_action
    def detective_identify_player(self, nick):
        self.send_msg(f'玩家 {nick} 的身份是 {self.room.players[nick].role}')

    @player_action
    def witch_kill_player(self, nick):
        if not self.witch_has_poison():
            return '没有毒药了'
        self.room.players[nick].status = PlayerStatus.PENDING_POISON

    @player_action
    def witch_heal_player(self, nick):
        if self.room.witch_rule == WitchRule.NO_SELF_RESCUE:
            if nick == self.nick:
                return '不能解救自己'
        if self.room.witch_rule == WitchRule.SELF_RESCUE_FIRST_NIGHT_ONLY:
            if nick == self.nick and self.room.round != 1:
                return '仅第一晚可以解救自己'

        if not self.witch_has_heal():
            return '没有解药了'
        self.room.players[nick].status = PlayerStatus.PENDING_HEAL

    @player_action
    def guard_protect_player(self, nick):
        if self.skill['last_protect'] == nick:
            return '两晚不可守卫同一玩家'

        if self.room.players[nick].status == PlayerStatus.PENDING_HEAL and \
                self.room.guard_rule == GuardRule.MED_CONFLICT:
            # 同守同救冲突
            self.room.players[nick].status = PlayerStatus.PENDING_DEAD
            return

        if self.room.players[nick].status == PlayerStatus.PENDING_POISON:
            # 守卫无法防御女巫毒药
            return

        self.room.players[nick].status = PlayerStatus.PENDING_GUARD

    @player_action
    def hunter_gun_status(self):
        self.send_msg(
            f'你的开枪状态为...'
            f'{"可以开枪" if self.status != PlayerStatus.PENDING_POISON else "无法开枪"}'
        )

    # 登录
    @classmethod
    def validate_nick(cls, nick) -> Optional[str]:
        if nick in Global.users or Config.SYS_NICK in nick:
            return '昵称已被使用'

    @classmethod
    def alloc(cls, nick, init_task_id) -> 'User':
        if nick in Global.users:
            raise ValueError
        Global.users[nick] = cls(
            nick=nick,
            main_task_id=init_task_id,
            input_blocking=False,
            room=None,
            role=None,
            skill=dict(),
            status=None,
            game_msg=output(),
            game_msg_syncer=None
        )
        logger.info(f'用户 "{nick}" 登录')
        return Global.users[nick]

    @classmethod
    def free(cls, user: 'User'):
        # 反注册
        Global.users.pop(user.nick)
        # 从房间移除用户
        if user.room:
            user.room.remove_player(user)
        logger.info(f'用户 "{user.nick}" 注销')
