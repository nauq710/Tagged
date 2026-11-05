"""Shared input/output fixture contract for browser-driven deterministic replay.

This module defines mechanics outcomes, not any particular wire protocol.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import re
from pathlib import Path

from app.game.engine import World
from app.game.rules import TICK_RATE, cardinal

RUN_ID = re.compile(r'^[A-Za-z0-9_-]{3,32}$')
PLAYER_ID = re.compile(r'^[A-Za-z0-9_-]{1,18}$')
MAX_TICKS, MAX_EVENTS, MAX_PLAYERS = 600, 1500, 8
OPS = {'join', 'leave', 'rejoin', 'input'}


def scenario_digest(scenario: dict) -> str:
    return sha256(json.dumps(scenario, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_scenario(obj: object) -> tuple[dict, list[str]]:
    if not isinstance(obj, dict):
        raise ValueError('Scenario must be a JSON object')
    if obj.get('version') != 1:
        raise ValueError('Scenario version must be 1')
    if not isinstance(obj.get('name'), str) or not (1 <= len(obj['name']) <= 80):
        raise ValueError('Invalid scenario name')
    if not isinstance(obj.get('room'), str) or not RUN_ID.fullmatch(obj['room']):
        raise ValueError('Room must be 3-32 alphanumeric/_/- characters')
    ticks = obj.get('ticks')
    if type(ticks) is not int or not (2 <= ticks <= MAX_TICKS):
        raise ValueError('ticks must be an integer between 2 and 600')
    events = obj.get('events')
    if not isinstance(events, list) or not (2 <= len(events) <= MAX_EVENTS):
        raise ValueError('events must contain 2-1500 actions')
    previous_tick = -1
    current_actor = None
    completed_actors: set[str] = set()
    names: dict[str, str] = {}
    first_op: dict[str, str] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f'Event #{index} is not an object')
        tick, op, actor = event.get('tick'), event.get('op'), event.get('player')
        if type(tick) is not int or not (0 <= tick < ticks) or tick < previous_tick:
            raise ValueError(f'Event #{index} has an invalid/out-of-order tick')
        if tick != previous_tick:
            current_actor = None
            completed_actors.clear()
        if actor != current_actor:
            if actor in completed_actors:
                raise ValueError('Group each player\'s same-tick actions contiguously')
            completed_actors.add(actor)
            current_actor = actor
        previous_tick = tick
        if op not in OPS or not isinstance(actor, str) or not PLAYER_ID.fullmatch(actor):
            raise ValueError(f'Event #{index} has invalid op or player')
        if actor not in first_op:
            first_op[actor] = op
            if op != 'join':
                raise ValueError(f'{actor}: first event must be join')
        if op == 'join':
            if actor in names:
                raise ValueError(f'{actor}: duplicate join (use rejoin)')
            name = event.get('name', actor)
            if not isinstance(name, str) or not (1 <= len(name) <= 18):
                raise ValueError(f'{actor}: invalid name')
            names[actor] = name
        if op == 'input':
            if (type(event.get('seq')) is not int or event['seq'] < 0
                or not cardinal(event.get('dx'), event.get('dy'))
                or type(event.get('cloak', False)) is not bool):
                raise ValueError(f'Event #{index}: invalid input')
    if not 2 <= len(names) <= MAX_PLAYERS:
        raise ValueError('Scenario must have 2-8 distinct player slots')
    if events[0]['tick'] != 0:
        raise ValueError('At least one player must join at tick 0')
    # Normalize permitted fields only, so all browsers hash identical semantics.
    sanitized = {
        'version': 1, 'name': obj['name'], 'room': obj['room'], 'ticks': ticks,
        'events': [
            ({'tick': e['tick'], 'op': e['op'], 'player': e['player']}
             | ({'name': e.get('name', e['player'])} if e['op'] == 'join' else {})
             | ({'seq': e['seq'], 'dx': e['dx'], 'dy': e['dy'],
                 'cloak': e.get('cloak', False)} if e['op'] == 'input' else {}))
            for e in events
        ],
    }
    return sanitized, list(names)


def canonical_outcome(world: World | None, identities: dict[str, str] | None = None) -> dict | None:
    if world is None or world.phase != 'finished':
        return None
    identities = identities or {}
    return {
        'phase': 'finished',
        'round': world.round,
        'winner': identities.get(world.winner, world.winner),
        'players': {
            identities.get(actor, actor): {'alive': player.alive, 'credits': player.credits}
            for actor, player in sorted(world.players.items())
        },
    }


def pinned_expected(scenario: dict) -> tuple[dict | None, str]:
    """Use published immutable expected JSON, not submission game code, to grade fixtures.

    For custom scenarios use the local oracle for debugging only. An external
    grading service can hold secret input/expected pairs outside student repos.
    """
    directory = Path(__file__).resolve().parents[3] / 'scenarios' / 'browser'
    digest = scenario_digest(scenario)
    for path in directory.glob('*.expected.json'):
        try:
            content = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if content.get('scenario_sha256') == digest:
            return content.get('expected'), 'pinned_fixture'
    return replay_oracle(scenario), 'local_reference'



def apply_event(world: World, event: dict) -> None:
    actor, op = event['player'], event['op']
    if op == 'join':
        world.add_player(actor, event.get('name', actor))
    elif op == 'leave':
        world.remove_player(actor)
    elif op == 'rejoin':
        world.rejoin(actor)
    elif op == 'input':
        world.accept_input(actor, event['seq'], event['dx'], event['dy'],
                           event.get('cloak', False))


def make_world(scenario: dict) -> World:
    room = scenario['room']
    seed = int.from_bytes(sha256(room.encode()).digest()[:4], 'big')
    return World(room, seed)


def replay_oracle(scenario: dict) -> dict | None:
    world = make_world(scenario)
    events_by_tick: dict[int, list[dict]] = defaultdict(list)
    for event in scenario['events']:
        events_by_tick[event['tick']].append(event)
    for tick in range(scenario['ticks']):
        for event in events_by_tick[tick]:
            apply_event(world, event)
        world.step()
    return canonical_outcome(world)


def result_report(scenario: dict, actual: dict | None, *,
                  run_id: str, elapsed_seconds: float,
                  responses: int, timeout_count: int, error: str | None = None) -> dict:
    expected, oracle_source = pinned_expected(scenario)
    differences = []
    if expected is None:
        differences.append('Scenario did not end in a completed round')
    if actual != expected:
        differences.append('Final game outcome differs from expected output')
    if error:
        differences.append(error)
    return {
        'format': 'tag-lagged-browser-result-v1',
        'run_id': run_id,
        'scenario': scenario['name'],
        'scenario_sha256': scenario_digest(scenario),
        'expected': expected,
        'actual': actual,
        'oracle_source': oracle_source,
        'verdict': 'PASS' if not differences else 'FAIL',
        'differences': differences,
        'stats': {
            'elapsed_seconds': round(elapsed_seconds, 3),
            'tick_count': scenario['ticks'],
            'action_batches_received': responses,
            'timeouts': timeout_count,
        },
    }
