import asyncio
import random
from collections import Counter
from copy import copy
from dataclasses import dataclass
from logging import getLogger
from typing import List, Optional, Dict, Tuple

from pywebio import run_async
from pywebio.output import output
from pywebio.session.coroutinebased import TaskHandle

from enums import Role, WitchRule, GuardRule, PlayerStatus, GameStage
from stub import OutputHandler
from utils import rand_int, say

logger = getLogger('Wolf')


class Config:
    SYS_NICK = '📢'


class Global:
    users = dict()
    rooms: Dict[str, 'Room'] = dict()

    @classmethod
    def reg_room(cls, room: 'Room') -> 'Room':
        if room.id is not None:
            raise AssertionError

        latest_room: list = list(cls.rooms.keys())[-1:]
        if not latest_room:
            alloc_room_id = rand_int()
        else:
            alloc_room_id = cls.rooms[latest_room[0]].id + 1

        room.id = alloc_room_id
        cls.rooms[str(room.id)] = room
        return room

    @classmethod
    def remove_room(cls, room_id):
        if str(room_id) in cls.rooms:
            del cls.rooms[str(room_id)]

    @classmethod
    def get_room(cls, room_id):
        return cls.rooms.get(str(room_id))


def player_action(func):
    """
    游戏阶段锁定逻辑装饰器

    用于 User 类下的游戏角色操作
    被装饰的函数返回字符串可以返回错误信息给当前用户
    """

    def wrapper(self: 'User', *args, **kwargs):
        if self.room is None or self.room.waiting is not True:
            return
        rv = func(self, *args, **kwargs)
        if rv in [None, True]:
            self.room.waiting = False
        if isinstance(rv, str):
            self.send_msg(text=rv)
        return rv

    return wrapper


