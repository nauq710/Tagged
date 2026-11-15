#!/usr/bin/env python3
"""Automated comprehensive benchmark suite:
1. Baseline (Full Snapshot) vs. Optimized (Delta Snapshot) head-to-head comparison
2. Scaled load testing: 10, 25, 50, 100 concurrent bots across rooms
3. State recovery / reconnect measurement (measuring convergence time and session continuity)
"""
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from aiohttp import ClientSession, WSMsgType

ROOM_SIZE = 4
DURATION = 8
PLAYERS = 8

async def run_bot(session: ClientSession, url: str, index: int, end: float, use_delta: bool) -> dict:
    rng = random.Random(2026 + index)
    room = f'bench-{index // ROOM_SIZE:02d}'
    token = f'tok_bot_{index}_{uuid.uuid4().hex[:6]}'
    received_bytes = 0
    snapshot_count = 0
    delta_count = 0
    message_sizes = []
    probes = []
    async with session.ws_connect(url, heartbeat=20, timeout=15) as socket:
        join_payload = {'type': 'join', 'name': f'bot-{index}', 'room': room, 'token': token}
        if use_delta:
            join_payload['delta'] = True
        await socket.send_json(join_payload)
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
                if seq % 10 == 1:
                    dx, dy = rng.choice([-1, 0, 1]), rng.choice([-1, 0, 1])
                await socket.send_json({'type': 'input', 'seq': seq, 'dx': dx, 'dy': dy, 'cloak': seq % 30 == 0})
            if now - last_ping >= 1.0:
                last_ping = now
                await socket.send_json({'type': 'ping', 'nonce': time.monotonic_ns()})
            try:
                msg = await socket.receive(timeout=0.02)
            except asyncio.TimeoutError:
                continue
            if msg.type == WSMsgType.TEXT:
                byte_len = len(msg.data.encode('utf-8'))
                received_bytes += byte_len
                message_sizes.append(byte_len)
                data = json.loads(msg.data)
                mtype = data.get('type')
                if mtype == 'snapshot':
                    snapshot_count += 1
                elif mtype == 'delta':
                    delta_count += 1
                elif mtype == 'pong':
                    probes.append((time.monotonic_ns() - data['nonce']) / 1e6)
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
    return {
        'total_bytes': received_bytes,
        'snapshot_count': snapshot_count,
        'delta_count': delta_count,
        'message_sizes': message_sizes,
        'rtts': probes
    }

