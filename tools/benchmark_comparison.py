#!/usr/bin/env python3
"""Automated comparison benchmark between Baseline (Full Snapshot) and Optimized (Delta Snapshot)."""
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from aiohttp import ClientSession, WSMsgType

ROOM_SIZE = 4
DURATION = 8
PLAYERS = 8

async def run_bot(session: ClientSession, url: str, index: int, end: float, use_delta: bool) -> dict:
    rng = random.Random(2026 + index)
    room = f'bench-{index // ROOM_SIZE:02d}'
    received_bytes = 0
    snapshot_count = 0
    delta_count = 0
    message_sizes = []
    probes = []
    async with session.ws_connect(url, heartbeat=20, timeout=15) as socket:
        join_payload = {'type': 'join', 'name': f'bot-{index}', 'room': room}
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
    print("      TAG, YOU'RE LAGGED! — PERFORMANCE COMPARISON BENCHMARK      ")
    print("=================================================================")
    print(f"Parameters: {PLAYERS} players, duration: {DURATION}s, room size: {ROOM_SIZE}\n")

    # 1. Run Baseline
    print("[1/2] Starting Baseline Server (Full Snapshots) on port 8001...")
    p1 = start_server(baseline_dir, 8001, py_exe)
    try:
        base_res = await benchmark_run(8001, use_delta=False, duration=DURATION, players=PLAYERS)
        print("      Baseline run completed.")
    finally:
        p1.terminate()
        p1.wait()

    time.sleep(1.0)

    # 2. Run Optimized
    print("[2/2] Starting Optimized Server (Delta Snapshots) on port 8002...")
    p2 = start_server(optimized_dir, 8002, py_exe)
    try:
        opt_res = await benchmark_run(8002, use_delta=True, duration=DURATION, players=PLAYERS)
        print("      Optimized run completed.")
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
    print(f"| Median Message Size (Bytes) | {base_res['p50_msg_size_bytes']:>15.1f} | {opt_res['p50_msg_size_bytes']:>17.1f} | -{round(base_res['p50_msg_size_bytes'] - opt_res['p50_msg_size_bytes'], 1):>18.1f} B |")
    print(f"| Latency RTT p50             | {base_res['rtt_p50_ms']:>13.2f} ms | {opt_res['rtt_p50_ms']:>15.2f} ms | {round(opt_res['rtt_p50_ms'] - base_res['rtt_p50_ms'], 2):>17.2f} ms |")
    print(f"| Latency RTT p95             | {base_res['rtt_p95_ms']:>13.2f} ms | {opt_res['rtt_p95_ms']:>15.2f} ms | {round(opt_res['rtt_p95_ms'] - base_res['rtt_p95_ms'], 2):>17.2f} ms |")
    print("===================================================================\n")

    report_path = Path(optimized_dir) / 'docs' / 'BENCHMARK_RESULTS.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({'baseline': base_res, 'optimized': opt_res, 'savings_percent': reduction_pct}, f, indent=2)
    print(f"Detailed JSON results written to: {report_path}")

if __name__ == '__main__':
    asyncio.run(main())
