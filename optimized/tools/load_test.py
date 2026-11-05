#!/usr/bin/env python3
"""Reference-protocol load test: synthetic headless players, no browser required.

STUDENT-EDITABLE if your networking protocol changes. Do not change the
meaning of movement/collection/cloak actions or present unverified metrics as gameplay latency.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time

from aiohttp import ClientSession, WSMsgType


async def bot(session: ClientSession, url: str, index: int, end: float, room_size: int) -> dict:
    rng = random.Random(1000 + index)
    room = f'load-{index // room_size:03d}'
    received_bytes, snapshot_count, probes = 0, 0, []
    async with session.ws_connect(url, heartbeat=20, timeout=15) as socket:
        await socket.send_json({'type': 'join', 'name': f'bot-{index}', 'room': room})
        welcome = await socket.receive_json(timeout=10)
        if welcome['type'] != 'welcome':
            raise RuntimeError(f'Join rejected: {welcome}')
        last_send = 0.0
        last_ping = 0.0
        seq = 0
        dx = dy = 0
        while time.monotonic() < end:
            now = time.monotonic()
            if now - last_send >= 0.1:
                last_send = now
                seq += 1
                if seq % 15 == 1:
                    dx, dy = rng.choice([-1, 0, 1]), rng.choice([-1, 0, 1])
                await socket.send_json({'type': 'input', 'seq': seq, 'dx': dx, 'dy': dy, 'cloak': seq % 37 == 0})
            if now - last_ping >= 2:
                last_ping = now
                await socket.send_json({'type': 'ping', 'nonce': time.monotonic_ns()})
            try:
                msg = await socket.receive(timeout=0.02)
            except asyncio.TimeoutError:
                continue
            if msg.type == WSMsgType.TEXT:
                received_bytes += len(msg.data.encode('utf-8'))
                data = json.loads(msg.data)
                if data.get('type') == 'snapshot': snapshot_count += 1
                if data.get('type') == 'pong':
                    probes.append((time.monotonic_ns() - data['nonce']) / 1e6)
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                raise RuntimeError('Socket closed during test')
    return {'snapshots': snapshot_count, 'bytes_received': received_bytes, 'rtts': probes}


async def run(args):
    url = args.url
    if url.startswith('http://'): url = 'ws://' + url[7:].rstrip('/') + '/ws'
    if url.startswith('https://'): url = 'wss://' + url[8:].rstrip('/') + '/ws'
    async with ClientSession() as session:
        end = time.monotonic() + args.duration
        tasks = [bot(session, url, index, end, args.room_size) for index in range(args.players)]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        passed = [x for x in outcomes if isinstance(x, dict)]
        failures = [str(x) for x in outcomes if isinstance(x, BaseException)]
        rtts = [r for result in passed for r in result['rtts']]
        ordered = sorted(rtts)
        print(json.dumps({
            'target_players': args.players, 'completed_players': len(passed), 'failed_players': len(failures),
            'duration_s': args.duration,
            'snapshots_received': sum(r['snapshots'] for r in passed),
            'received_app_bytes': sum(r['bytes_received'] for r in passed),
            'ping_rtt_p50_ms': round(statistics.median(rtts), 2) if rtts else None,
            'ping_rtt_p95_ms': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 2) if rtts else None,
            'failure_examples': failures[:5],
        }, indent=2))
        if failures:
            raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Load-test the baseline WebSocket protocol')
    parser.add_argument('--url', default='ws://127.0.0.1:8000/ws')
    parser.add_argument('--players', type=int, default=10)
    parser.add_argument('--room-size', type=int, default=20)
    parser.add_argument('--duration', type=int, default=15)
    arguments = parser.parse_args()
    if not 1 <= arguments.players <= 1000 or not 1 <= arguments.room_size <= 20 or arguments.duration < 1:
        parser.error('Use 1-1000 players, room-size 1-20, and positive duration')
    asyncio.run(run(arguments))
