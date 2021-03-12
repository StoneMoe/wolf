import asyncio
import random
from collections import Counter
from copy import copy
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Union

from pywebio import run_async
from pywebio.session.coroutinebased import TaskHandle

from enums import Role, WitchRule, GuardRule, GameStage, LogCtrl, PlayerStatus
from models.system import Global, Config
from models.user import User
from utils import say
from . import logger


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
    log: List[Tuple[Union[str, None], Union[str, LogCtrl]]]  # 广播消息源，(目标, 内容)

    # Internal
    logic_thread: Optional[TaskHandle]

    async def night_logic(self):
        """单夜逻辑"""
        # 开始
        self.round += 1
        self.broadcast_msg('天黑请闭眼', tts=True)
        await asyncio.sleep(3)

        # 狼人
        self.stage = GameStage.WOLF
        self.broadcast_msg('狼人请出现', tts=True)
        await self.wait_for_player()
        self.broadcast_msg('狼人请闭眼', tts=True)
        await asyncio.sleep(3)

        # 预言家
        if Role.DETECTIVE in self.roles:
            self.stage = GameStage.DETECTIVE
            self.broadcast_msg('预言家请出现', tts=True)
            await self.wait_for_player()
            self.broadcast_msg('预言家请闭眼', tts=True)
            await asyncio.sleep(3)

        # 女巫
        if Role.WITCH in self.roles:
            self.stage = GameStage.WITCH
            self.broadcast_msg('女巫请出现', tts=True)
            await self.wait_for_player()
            self.broadcast_msg('女巫请闭眼', tts=True)
            await asyncio.sleep(3)

        # 守卫
        if Role.GUARD in self.roles:
            self.stage = GameStage.GUARD
            self.broadcast_msg('守卫请出现', tts=True)
            await self.wait_for_player()
            self.broadcast_msg('守卫请闭眼', tts=True)
            await asyncio.sleep(3)

        # 猎人
        if Role.HUNTER in self.roles:
            self.stage = GameStage.HUNTER
            self.broadcast_msg('猎人请出现', tts=True)
            await self.wait_for_player()
            self.broadcast_msg('猎人请闭眼', tts=True)
            await asyncio.sleep(3)

        # 检查结果
        self.check_result()

    def check_result(self, is_vote_check=False):
        """检查结果，在投票后、及夜晚结束时被调用"""
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
            if user.status in [PlayerStatus.PENDING_DEAD, PlayerStatus.PENDING_POISON]:
                self.players[nick].status = PlayerStatus.DEAD
                out_result.append(nick)

        if not citizen_team or (not self.is_no_god() and not god_team):
            self.stop_game('狼人胜利')
            return

        if not wolf_team:
            self.stop_game('好人胜利')
            return

        if not is_vote_check:
            self.stage = GameStage.Day
            self.broadcast_msg(f'天亮了，昨夜 {"无人" if not out_result else "，".join(out_result)} 出局', tts=True)
            self.broadcast_msg('等待投票')
            return

    async def vote_kill(self, nick):
        self.players[nick].status = PlayerStatus.DEAD
        self.check_result(is_vote_check=True)
        if self.started:
            self.enter_null_stage()
            await self.start_game()  # 下一夜

    async def wait_for_player(self):
        """玩家操作等待锁"""
        self.waiting = True
        while True:
            await asyncio.sleep(0.1)
            if self.waiting is False:
                self.broadcast_log_ctrl(LogCtrl.RemoveInput)
                break

    def enter_null_stage(self):
        """
        将当前游戏阶段设置为 None

        确保在"每个阶段逻辑结束时"调用本函数，以保证客户端 UI 状态正确
        """
        self.stage = None

    async def start_game(self):
        """开始游戏/下一夜"""
        if not self.started:
            if self.logic_thread is not None and not self.logic_thread.closed():
                logger.error('没有正确关闭上一局游戏')
                return

            if len(self.players) != len(self.roles):
                self.broadcast_msg('人数不足，无法开始游戏')
                return

            # 游戏状态
            self.started = True

            # 分配身份
            self.broadcast_msg('游戏开始，请查看你的身份', tts=True)
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
                self.players[nick].send_msg(f'你的身份是 "{self.players[nick].role}"')

            await asyncio.sleep(5)

        self.logic_thread = run_async(self.night_logic())

    def stop_game(self, reason=''):
        """结束游戏"""
        self.started = False
        self.roles_pool = copy(self.roles)
        self.round = 0
        self.enter_null_stage()
        self.waiting = False

        self.broadcast_msg(f'游戏结束，{reason}。', tts=True)
        for nick, user in self.players.items():
            self.broadcast_msg(f'{nick}：{user.role} ({user.status})')
            self.players[nick].role = None
            self.players[nick].status = None

    def list_alive_players(self) -> list:
        """返回存活的 User，包括 PENDING_DEAD 状态的玩家"""
        return [user for user in self.players.values() if user.status != PlayerStatus.DEAD]

    def list_pending_kill_players(self) -> list:
        return [user for user in self.players.values() if user.status == PlayerStatus.PENDING_DEAD]

    def is_full(self) -> bool:
        return len(self.players) >= len(self.roles)

    def is_no_god(self):
        """该房间未配置神"""
        god_roles = [Role.DETECTIVE, Role.WITCH, Role.HUNTER, Role.GUARD]
        for god in god_roles:
            if god in self.roles:
                return False
        return True

    def add_player(self, user: 'User'):
        """添加一个用户到房间"""
        if user.room or user.nick in self.players:
            raise AssertionError
        self.players[user.nick] = user
        user.room = self
        user.start_syncer()  # will run later

        players_status = f'人数 {len(self.players)}/{len(self.roles)}，房主是 {self.get_host()}'
        user.game_msg.append(players_status)
        self.broadcast_msg(players_status)
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

        self.broadcast_msg(f'人数 {len(self.players)}/{len(self.roles)}，房主是 {self.get_host()}')
        logger.info(f'用户 "{user.nick}" 离开房间 "{self.id}"')

    def get_host(self):
        if not self.players:
            return None
        return next(iter(self.players.values()))

    def send_msg(self, text: str, nick: str):
        """发送一条消息到指定玩家，仅指定的玩家可见"""
        self.log.append((nick, text))

    def broadcast_msg(self, text: str, tts=False):
        """广播一条消息到所有房间内玩家"""
        if tts:
            say(text)

        self.log.append((Config.SYS_NICK, text))

    def broadcast_log_ctrl(self, ctrl_type: LogCtrl):
        """广播特殊的客户端控制消息"""
        self.log.append((None, ctrl_type))

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
