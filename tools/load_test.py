#!/usr/bin/env python3
"""Load-test utility supporting both Baseline and Optimized (Delta + Session) protocols.

STUDENT-EDITABLE: Measures latency, bandwidth, and stability under synthetic load.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid

from aiohttp import ClientSession, WSMsgType


async def bot(session: ClientSession, url: str, index: int, end: float, room_size: int, use_delta: bool) -> dict:
    rng = random.Random(1000 + index)
    room = f'load-{index // room_size:03d}'
    token = f'tok_load_{index:04d}_{uuid.uuid4().hex[:8]}'
    received_bytes = 0
    snapshot_count = 0
    delta_count = 0
    probes = []
    
    async with session.ws_connect(url, heartbeat=20, timeout=15) as socket:
        join_msg = {
            'type': 'join',
            'name': f'bot-{index}',
            'room': room,
            'token': token,
            'delta': use_delta
        }
        await socket.send_json(join_msg)
        welcome = await socket.receive_json(timeout=10)
        if welcome.get('type') != 'welcome':
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
                await socket.send_json({
                    'type': 'input',
                    'seq': seq,
                    'dx': dx,
                    'dy': dy,
                    'cloak': seq % 37 == 0
                })
            if now - last_ping >= 1.0:
                last_ping = now
                await socket.send_json({'type': 'ping', 'nonce': time.monotonic_ns()})
            
            try:
                msg = await socket.receive(timeout=0.02)
            except asyncio.TimeoutError:
                continue
                
            if msg.type == WSMsgType.TEXT:
                received_bytes += len(msg.data.encode('utf-8'))
                data = json.loads(msg.data)
                mtype = data.get('type')
                if mtype == 'snapshot':
                    snapshot_count += 1
                elif mtype == 'delta':
                    delta_count += 1
                elif mtype == 'pong':
                    probes.append((time.monotonic_ns() - data['nonce']) / 1e6)
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                raise RuntimeError('Socket closed unexpectedly')
                
    return {
        'snapshots': snapshot_count,
        'deltas': delta_count,
        'bytes_received': received_bytes,
        'rtts': probes
    }


async def run(args):
    url = args.url
    if url.startswith('http://'):
        url = 'ws://' + url[7:].rstrip('/') + '/ws'
    elif url.startswith('https://'):
        url = 'wss://' + url[8:].rstrip('/') + '/ws'
        
    async with ClientSession() as session:
        end = time.monotonic() + args.duration
        tasks = [
            bot(session, url, index, end, args.room_size, args.delta)
            for index in range(args.players)
        ]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        passed = [x for x in outcomes if isinstance(x, dict)]
        failures = [str(x) for x in outcomes if isinstance(x, BaseException)]
        rtts = [r for result in passed for r in result['rtts']]
        ordered = sorted(rtts)
        
        result_payload = {
            'target_players': args.players,
            'completed_players': len(passed),
            'failed_players': len(failures),
            'duration_s': args.duration,
            'protocol_mode': 'delta' if args.delta else 'baseline_full',
            'snapshots_received': sum(r['snapshots'] for r in passed),
            'deltas_received': sum(r['deltas'] for r in passed),
            'received_app_bytes': sum(r['bytes_received'] for r in passed),
            'ping_rtt_p50_ms': round(statistics.median(rtts), 2) if rtts else None,
            'ping_rtt_p95_ms': round(ordered[min(len(ordered)-1, int(len(ordered)*0.95))], 2) if rtts else None,
            'failure_examples': failures[:5],
        }
        print(json.dumps(result_payload, indent=2))
        if failures:
            raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Load-test utility for Tag game')
    parser.add_argument('--url', default='ws://127.0.0.1:8000/ws')
    parser.add_argument('--players', type=int, default=10)
    parser.add_argument('--room-size', type=int, default=4)
    parser.add_argument('--duration', type=int, default=10)
    parser.add_argument('--delta', action='store_true', help='Request delta snapshots (v2)')
    args = parser.parse_args()
    asyncio.run(run(args))
