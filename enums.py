from enum import Enum
from typing import Union


class LogCtrl(Enum):
    """广播目标为 None 的，特殊控制消息类型枚举"""
    RemoveInput = '移除当前输入框'


class PlainEnum(Enum):

    def __repr__(self):
        return self.value

    __str__ = __repr__


class PlayerStatus(PlainEnum):
    ALIVE = '存活'
    DEAD = '出局'
    PENDING_DEAD = '被狼人/女巫/守救冲突杀害'
    PENDING_HEAL = '被女巫解救'
    PENDING_POISON = '被女巫毒害'
    PENDING_GUARD = '被守卫守护'


class GameStage(Enum):
    Day = 'Day'
    WOLF = '狼人'
    DETECTIVE = '预言家'
    WITCH = '女巫'
    GUARD = '守卫'
    HUNTER = '猎人'


class Role(PlainEnum):
    WOLF = '狼人'  # 狼人
    WOLF_KING = '狼王'  # 狼王
    DETECTIVE = '预言家'  # 预言家
    WITCH = '女巫'  # 女巫
    GUARD = '守卫'  # 守卫
    HUNTER = '猎人'  # 猎人
    CITIZEN = '平民'  # 平民

    @classmethod
    def as_god_citizen_options(cls) -> list:
        return list(cls.god_citizen_mapping().keys())

    @classmethod
    def as_god_wolf_options(cls) -> list:
        return list(cls.god_wolf_mapping().keys())

    @classmethod
    def from_option(cls, option: Union[str, list]):
        if isinstance(option, list):
            return [cls.mapping()[item] for item in option]
        elif isinstance(option, str):
            return cls.mapping()[option]
        else:
            raise NotImplementedError

    @classmethod
    def normal_mapping(cls) -> dict:
        return {
            '狼人': cls.WOLF,
            '平民': cls.CITIZEN,
        }

    @classmethod
    def god_wolf_mapping(cls) -> dict:
        return {
            '狼王': cls.WOLF_KING
        }

    @classmethod
    def god_citizen_mapping(cls) -> dict:
        return {
            '预言家': cls.DETECTIVE,
            '女巫': cls.WITCH,
            '守卫': cls.GUARD,
            '猎人': cls.HUNTER,
        }

    @classmethod
    def mapping(cls) -> dict:
        return dict(**cls.normal_mapping(), **cls.god_wolf_mapping(), **cls.god_citizen_mapping())


class WitchRule(Enum):
    SELF_RESCUE_FIRST_NIGHT_ONLY = '仅第一夜可自救'
    NO_SELF_RESCUE = '不可自救'
    ALWAYS_SELF_RESCUE = '始终可自救'

    @classmethod
    def as_options(cls) -> list:
        return list(cls.mapping().keys())

    @classmethod
    def from_option(cls, option: Union[str, list]):
        if isinstance(option, list):
            return [cls.mapping()[item] for item in option]
        elif isinstance(option, str):
            return cls.mapping()[option]
        else:
            raise NotImplementedError

    @classmethod
    def mapping(cls) -> dict:
        return {
            '仅第一夜可自救': cls.SELF_RESCUE_FIRST_NIGHT_ONLY,
            '始终可自救': cls.ALWAYS_SELF_RESCUE,
            '不可自救': cls.NO_SELF_RESCUE,
        }


class GuardRule(Enum):
    MED_CONFLICT = '同时被守被救时，对象死亡'
    NO_MED_CONFLICT = '同时被守被救时，对象存活'

    @classmethod
    def as_options(cls) -> list:
        return list(cls.mapping().keys())

    @classmethod
    def from_option(cls, option: Union[str, list]):
        if isinstance(option, list):
            return [cls.mapping()[item] for item in option]
        elif isinstance(option, str):
            return cls.mapping()[option]
        else:
            raise NotImplementedError

    @classmethod
    def mapping(cls) -> dict:
        return {
            '同时被守被救时，对象死亡': cls.MED_CONFLICT,
            '同时被守被救时，对象存活': cls.NO_MED_CONFLICT,
        }
