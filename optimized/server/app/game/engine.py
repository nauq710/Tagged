"""STUDENT-EDITABLE: reference world state and deterministic simulation.

You may replace state representation and synchronization but must preserve rules.py.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import random

from .rules import (WIDTH, HEIGHT, TICK_RATE, SNAPSHOT_RATE, ROOM_CAPACITY,
                    MOVE_SPEED, BASE_RADIUS, CLOAK_TICKS, CLOAK_COST,
                    DECAY_INTERVAL_TICKS, speed_for, decay_for,
                    KILL_TRANSFER_RATE, COLLECTIBLES, radius_for, cardinal,
                    can_cloak, visible_to, transfer_on_kill, predator_wins, should_finish)


@dataclass
class Player:
    id: str
    name: str
    x: float
    y: float
    credits: int = 0
    alive: bool = True
    seq: int = -1
    dx: int = 0
    dy: int = 0
    cloak_pending: bool = False
    invisible_until: int = 0
    next_decay_tick: int = 0

    @property
    def radius(self) -> float:
        return radius_for(self.credits)


@dataclass
class Item:
    id: int
    tier: str
    value: int
    x: float
    y: float
    radius: int


class World:
    """Room state with deterministic tick-based mechanics and seeded item spawns."""
    def __init__(self, room: str, seed: int = 2026):
        self.room, self.tick, self.round = room, 0, 0
        self.phase = 'waiting'  # waiting | running | finished
        self.winner: str | None = None
        self.rng = random.Random(seed)
        self.players: dict[str, Player] = {}
        self.events: list[dict] = []
        self.event_id = 0
        self.items: list[Item] = []
        item_id = 0
        for tier, (count, value, rad) in COLLECTIBLES.items():
            for _ in range(count):
                self.items.append(self._make_item(item_id, tier, value, rad))
                item_id += 1

    def _spawn(self, margin: int = 40) -> tuple[float, float]:
        # One RNG stream per room gives repeatable reference runs.
        for _ in range(100):
            x = float(self.rng.randint(margin, WIDTH-margin))
            y = float(self.rng.randint(margin, HEIGHT-margin))
            if all(math.hypot(x-p.x, y-p.y) > p.radius + 40 for p in self.players.values() if p.alive):
                return x, y
        return float(self.rng.randint(margin, WIDTH-margin)), float(self.rng.randint(margin, HEIGHT-margin))

    def _make_item(self, item_id: int, tier: str, value: int, radius: int) -> Item:
        x, y = self._spawn()
        return Item(item_id, tier, value, x, y, radius)

    def _event(self, kind: str, **data: object) -> None:
        self.event_id += 1
        self.events.append({'id': self.event_id, 'type': kind, 'tick': self.tick, **data})
        self.events = self.events[-32:]

    def _start_round(self) -> None:
        self.round += 1
        self.phase, self.winner = 'running', None
        for player_id in sorted(self.players):
            player = self.players[player_id]
            player.credits, player.alive = 0, True
            player.seq, player.dx, player.dy = -1, 0, 0
            player.cloak_pending, player.invisible_until = False, 0
            player.next_decay_tick = self.tick + DECAY_INTERVAL_TICKS
            player.x, player.y = self._spawn()
        self._event('start', round=self.round)

    def add_player(self, player_id: str, name: str) -> Player:
        if len(self.players) >= ROOM_CAPACITY:
            raise ValueError('Room full')
        if player_id in self.players:
            raise ValueError('Duplicate player')
        x, y = self._spawn()
        player = Player(player_id, name, x, y, next_decay_tick=self.tick + DECAY_INTERVAL_TICKS)
        self.players[player_id] = player
        self._event('join', actor=player_id)
        if self.phase == 'waiting' and len(self.players) >= 2:
            self._start_round()
        elif self.phase == 'finished' and len(self.alive_players()) >= 2:
            self._start_round()
        return player

    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def remove_player(self, player_id: str) -> None:
        if player_id not in self.players:
            return
        del self.players[player_id]
        self._event('leave', actor=player_id)
        self._finish_if_needed()

    def rejoin(self, player_id: str) -> bool:
        player = self.players.get(player_id)
        if player is None or (player.alive and self.phase != 'finished'):
            return False
        player.credits, player.alive = 0, True
        player.seq, player.dx, player.dy = -1, 0, 0
        player.cloak_pending, player.invisible_until = False, 0
        player.next_decay_tick = self.tick + DECAY_INTERVAL_TICKS
        player.x, player.y = self._spawn()
        self._event('rejoin', actor=player_id)
        if self.phase == 'finished' and len(self.alive_players()) >= 2:
            self._start_round()
        return True

    def accept_input(self, player_id: str, seq: int, dx: int, dy: int, cloak: bool) -> bool:
        player = self.players.get(player_id)
        if player is None or not player.alive or self.phase != 'running' or seq <= player.seq:
            return False
        if not cardinal(dx, dy):
            return False
        player.seq, player.dx, player.dy = seq, dx, dy
        player.cloak_pending = player.cloak_pending or cloak
        return True

    def _finish_if_needed(self) -> None:
        if should_finish(self.phase, len(self.alive_players())):
            self.phase = 'finished'
            alive = self.alive_players()
            self.winner = alive[0].id if alive else None
            self._event('finish', winner=self.winner)

    def step(self) -> None:
        self.tick += 1
        if self.phase != 'running':
            return
        dt = 1 / TICK_RATE
        # Process movement + ability in stable ID order.
        for player_id in sorted(self.players):
            player = self.players[player_id]
            if not player.alive:
                continue
            if player.cloak_pending:
                player.cloak_pending = False
                if can_cloak(player.credits, self.tick, player.invisible_until):
                    player.credits -= CLOAK_COST
                    player.invisible_until = self.tick + CLOAK_TICKS
                    self._event('cloak', actor=player.id, cost=CLOAK_COST)
            radius = player.radius
            player.x = max(radius, min(WIDTH-radius, player.x + player.dx*speed_for(player.credits)*dt))
            player.y = max(radius, min(HEIGHT-radius, player.y + player.dy*speed_for(player.credits)*dt))

        # Collectibles: one pickup per item/tick, nearest player wins ties by ID.
        for index, item in enumerate(self.items):
            near = [p for p in self.alive_players() if math.hypot(p.x-item.x, p.y-item.y) <= p.radius + item.radius]
            if not near:
                continue
            eater = min(near, key=lambda p: (math.hypot(p.x-item.x, p.y-item.y), p.id))
            eater.credits += item.value
            self._event('collect', actor=eater.id, tier=item.tier, value=item.value, credits=eater.credits)
            self.items[index] = self._make_item(item.id, item.tier, item.value, item.radius)

        # Resolution order makes simultaneous contacts deterministic.
        # Invisibility conceals position but does NOT confer collision immunity.
        living = sorted(self.alive_players(), key=lambda p: (-p.credits, p.id))
        for strong in living:
            if not strong.alive:
                continue
            for weak in living:
                if weak.id == strong.id or not weak.alive or not predator_wins(strong.credits, weak.credits):
                    continue
                if math.hypot(strong.x-weak.x, strong.y-weak.y) <= strong.radius+weak.radius:
                    transferred = transfer_on_kill(weak.credits)
                    weak.alive, weak.dx, weak.dy, weak.cloak_pending = False, 0, 0, False
                    strong.credits += transferred
                    self._event('kill', actor=strong.id, target=weak.id, transferred=transferred)
        # Decay happens after movement, pickup and collisions. Each player's
        # interval is measured from their spawn/rejoin, not global room start.
        for player_id in sorted(self.players):
            player = self.players[player_id]
            if player.alive and self.tick >= player.next_decay_tick:
                old_credits = player.credits
                player.credits = max(0, old_credits - decay_for(old_credits))
                player.next_decay_tick += DECAY_INTERVAL_TICKS
                if player.credits != old_credits:
                    self._event('decay', actor=player_id, amount=old_credits - player.credits, credits=player.credits)
        self._finish_if_needed()

    def snapshot(self, viewer_id: str | None = None, reveal_hidden: bool = False) -> dict:
        # Player-specific projection: invisible players are visible only to themselves.
        return {
            'type': 'snapshot', 'room': self.room, 'tick': self.tick,
            'phase': self.phase, 'round': self.round, 'winner': self.winner,
            'players': [
                {'id': p.id, 'name': p.name, 'x': round(p.x, 3), 'y': round(p.y, 3),
                 'credits': p.credits, 'radius': round(p.radius, 3), 'alive': p.alive,
                 'invisible': self.tick < p.invisible_until}
                for p in sorted(self.players.values(), key=lambda p: p.id)
                if reveal_hidden or not p.alive or visible_to(p.id, viewer_id, self.tick, p.invisible_until)
            ],
            'items': [{'id': i.id, 'tier': i.tier, 'value': i.value,
                       'x': i.x, 'y': i.y, 'radius': i.radius} for i in self.items],
            'events': list(self.events),
        }
