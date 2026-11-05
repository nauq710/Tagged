"""INSTRUCTOR-OWNED: canonical, transport-independent game rules. DO NOT EDIT.

Networking, state storage, encoding, prediction and delivery may be redesigned.
The observable outcome of these pure gameplay rules may not be changed.
"""
from __future__ import annotations
import math

WIDTH, HEIGHT = 960, 600
TICK_RATE, SNAPSHOT_RATE, ROOM_CAPACITY = 20, 10, 20
MOVE_SPEED, BASE_RADIUS = 170.0, 14.0
MIN_MOVE_SPEED, SPEED_SCALE = 65.0, 0.09
DECAY_INTERVAL_TICKS, DECAY_RATE = 5 * TICK_RATE, 0.02
CLOAK_TICKS, CLOAK_COST = 3 * TICK_RATE, 5
KILL_TRANSFER_RATE = .40
COLLECTIBLES = {'small': (18, 1, 6), 'medium': (10, 3, 9), 'large': (4, 7, 13)}


def radius_for(credits: int) -> float:
    return BASE_RADIUS + min(22.0, math.sqrt(credits) * 2.0)


def speed_for(credits: int) -> float:
    """Move speed decreases as credit increases, with a safe lower bound."""
    return max(MIN_MOVE_SPEED, MOVE_SPEED / (1.0 + SPEED_SCALE * math.sqrt(max(0, credits))))


def decay_for(credits: int) -> int:
    """Credits lost each decay interval (2% rounded up, or zero when empty)."""
    return min(max(0, credits), math.ceil(max(0, credits) * DECAY_RATE))


def cardinal(dx: int, dy: int) -> bool:
    return (type(dx) is int and type(dy) is int and
            dx in (-1, 0, 1) and dy in (-1, 0, 1) and abs(dx) + abs(dy) <= 1)


def can_cloak(credits: int, current_tick: int, invisible_until: int) -> bool:
    return credits >= CLOAK_COST and current_tick >= invisible_until


def visible_to(player_id: str, viewer_id: str | None, current_tick: int, invisible_until: int) -> bool:
    return player_id == viewer_id or current_tick >= invisible_until


def transfer_on_kill(loser_credits: int) -> int:
    return math.ceil(loser_credits * KILL_TRANSFER_RATE)


def predator_wins(predator_credits: int, prey_credits: int) -> bool:
    return predator_credits > prey_credits


def should_finish(phase: str, alive_count: int) -> bool:
    return phase == 'running' and alive_count <= 1
