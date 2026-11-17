"""Student-editable room/session state and orchestration; do not change the rules."""
from __future__ import annotations
from hashlib import sha256
import re
import uuid
from .engine import World
from .rules import HEIGHT, ROOM_CAPACITY, SNAPSHOT_RATE, TICK_RATE, WIDTH

ROOM_NAME = re.compile(r'^[a-zA-Z0-9_-]{1,20}$')

class GameService:
    def __init__(self) -> None:
        self.rooms: dict[str, World] = {}
        self.player_rooms: dict[str, str] = {}
        self.simulator_rooms: set[str] = set()
        self.session_players: dict[str, str] = {}  # session_token -> player_id
        self.player_sessions: dict[str, str] = {}  # player_id -> session_token

    def join(self, name: str, room: str, session_token: str | None = None) -> dict:
        if not ROOM_NAME.fullmatch(room):
            raise ValueError('Room must be 1-20 letters, numbers, _ or -')
        name = name.strip()[:18]
        if not name:
            raise ValueError('Player name required')
        if room not in self.rooms:
            seed = int.from_bytes(sha256(room.encode()).digest()[:4], 'big')
            self.rooms[room] = World(room, seed)

        world = self.rooms[room]
        player_id = None
        resumed = False
        # Persistent identity: if session_token provided and player already in room, reconnect!
        if session_token and session_token in self.session_players:
            existing_pid = self.session_players[session_token]
            if existing_pid in world.players:
                player_id = existing_pid
                p = world.players[player_id]
                p.name = name
                p.seq = -1
                p.dx = 0
                p.dy = 0
                self.player_rooms[player_id] = room
                resumed = True
                if world.phase == 'waiting' and len(world.players) >= 2:
                    world._start_round()

        if player_id is None:
            player_id = uuid.uuid4().hex[:12]
            world.add_player(player_id, name)
            self.player_rooms[player_id] = room
            if session_token:
                self.session_players[session_token] = player_id
                self.player_sessions[player_id] = session_token

        welcome = {'type': 'welcome', 'id': player_id, 'room': room, 'width': WIDTH,
                   'height': HEIGHT, 'tick_rate': TICK_RATE, 'snapshot_rate': SNAPSHOT_RATE,
                   'room_capacity': ROOM_CAPACITY}
        if resumed:
            welcome['resumed'] = True
        return welcome

    def start_sim_room(self, room: str) -> None:
        if room in self.rooms:
            raise ValueError('Scenario room already in use')
        seed = int.from_bytes(sha256(room.encode()).digest()[:4], 'big')
        self.rooms[room] = World(room, seed)
        self.simulator_rooms.add(room)

    def sim_join(self, actor: str, room: str, run_id: str, name: str) -> dict:
        if room not in self.simulator_rooms:
            raise ValueError('Scenario room is not reserved')
        player_id = f'_sim_{run_id}_{actor}'
        self.rooms[room].add_player(player_id, name)
        self.player_rooms[player_id] = room
        return {'type': 'welcome', 'id': player_id, 'room': room,
                'width': WIDTH, 'height': HEIGHT, 'tick_rate': TICK_RATE,
                'snapshot_rate': SNAPSHOT_RATE, 'room_capacity': ROOM_CAPACITY}

    def sim_step(self, room: str) -> dict:
        if room not in self.simulator_rooms or room not in self.rooms:
            raise ValueError('Scenario room unavailable')
        self.rooms[room].step()
        return self.rooms[room].snapshot(reveal_hidden=True)

    def finish_sim_room(self, room: str) -> None:
        if room in self.simulator_rooms:
            for player_id in list(self.rooms.get(room).players if room in self.rooms else []):
                self.player_rooms.pop(player_id, None)
            self.rooms.pop(room, None)
            self.simulator_rooms.discard(room)

    def leave(self, player_id: str, clear_session: bool = True) -> None:
        room = self.player_rooms.pop(player_id, None)
        if clear_session:
            token = self.player_sessions.pop(player_id, None)
            if token:
                self.session_players.pop(token, None)
        if room is not None and room in self.rooms:
            self.rooms[room].remove_player(player_id)
            if not self.rooms[room].players and room not in self.simulator_rooms:
                del self.rooms[room]

    def rejoin(self, player_id: str) -> bool:
        room = self.player_rooms.get(player_id)
        return self.rooms[room].rejoin(player_id) if room else False

    def apply_input(self, player_id: str, seq: int, dx: int, dy: int, cloak: bool) -> bool:
        room = self.player_rooms.get(player_id)
        return self.rooms[room].accept_input(player_id, seq, dx, dy, cloak) if room else False

    def snapshot_for(self, player_id: str) -> dict | None:
        room = self.player_rooms.get(player_id)
        return self.rooms[room].snapshot(viewer_id=player_id) if room else None

    def advance(self) -> dict[str, dict]:
        for room, world in self.rooms.items():
            if room not in self.simulator_rooms:
                world.step()
        return {room: world.snapshot(reveal_hidden=True) for room, world in self.rooms.items()}
