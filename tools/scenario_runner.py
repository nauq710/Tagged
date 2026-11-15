#!/usr/bin/env python3
"""Student-editable controlled scenario runner for deterministic and live tests.

Oracle mode applies actions on exact simulation ticks. Live mode sends the same
intended timeline over baseline WebSockets, with optional message-level faults.
The final completed match result is checked against the offline oracle.
Intermediate ticks are recorded for diagnosis, never compared for grading.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import random
import sys
import time
from aiohttp import ClientSession, WSMsgType

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'server'))
from app.game.engine import World
from app.game.rules import TICK_RATE
from tools.final_outcome import canonical_terminal_outcome, merge_terminal_observations, compare_terminal_outcomes


def load(path: str) -> dict:
    scenario = json.loads(Path(path).read_text())
    assert isinstance(scenario['ticks'], int) and 1 <= scenario['ticks'] <= 20000
    assert isinstance(scenario['events'], list) and all(isinstance(e['tick'], int) and 0 <= e['tick'] < scenario['ticks'] for e in scenario['events'])
    return scenario


def replay(scenario: dict) -> dict:
    room = scenario['room']
    seed = int.from_bytes(sha256(room.encode()).digest()[:4], 'big')
    world = World(room, seed)
    trace = []
    events = defaultdict(list)
    for e in scenario['events']:
        events[e['tick']].append(e)
    for tick in range(scenario['ticks']):
        for event in events[tick]:
            key = event['player']
            match event['op']:
                case 'join': world.add_player(key, event.get('name', key))
                case 'leave': world.remove_player(key)
                case 'rejoin': world.rejoin(key)
                case 'input': world.accept_input(key, event['seq'], event['dx'], event['dy'], event.get('cloak', False))
                case _: raise ValueError(f"Unknown operation: {event['op']}")
        world.step()
        trace.append(world.snapshot(reveal_hidden=True))
    return {'name': scenario['name'], 'room': room, 'mode': 'oracle', 'ticks': scenario['ticks'],
            'trace': trace, 'final': trace[-1],
            'final_result': canonical_terminal_outcome(trace[-1])}


async def live(scenario: dict, args) -> dict:
    url = args.url.rstrip('/')
    if url.startswith('http://'): url = 'ws://' + url[7:]
    if url.startswith('https://'): url = 'wss://' + url[8:]
    if not url.endswith('/ws'): url += '/ws'
    rng = random.Random(args.seed)
    clients = {}
    observations: dict[str, list[dict]] = defaultdict(list)
    input_stats = {'sent': 0, 'dropped': 0, 'duplicated': 0, 'delayed': 0}
    player_ids: dict[str, str] = {}
    failures = []
    reader_jobs = []
    started = time.monotonic()
    events = defaultdict(list)
    for e in scenario['events']:
        events[e['tick']].append(e)

    async with ClientSession() as session:
        async def reader(key: str, ws):
            try:
                async for message in ws:
                    if message.type != WSMsgType.TEXT: continue
                    obj = json.loads(message.data)
                    if obj.get('type') == 'welcome' and isinstance(obj.get('id'), str):
                        player_ids[obj['id']] = key
                    elif obj.get('type') == 'snapshot':
                        observations[key].append(obj)
                    elif obj.get('type') == 'error':
                        failures.append(f'{key}: {obj.get("message")}')
            except (asyncio.CancelledError, Exception) as exc:
                if not isinstance(exc, asyncio.CancelledError):
                    failures.append(f'{key}: {exc}')

        async def send_input(key: str, ws, event: dict):
            if rng.random() < args.drop_rate:
                input_stats['dropped'] += 1
                return
            delay = max(0, args.delay_ms + rng.uniform(-args.jitter_ms, args.jitter_ms)) / 1000
            if delay: input_stats['delayed'] += 1
            await asyncio.sleep(delay)
            if ws.closed: return
            msg = {x: event[x] for x in ('seq', 'dx', 'dy')}
            msg.update(type='input', cloak=event.get('cloak', False))
            await ws.send_json(msg)
            input_stats['sent'] += 1
            if rng.random() < args.duplicate_rate:
                await ws.send_json(msg)
                input_stats['duplicated'] += 1

        send_jobs = []
        for tick in range(scenario['ticks']):
            target = started + tick / TICK_RATE
            await asyncio.sleep(max(0, target-time.monotonic()))
            for event in events[tick]:
                key = event['player']
                op = event['op']
                if op == 'join':
                    ws = await session.ws_connect(url, heartbeat=20, timeout=10)
                    clients[key] = ws
                    await ws.send_json({'type': 'join', 'room': scenario['room'], 'name': event.get('name', key)})
                    reader_jobs.append(asyncio.create_task(reader(key, ws)))
                elif op == 'leave':
                    if key in clients: await clients[key].close()
                elif op == 'rejoin':
                    if key in clients: await clients[key].send_json({'type': 'rejoin'})
                elif op == 'input':
                    if key in clients: send_jobs.append(asyncio.create_task(send_input(key, clients[key], event)))
        if send_jobs: await asyncio.gather(*send_jobs, return_exceptions=True)
        await asyncio.sleep(args.settle_seconds)
        active_clients = {key for key, ws in clients.items() if not ws.closed}
        for ws in clients.values():
            if not ws.closed: await ws.close()
        await asyncio.gather(*reader_jobs, return_exceptions=True)

    # Only the completed match outcome is a grading oracle. Snapshots from
    # intermediate ticks are diagnostic samples, not required to match.
    expected = canonical_terminal_outcome(replay(scenario)['final'])
    final_observations = {
        key: values[-1] for key, values in observations.items()
        if key in active_clients and values
    }
    actual, observation_errors = merge_terminal_observations(final_observations, player_ids)
    comparison = compare_terminal_outcomes(expected, actual, observation_errors)
    return {
        'name': scenario['name'], 'room': scenario['room'], 'mode': 'live',
        'url': url,
        'profile': {
            'delay_ms': args.delay_ms, 'jitter_ms': args.jitter_ms,
            'drop_rate': args.drop_rate, 'duplicate_rate': args.duplicate_rate,
        },
        'intended_ticks': scenario['ticks'], 'clients': len(clients),
        'input': input_stats,
        'observed': {
            key: {
                'snapshots': len(values), 'first_tick': values[0]['tick'] if values else None,
                'last_tick': values[-1]['tick'] if values else None,
                'last_phase': values[-1]['phase'] if values else None,
            } for key, values in observations.items()
        },
        'final_result': actual,
        'final_comparison': comparison,
        'errors': failures,
    }

def main():
    p = argparse.ArgumentParser(description='Offline deterministic oracle or live WebSocket scenario')
    p.add_argument('scenario')
    p.add_argument('--mode', choices=('oracle', 'live'), default='oracle')
    p.add_argument('--url', default='http://127.0.0.1:8000')
    p.add_argument('--delay-ms', type=float, default=0)
    p.add_argument('--jitter-ms', type=float, default=0)
    p.add_argument('--drop-rate', type=float, default=0)
    p.add_argument('--duplicate-rate', type=float, default=0)
    p.add_argument('--settle-seconds', type=float, default=1)
    p.add_argument('--seed', type=int, default=123)
    p.add_argument('--output')
    args = p.parse_args()
    if not (0 <= args.drop_rate <= 1 and 0 <= args.duplicate_rate <= 1 and args.delay_ms >= 0 and args.jitter_ms >= 0):
        p.error('Invalid network fault parameters')
    scenario = load(args.scenario)
    output = replay(scenario) if args.mode == 'oracle' else asyncio.run(live(scenario, args))
    out = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).write_text(out + '\n')
        print(f'Wrote {args.output}')
    else:
        if args.mode == 'oracle':
            brief = {k: v for k, v in output.items() if k not in ('trace', 'final')}
            print(json.dumps(brief, indent=2))
        else:
            print(out)
    if args.mode == 'live' and (output['errors'] or output['final_comparison']['status'] == 'fail'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
