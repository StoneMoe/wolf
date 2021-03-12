from typing import Dict, TYPE_CHECKING

from utils import rand_int

if TYPE_CHECKING:
    from .room import Room


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
