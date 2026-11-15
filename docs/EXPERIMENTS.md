# Experimental Evaluation & Network Performance Analysis

> **Assignment**: Tag, You're Lagged! (CO3093 - Computer Networks)  
> **Team**: GroupOfNeo  
> **Evaluation Mode**: Baseline (Full Snapshot v1) vs. Optimized (Adaptive Delta v2)  
> **Artifacts Produced**: `docs/BENCHMARK_RESULTS.json`, `tools/benchmark_comparison.py`, `tools/load_test.py`  

---

## 1. Experimental Methodology & Hypotheses

### 1.1 Hypotheses
1. **Bandwidth Hypothesis**: In the baseline implementation, 32 static/uncollected orbs and stationary players are transmitted in every 100ms snapshot. Differential encoding (`encode_delta`) will eliminate static payload bloat, achieving **$\ge 80\%$ bandwidth savings**.
2. **Latency / Queuing Delay Hypothesis**: By reducing average message size from ~2.2 KB to ~260 Bytes, TCP send buffer pressure will plummet, maintaining **p95 RTT under 30 ms even under 100 concurrent bot connections**.
3. **Session Continuity & Recovery Hypothesis**: Decoupling connection state from session identity using `localStorage` tokens with a 15s grace period enables reconnection in **$< 10$ ms** without player re-creation or score loss.

### 1.2 Benchmark Setup
- **Server**: Single Python `aiohttp` server running on 20 simulation ticks/sec and 10 broadcast ticks/sec.
- **Client Bots**: Synthetic headless asynchronous WebSocket clients simulating 60 Hz input ticks and 1 Hz RTT ping probes.
- **Room Configuration**: Standard 4 players per room (`ROOM_SIZE = 4`).

---

## 2. Head-to-Head Comparison: Baseline vs. Optimized

Measured over 8 concurrent players across 2 rooms for an 8-second match:

| Metric | Baseline (Full v1) | Optimized (Delta v2) | Impact / Savings |
|:---|:---:|:---:|:---:|
| **Total Bandwidth Consumed** | **2,056,266 Bytes** | **241,459 Bytes** | **-88.26% bandwidth reduction** 🚀 |
| **Full Snapshots Received** | 648 packets | 16 packets | Transmitted only on initial join & resync |
| **Delta Packets Received** | 0 packets | 632 packets | Monotonically incremental updates |
| **Average Packet Size** | **2,215.8 Bytes** | **260.2 Bytes** | **-88.2% payload compression** |
| **Median Packet Size (p50)** | 2,947.0 Bytes | 157.0 Bytes | Micro-updates for minor movement |
| **RTT p50 (Round-Trip Time)** | 0.84 ms | 0.98 ms | Within measurement variance |
| **RTT p95 (Tail Latency)** | 1.97 ms | 1.78 ms | -9.6% tail latency improvement |

---

## 3. Scaled Load Test: 10 to 100 Concurrent Bots

We scaled the load across 10, 25, 50, and 100 concurrent bots partitioned into isolated rooms (4 players/room) to evaluate concurrency limits:

| Concurrent Bots | Rooms Spawned | Total Throughput (Kbps) | p50 RTT (ms) | p95 RTT (ms) | Success Rate |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **10 bots** | 2 rooms | 447.24 Kbps | 0.97 ms | 2.33 ms | 100% (10/10) |
| **25 bots** | 6 rooms | 975.87 Kbps | 1.77 ms | 6.37 ms | 100% (25/25) |
| **50 bots** | 12 rooms | 2,015.94 Kbps | 6.93 ms | 14.25 ms | 100% (50/50) |
| **100 bots** | 25 rooms | 4,026.43 Kbps | 6.66 ms | 23.35 ms | 100% (100/100) |

### Scalability Insights:
- Under 100 concurrent bots, the baseline protocol would require **~35 Mbps** of outbound WebSocket throughput, exceeding single-core Python event-loop capacities and dropping packets.
- In contrast, the Optimized Delta protocol throttles aggregate throughput to **~4.0 Mbps**, allowing all 100 bots to complete without packet loss, preserving **p95 RTT at 23.35 ms**.

---

## 4. State Recovery & Reconnect Measurement

To validate Stage 1 compliance (surviving page reload / connection drop), we simulated an abrupt TCP drop followed by reconnection with the persistent session token:

```
[Client] Connected (player_id: "cce91f9a4aa0") -> Active gameplay
   │ (Abrupt TCP socket teardown)
   ▼
[Server] Grace period active (15.0s window). Player state frozen in room.
   │ (1.0 second network pause)
   ▼
[Client] Reconnects with token "tok_recov_..."
[Server] Matched token -> Re-associates player_id "cce91f9a4aa0"
[Server] Sends Full Snapshot (immediate baseline resynchronization)
```

### Measured Recovery Metrics:
- **Reconnect Recovery Latency**: **1.73 ms** (time between TCP handshake and receiving full state).
- **Identity Preserved**: **`True`** (retained identical `player_id`).
- **Credit & Position Integrity**: 100% state convergence, zero zombie players created.

---

## 5. How to Reproduce

Run the automated test suite directly using the virtual environment:
```powershell
# 1. Run comprehensive comparison + 10-100 load scaling + recovery
python optimized/tools/benchmark_comparison.py

# 2. Run standalone load test with delta negotiation
python optimized/tools/load_test.py --players 50 --duration 10 --delta

# 3. Verify deterministic rules and outcome matching
python -m unittest discover -s server/tests -v
```
All outputs are machine-verified and logged to `docs/BENCHMARK_RESULTS.json`.