@dataclass
class User:
    nick: str
    room: Optional['Room']  # 所在房间
    role: Optional[Role]  # 角色
    skill: dict  # 角色技能
    status: Optional[PlayerStatus]  # 玩家状态

    game_msg: OutputHandler  # 玩家日志框
    game_msg_syncer: Optional[TaskHandle]

    def __str__(self):
        return self.nick

    __repr__ = __str__

    def send_msg(self, text):
        if self.room:
            self.room.send_msg(text, target=self.nick)
        else:
            logger.warning('在玩家非进入房间状态时调用了 User.send_msg()')

    async def _game_msg_syncer(self):
        """同步 Game msg box 和 Room Log，由 Room 管理"""
        last_idx = len(self.room.log)
        while True:
            for msg in self.room.log[last_idx:]:
                if msg[0] == self.nick:
                    self.game_msg.append(f'👂：{msg[1]}')
                elif msg[0] == Config.SYS_NICK:
                    self.game_msg.append(f'📢：{msg[1]}')

            # 清理记录
            if len(self.room.log) > 50000:
                self.room.log = self.room.log[len(self.room.log) // 2:]
            last_idx = len(self.room.log)

            await asyncio.sleep(0.2)

    def start_syncer(self):
        if self.game_msg_syncer is not None:
            raise AssertionError
        self.game_msg_syncer = run_async(self._game_msg_syncer())

    def stop_syncer(self):
        if self.game_msg_syncer is None or self.game_msg_syncer.closed():
            raise AssertionError
        self.game_msg_syncer.close()
        self.game_msg_syncer = None

    # 玩家状态
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
        self.room.send_msg(
            f'玩家 {nick} 的身份是 {self.room.players[nick].role}',
            target=self.nick
        )

    @player_action
    def witch_kill_player(self, nick):
        if not self.witch_has_poison():
            return '没有毒药了'
        self.room.players[nick].status = PlayerStatus.PENDING_DEAD

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
        # TODO: 没有处理守卫无法防御女巫毒药的情况
        if self.skill['last_protect'] == nick:
            return '两晚不可守卫同一玩家'

        if self.room.players[nick].status == PlayerStatus.PENDING_HEAL and \
                self.room.guard_rule == GuardRule.MED_CONFLICT:
            self.room.players[nick].status = PlayerStatus.PENDING_DEAD

        self.room.players[nick].status = PlayerStatus.PENDING_GUARD

    @player_action
    def hunter_gun_status(self):
        self.room.send_msg(
            f'你的开枪状态为...'
            f'{"可以开枪" if self.status != PlayerStatus.PENDING_DEAD else "无法开枪"}',
            target=self.nick
        )

    # 玩家操作 End

    @classmethod
    def validate_nick(cls, nick) -> Optional[str]:
        if nick in Global.users or Config.SYS_NICK in nick:
            return '昵称已被使用'

    @classmethod
    def alloc(cls, nick) -> 'User':
        if nick in Global.users:
            raise ValueError
        Global.users[nick] = cls(
            nick=nick,
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


@dataclass
class Room:
    id: Optional[int]  # 这个 id 应该在注册房间至 room registry 时，由 Global manager 写入
    # Static settings
    roles: List[Role]
    witch_rule: WitchRule
    guard_rule: GuardRule

    # Dynamic
    started: bool  # 游戏开始状态
    roles_pool: List[Role]  # 用于记录角色分配剩余状态
    players: Dict[str, User]  # 房间内玩家
    round: int  # 轮次
    stage: Optional[GameStage]  # 游戏阶段
    waiting: bool  # 等待玩家操作
    log: List[Tuple[str, str]]  # 广播消息源，(目标, 内容)

    # Internal
    logic_thread: Optional[TaskHandle]

    async def night_logic(self):
        """单夜逻辑"""
        # 开始
        self.send_msg('天黑请闭眼', tts=True)
        await asyncio.sleep(3)

        # 狼人
        self.stage = GameStage.WOLF
        self.send_msg('狼人请出现', tts=True)
        await self.wait_for_player()
        self.send_msg('狼人请闭眼', tts=True)
        await asyncio.sleep(3)

        # 预言家
        if Role.DETECTIVE in self.roles:
            self.stage = GameStage.DETECTIVE
            self.send_msg('预言家请出现', tts=True)
            await self.wait_for_player()
            self.send_msg('预言家请闭眼', tts=True)
            await asyncio.sleep(3)

        # 女巫
        if Role.WITCH in self.roles:
            self.stage = GameStage.WITCH
            self.send_msg('女巫请出现', tts=True)
            await self.wait_for_player()
            self.send_msg('女巫请闭眼', tts=True)
            await asyncio.sleep(3)

        # 守卫
        if Role.GUARD in self.roles:
            self.stage = GameStage.GUARD
            self.send_msg('守卫请出现', tts=True)
            await self.wait_for_player()
            self.send_msg('守卫请闭眼', tts=True)
            await asyncio.sleep(3)

        # 猎人
        if Role.HUNTER in self.roles:
            self.stage = GameStage.HUNTER
            self.send_msg('猎人请出现', tts=True)
            await self.wait_for_player()
            self.send_msg('猎人请闭眼', tts=True)
            await asyncio.sleep(3)

        # 检查结果
        self.check_result()

    def check_result(self, is_vote=False):
        out_result = []  # 本局出局
        # 存活列表
        wolf_team = []
        citizen_team = []
        god_team = []
        for nick, user in self.players.items():
            if user.status in [
                PlayerStatus.ALIVE,
                PlayerStatus.PENDING_HEAL,
                PlayerStatus.PENDING_GUARD
            ]:
                if user.role in [Role.WOLF, Role.WOLF_KING]:
                    wolf_team.append(1)
                elif user.role in [Role.CITIZEN]:
                    citizen_team.append(1)
                else:
                    god_team.append(1)
                # 设置为 ALIVE
                self.players[nick].status = PlayerStatus.ALIVE

            # 设置为 DEAD
            if user.status == PlayerStatus.PENDING_DEAD:
                self.players[nick].status = PlayerStatus.DEAD
                out_result.append(nick)

        if not citizen_team or not god_team:  # TODO: 没有判断无神状态
            self.stop_game('狼人胜利')
        elif not wolf_team:
            self.stop_game('好人胜利')
        elif not is_vote:
            self.stage = GameStage.Day
            self.send_msg(f'天亮了，昨夜 {"无人" if not out_result else "，".join(out_result)} 出局', tts=True)
            self.send_msg('等待投票')

    async def vote_kill(self, nick):
        self.players[nick].status = PlayerStatus.DEAD
        self.check_result()
        if self.started:
            await self.start_game()

    async def wait_for_player(self):
        self.waiting = True
        while True:
            await asyncio.sleep(0.1)
            if self.waiting is False:
                self.stage = None
                break

    async def start_game(self):
        """开始游戏/下一夜"""
        if not self.started and self.logic_thread is not None and not self.logic_thread.closed():
            logger.error('没有正确关闭上一局游戏')
            raise AssertionError

        if not self.started:
            if len(self.players) != len(self.roles):
                self.send_msg('人数不足，无法开始游戏')
                return

            # 游戏状态
            self.started = True

            # 分配身份
            self.send_msg('游戏开始，请查看你的身份', tts=True)
            random.shuffle(self.roles_pool)
            for nick in self.players:
                self.players[nick].role = self.roles_pool.pop()
                self.players[nick].status = PlayerStatus.ALIVE
                # 女巫道具
                if self.players[nick].role == Role.WITCH:
                    self.players[nick].skill['poison'] = True
                    self.players[nick].skill['heal'] = True
                # 守卫守护记录
                if self.players[nick].role == Role.GUARD:
                    self.players[nick].skill['last_protect'] = None
                self.send_msg(f'你的身份是 "{self.players[nick].role}"', target=nick)
            await asyncio.sleep(5)

        self.round += 1
        self.logic_thread = run_async(self.night_logic())

    def stop_game(self, reason=''):
        """结束游戏，在投票阶段以及夜晚最后阶段被调用"""
        #
        # self.logic_thread.close()
        # self.logic_thread = None
        self.started = False
        self.roles_pool = copy(self.roles)
        self.round = 0
        self.stage = None
        self.waiting = False

        self.send_msg(f'游戏结束，{reason}。', tts=True)
        for nick, user in self.players.items():
            self.send_msg(f'{nick}：{user.role} ({user.status})')
            self.players[nick].role = None
            self.players[nick].status = None

    def list_alive_players(self) -> list:
        """返回存活的 User，包括 PENDING_DEAD 状态的玩家"""
        return [user for user in self.players.values() if user.status != PlayerStatus.DEAD]

    def list_pending_kill_players(self) -> list:
        return [user for user in self.players.values() if user.status == PlayerStatus.PENDING_DEAD]

    def is_full(self) -> bool:
        return len(self.players) >= len(self.roles)

    def add_player(self, user: 'User'):
        """添加一个用户到房间"""
        if user.room or user.nick in self.players:
            raise AssertionError
        self.players[user.nick] = user
        user.room = self
        user.start_syncer()  # will run later

        players_status = f'人数 {len(self.players)}/{len(self.roles)}，房主是 {self.get_host()}'
        user.game_msg.append(players_status)
        self.send_msg(players_status)
        logger.info(f'用户 "{user.nick}" 加入房间 "{self.id}"')

    def remove_player(self, user: 'User'):
        """将用户从房间移除"""
        if user.nick not in self.players:
            raise AssertionError
        self.players.pop(user.nick)
        user.stop_syncer()
        user.room = None

        if not self.players:
            Global.remove_room(self.id)
            return

        self.send_msg(f'人数 {len(self.players)}/{len(self.roles)}，房主是 {self.get_host()}')
        logger.info(f'用户 "{user.nick}" 离开房间 "{self.id}"')

    def get_host(self):
        if not self.players:
            return None
        return next(iter(self.players.values()))

    def send_msg(self, text, target: str = None, tts=False):
        """广播一条消息到所有房间内玩家"""
        if tts:
            say(text)
        if not target:
            target = Config.SYS_NICK

        self.log.append((target, text))

    def desc(self):
        return f'房间号 {self.id}，' \
               f'需要玩家 {len(self.roles)} 人，' \
               f'人员配置：{dict(Counter(self.roles))}'

    @classmethod
    def alloc(cls, room_setting) -> 'Room':
        """Create room by setting and register it to global storage"""
        # build full role list
        roles = []
        roles.extend([Role.WOLF] * room_setting['wolf_num'])
        roles.extend([Role.CITIZEN] * room_setting['citizen_num'])
        roles.extend(Role.from_option(room_setting['god_wolf']))
        roles.extend(Role.from_option(room_setting['god_citizen']))

        # Go
        return Global.reg_room(
            cls(
                id=None,
                # Static settings
                roles=copy(roles),
                witch_rule=WitchRule.from_option(room_setting['witch_rule']),
                guard_rule=GuardRule.from_option(room_setting['guard_rule']),
                # Dynamic
                started=False,
                roles_pool=copy(roles),
                players=dict(),
                round=0,
                stage=None,
                waiting=False,
                log=list(),
                # Internal
                logic_thread=None,
            )
        )

    @classmethod
    def get(cls, room_id) -> Optional['Room']:
        """获取一个已存在的房间"""
        return Global.get_room(room_id)

    @classmethod
    def validate_room_join(cls, room_id):
        room = cls.get(room_id)
        if not room:
            return '房间不存在'
        if room.is_full():
            return '房间已满'