async def benchmark_run(port: int, use_delta: bool, duration: int, players: int) -> dict:
    url = f'ws://127.0.0.1:{port}/ws'
    async with ClientSession() as session:
        end = time.monotonic() + duration
        tasks = [run_bot(session, url, i, end, use_delta) for i in range(players)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid = [r for r in results if isinstance(r, dict)]
        total_bytes = sum(r['total_bytes'] for r in valid)
        total_snapshots = sum(r['snapshot_count'] for r in valid)
        total_deltas = sum(r['delta_count'] for r in valid)
        all_sizes = [s for r in valid for s in r['message_sizes']]
        all_rtts = sorted([p for r in valid for p in r['rtts']])
        return {
            'clients_succeeded': len(valid),
            'total_bytes': total_bytes,
            'total_snapshots': total_snapshots,
            'total_deltas': total_deltas,
            'avg_msg_size_bytes': round(statistics.mean(all_sizes), 1) if all_sizes else 0,
            'p50_msg_size_bytes': statistics.median(all_sizes) if all_sizes else 0,
            'rtt_p50_ms': round(statistics.median(all_rtts), 2) if all_rtts else 0,
            'rtt_p95_ms': round(all_rtts[int(0.95 * len(all_rtts))], 2) if all_rtts else 0,
        }

async def benchmark_recovery(port: int) -> dict:
    """Measure reconnect recovery latency and state convergence with session token."""
    url = f'ws://127.0.0.1:{port}/ws'
    token = f'tok_recov_{uuid.uuid4().hex[:8]}'
    room = 'recovery-test'
    
    # 1. Initial connect
    async with ClientSession() as session:
        t0 = time.monotonic()
        async with session.ws_connect(url) as ws1:
            await ws1.send_json({'type': 'join', 'name': 'RecovBot', 'room': room, 'token': token, 'delta': True})
            w1 = await ws1.receive_json(timeout=5)
            s1 = await ws1.receive_json(timeout=5)
            assigned_id = w1['id']
            # Send movement
            await ws1.send_json({'type': 'input', 'seq': 1, 'dx': 1, 'dy': 0, 'cloak': False})
            await asyncio.sleep(0.5)
            # Abrupt disconnect
        
        disc_time = time.monotonic()
        # Simulated disconnect gap of 1.0 second
        await asyncio.sleep(1.0)
        
        # 2. Reconnect with same token
        reconnect_start = time.monotonic()
        async with session.ws_connect(url) as ws2:
            await ws2.send_json({'type': 'join', 'name': 'RecovBot', 'room': room, 'token': token, 'delta': True})
            w2 = await ws2.receive_json(timeout=5)
            s2 = await ws2.receive_json(timeout=5)
            reconnect_end = time.monotonic()
            
            reconnected_id = w2['id']
            is_same_identity = (assigned_id == reconnected_id)
            recovery_latency_ms = round((reconnect_end - reconnect_start) * 1000, 2)
            
            return {
                'reconnect_recovery_latency_ms': recovery_latency_ms,
                'identity_preserved': is_same_identity,
                'initial_player_id': assigned_id,
                'reconnected_player_id': reconnected_id,
                'state_received_type': s2.get('type')
            }

def start_server(code_dir: str, port: int, py_exe: str):
    env = os.environ.copy()
    env['PORT'] = str(port)
    env['HOST'] = '127.0.0.1'
    env['PYTHONPATH'] = f"{code_dir};{code_dir}/server"
    cmd = [py_exe, "-m", "app.main"]
    proc = subprocess.Popen(cmd, cwd=os.path.join(code_dir, 'server'), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    return proc

async def main():
    root = Path(__file__).resolve().parents[2]
    baseline_dir = str(root / 'baseline')
    optimized_dir = str(root / 'optimized')
    py_exe = str(root / '.venv' / 'Scripts' / 'python.exe')

    print("=================================================================")
    print("      TAG, YOU'RE LAGGED! — COMPREHENSIVE NETWORK BENCHMARK      ")
    print("=================================================================\n")

    # 1. Baseline Run
    print("[1/4] Running Baseline Server (Full Snapshots, 8 bots)...")
    p1 = start_server(baseline_dir, 8001, py_exe)
    try:
        base_res = await benchmark_run(8001, use_delta=False, duration=DURATION, players=PLAYERS)
        print("      Baseline completed.")
    finally:
        p1.terminate()
        p1.wait()

    time.sleep(1.0)

    # 2. Optimized Run
    print("[2/4] Running Optimized Server (Delta Snapshots, 8 bots)...")
    p2 = start_server(optimized_dir, 8002, py_exe)
    try:
        opt_res = await benchmark_run(8002, use_delta=True, duration=DURATION, players=PLAYERS)
        print("      Optimized completed.")
        
        # 3. Scaling Benchmark on Optimized (10 -> 100 bots)
        print("[3/4] Running Scaled Load Benchmarks on Optimized (10, 25, 50, 100 bots)...")
        scaling_results = {}
        for count in [10, 25, 50, 100]:
            print(f"      -> Testing {count} bots across {max(1, count // ROOM_SIZE)} rooms...")
            scale_res = await benchmark_run(8002, use_delta=True, duration=5, players=count)
            scaling_results[f"{count}_bots"] = {
                'active_bots': scale_res['clients_succeeded'],
                'throughput_kbps': round((scale_res['total_bytes'] * 8) / (5 * 1024), 2),
                'rtt_p50_ms': scale_res['rtt_p50_ms'],
                'rtt_p95_ms': scale_res['rtt_p95_ms'],
                'avg_msg_size_bytes': scale_res['avg_msg_size_bytes']
            }
            print(f"         p50 RTT: {scale_res['rtt_p50_ms']} ms | p95 RTT: {scale_res['rtt_p95_ms']} ms | Throughput: {scaling_results[f'{count}_bots']['throughput_kbps']} Kbps")
            await asyncio.sleep(0.5)

        # 4. State Recovery Benchmark
        print("[4/4] Measuring Disconnect / Reconnect Recovery Latency...")
        recovery_res = await benchmark_recovery(8002)
        print(f"      Recovery Latency: {recovery_res['reconnect_recovery_latency_ms']} ms (Identity Preserved: {recovery_res['identity_preserved']})")

    finally:
        p2.terminate()
        p2.wait()

    # Calculate savings
    b_bytes = base_res['total_bytes']
    o_bytes = opt_res['total_bytes']
    reduction_pct = round(((b_bytes - o_bytes) / b_bytes) * 100, 2) if b_bytes else 0

    print("\n========================= RESULTS SUMMARY =========================")
    print(f"| Metric                      | Baseline (Full) | Optimized (Delta) | Difference / Savings |")
    print(f"|-----------------------------|-----------------|-------------------|----------------------|")
    print(f"| Total Data Transferred      | {b_bytes:>12,d} B | {o_bytes:>15,d} B | {reduction_pct:>18.2f}% |")
    print(f"| Full Snapshots Received     | {base_res['total_snapshots']:>15d} | {opt_res['total_snapshots']:>17d} | {opt_res['total_snapshots'] - base_res['total_snapshots']:>20d} |")
    print(f"| Delta Snapshots Received    | {base_res['total_deltas']:>15d} | {opt_res['total_deltas']:>17d} | +{opt_res['total_deltas']:>19d} |")
    print(f"| Avg Message Size (Bytes)    | {base_res['avg_msg_size_bytes']:>15.1f} | {opt_res['avg_msg_size_bytes']:>17.1f} | -{round(base_res['avg_msg_size_bytes'] - opt_res['avg_msg_size_bytes'], 1):>18.1f} B |")
    print(f"| Latency RTT p50             | {base_res['rtt_p50_ms']:>13.2f} ms | {opt_res['rtt_p50_ms']:>15.2f} ms | {round(opt_res['rtt_p50_ms'] - base_res['rtt_p50_ms'], 2):>17.2f} ms |")
    print(f"| Latency RTT p95             | {base_res['rtt_p95_ms']:>13.2f} ms | {opt_res['rtt_p95_ms']:>15.2f} ms | {round(opt_res['rtt_p95_ms'] - base_res['rtt_p95_ms'], 2):>17.2f} ms |")
    print("===================================================================\n")

    final_report = {
        'comparison': {
            'baseline': base_res,
            'optimized': opt_res,
            'bandwidth_reduction_percent': reduction_pct
        },
        'scaling_load_test': scaling_results,
        'state_recovery_benchmark': recovery_res
    }

    report_path = Path(optimized_dir) / 'docs' / 'BENCHMARK_RESULTS.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, indent=2)
    print(f"Comprehensive JSON results written to: {report_path}")

if __name__ == '__main__':
    asyncio.run(main())
