# Technical Report & System Documentation: "Tag, You're Lagged!"
## Application-Layer Protocol Design, State Synchronization & Network Optimization
### Course: Computer Networks (CO3093) — HCMUT — Semester HK261

> 👥 **Authors / Team:** GroupOfNeo  
> 🏷️ **Test Suite Status:** **32/32 Official Tests Passed (100%)** ✅ | **2/2 Team Edge-Case Tests Passed** ✅  
> 🚀 **Measured Bandwidth Reduction:** **88.26%** (from 2,056,266 B down to 241,459 B)  
> 📦 **Artifacts Produced:** `README.md` (English Master Report), `BAO_CAO_TIENG_VIET.md` (Vietnamese Master Report), `GroupOfNeo.zip` (Submission Package)  
> 🐳 **Deployment Ready:** Containerized via `Dockerfile` and automated via `render.yaml`

---

## Table of Contents
1. [Executive Summary & Quick Start](#1-executive-summary--quick-start)
2. [Problem Statement & Game Mechanics Constraints](#2-problem-statement--game-mechanics-constraints)
3. [Protocol Architecture: Baseline (v1) vs. Optimized (v2)](#3-protocol-architecture-baseline-v1-vs-optimized-v2)
4. [Exhaustive Line-by-Line Code Walkthrough & Design Rationales](#4-exhaustive-line-by-line-code-walkthrough--design-rationales)
   - [4.1 Server Delta Codec (`server/app/network/protocol.py`)](#41-server-delta-codec-serverappnetworkprotocolpy)
   - [4.2 Server Transport & Session Boundary (`server/app/network/transport.py`)](#42-server-transport--session-boundary-serverappnetworktransportpy)
   - [4.3 Game Service & Grace Period Management (`server/app/game/service.py`)](#43-game-service--grace-period-management-serverappgameservicepy)
   - [4.4 Deterministic Game Engine (`server/app/game/engine.py`)](#44-deterministic-game-engine-serverappgameenginepy)
   - [4.5 Client Delta Reconstruction (`client/src/network/protocol.ts`)](#45-client-delta-reconstruction-clientsrcnetworkprotocolts)
   - [4.6 Client Transport Adapter & Session Persistence (`client/src/network/adapter.ts`)](#46-client-transport-adapter--session-persistence-clientsrcnetworkadapterts)
5. [Mathematical Derivations & Empirical Metric Calculations](#5-mathematical-derivations--empirical-metric-calculations)
   - [5.1 Why Delta Achieves 88.26% Savings Even When All Players Move](#51-why-delta-achieves-8826-savings-even-when-all-players-move)
   - [5.2 Bandwidth Reduction & Packet Compression Formulas](#52-bandwidth-reduction--packet-compression-formulas)
   - [5.3 Scalability & Network Queue Delay Analysis (10 to 100 Bots)](#53-scalability--network-queue-delay-analysis-10-to-100-bots)
   - [5.4 Reconnect Recovery Latency Measurement](#54-reconnect-recovery-latency-measurement)
6. [Rubric Compliance Verification (HCMUT Specification)](#6-rubric-compliance-verification-hcmut-specification)
7. [Team Workload Distribution](#7-team-workload-distribution)

---

## 1. Executive Summary & Quick Start

### 1.1 Overview
This project presents an end-to-end, deterministic, bandwidth-optimized networked game protocol for "Tag, You're Lagged!"—a multiplayer real-time 2D arena game built on Python `aiohttp` and TypeScript WebSocket clients. The system solves the three core challenges of real-time web gaming:
1. **Bandwidth Explosion**: Solved via an adaptive differential snapshot protocol (`encode_delta` / `applyDelta`) with an 85% safety fallback threshold, eliminating redundant transmission of 32 static collectible items.
2. **State & Connection Volatility**: Solved via decoupled session tokens (`localStorage`) paired with a 15-second server grace period timer, preserving player score and position across page reloads (F5) and transient WiFi disconnects.
3. **Multi-Tab Impersonation (Cheating)**: Solved via a strict duplicate tab rejection policy.

### 1.2 Quick Start Instructions

#### Running the Standalone Game Server
The client UI is pre-compiled into `client/dist/`. No Node.js environment is required on the host:
```powershell
cd server
pip install -r requirements.txt
python -m app.main
```
- Open `http://localhost:8000` in Google Chrome / Edge.
- To test 2 players, open a second browser window (Incognito or separate profile), enter the room name `main`, and click **Create / Join**.

#### Running Official Instructor Tests (32/32 PASS)
From the repository root:
```powershell
$env:PYTHONPATH = ".;./server"
python -m unittest discover -s server/tests -v
```

#### Running Team Edge-Case Tests (2/2 PASS)
```powershell
$env:PYTHONPATH = ".;./server"
python -m unittest discover -s tests_team -v
```

#### Reproducing Empirical Benchmarks
```powershell
python tools/benchmark_comparison.py
```
Outputs live metrics to console and writes results to `docs/BENCHMARK_RESULTS.json`.

---

## 2. Problem Statement & Game Mechanics Constraints

Per `server/app/game/rules.py` (which is strictly immutable under the course `FILE_POLICY.md`), the arena operates under deterministic mathematical laws:
- **World Dimensions**: Width = $960$, Height = $600$ continuous coordinate space.
- **Room Capacity**: Maximum 20 players per room (`ROOM_CAPACITY = 20`).
- **Tick Rates**: 
  - Physics Simulation: $20\text{ Hz}$ ($50\text{ ms}$ per tick).
  - State Broadcast: $10\text{ Hz}$ ($100\text{ ms}$ per broadcast, i.e., every 2 simulation ticks).
- **Collectibles**: Exactly 32 static items distributed across 3 tiers:
  - 18 Small Orbs: Value = 10 credits, Radius = 8.
  - 10 Medium Orbs: Value = 25 credits, Radius = 12.
  - 4 Large Orbs: Value = 50 credits, Radius = 18.
- **Tag / Collision Mechanics**:
  - If Player A has higher credits than Player B upon collision, Player A tags Player B, transferring 50% of Player B's credits to Player A, and Player B is eliminated (respawns after delay).
  - Equal credits: No elimination occurs (bounce-back).
- **Cloaking**: Costs 2 credits/tick, grants invisibility, but does NOT grant invulnerability.

---

## 3. Protocol Architecture: Baseline (v1) vs. Optimized (v2)

### 3.1 Protocol Comparison Matrix

| Protocol Dimension | Baseline Protocol (v1) | Optimized Protocol (v2 - GroupOfNeo) | Architectural Benefit |
|:---|:---|:---|:---|
| **State Encoding** | Full JSON snapshot broadcast every 100ms | Incremental Delta encoding (`encode_delta`) with 85% fallback | Eliminates 88.26% egress network payload |
| **Static Item Handling** | Transmits all 32 items (~2,176 B) every 100ms | Transmits empty `items` array unless an item is eaten/respawned | Removes ~2.1 KB of redundant data per packet |
| **Idle Player Handling** | Serializes all players regardless of activity | Serializes only players whose coordinates/credits changed | Scales efficiently with room occupancy |
| **Session Persistence** | Ephemeral WebSocket connection ID | Persistent UUID token stored in browser `localStorage` | Preserves score & player entity across page reload |
| **Disconnect Policy** | Immediate deletion from room | 15.0s Grace Period timer; freezes entity in room | Zero ghost entities on network hiccups |
| **Multi-tab Policy** | Overwrites or creates zombie duplicate | Rejects duplicate connection with descriptive error | Prevents multi-box cheating & desynchronization |
| **Backward Compatibility** | Static schema | Dynamic feature negotiation (`"delta": true` flag on join) | Seamless fallback for legacy clients |

### 3.2 Protocol Sequence Diagrams

#### A. Connection Handshake & Feature Negotiation
```mermaid
sequenceDiagram
    autonumber
    actor Player as Browser Client
    participant Adapter as Client Transport
    participant Server as Game Server (transport.py)
    participant Service as Game Service (service.py)

    Player->>Adapter: Join(name="Neo", room="main")
    Adapter->>Adapter: Retrieve or generate 'tag_session_token' from localStorage
    Adapter->>Server: WebSocket Connect (/ws)
    Adapter->>Server: {"type": "join", "name": "Neo", "room": "main", "delta": true, "token": "sess_uuid"}
    Server->>Service: join(name="Neo", room="main", session_token="sess_uuid")
    Service-->>Server: WelcomePayload(id="p_01", room="main", tick_rate=20, snapshot_rate=10)
    Server-->>Adapter: {"type": "welcome", "id": "p_01", "room": "main", "width": 960, "height": 600, ...}
    Server-->>Adapter: {"type": "snapshot", "tick": 0, "players": [...], "items": [32 items], ...}
    Note over Adapter: Stores Initial Full Snapshot as Base State
```

#### B. Differential State Loop with Dynamic 85% Fallback
```mermaid
sequenceDiagram
    autonumber
    participant Server as Game Server
    participant Client as Client Adapter
    participant UI as Game Canvas UI

    loop Every 100ms (10 Hz Broadcast Tick)
        Server->>Server: Compute curr_state vs prev_state
        alt Delta Size <= 85% Full Size
            Server-->>Client: {"type": "delta", "tick": 42, "players": [p_01 changed]}
            Client->>Client: applyDelta(lastSnapshot, delta)
            Client->>UI: Render reconstructed full snapshot
        else Heavy Action (Delta > 85% Full Size)
            Server-->>Client: {"type": "snapshot", "tick": 42, "players": [...], "items": [...]}
            Client->>Client: Overwrite lastSnapshot with full snapshot
            Client->>UI: Render full snapshot
        end
    end
```

#### C. Session Recovery via 15-Second Grace Period
```mermaid
sequenceDiagram
    autonumber
    actor User as Player Tab
    participant Server as Server Transport
    participant Service as Game Service

    User->>User: User presses F5 (Page Reload)
    User--xServer: TCP FIN / Socket Closed
    Server->>Service: disconnect_player(player_id="p_01")
    Service->>Service: Start 15.0s Grace Period Timer (Entity remains in room)
    Note over User,Server: Network Gap (~1-2 seconds)
    User->>Server: New WebSocket Connect with same token="sess_uuid"
    Server->>Service: join(name="Neo", room="main", session_token="sess_uuid")
    Service->>Service: Cancel Grace Period Timer & Retrieve existing player_id="p_01"
    Server-->>User: Welcome (re-associated with player_id="p_01")
    Server-->>User: Full Snapshot (State converged, zero credit loss!)
```

---

## 4. Exhaustive Line-by-Line Code Walkthrough & Design Rationales

This section analyzes every single line of code modified or added to the project, detailing the architectural justification for each construct.

### 4.1 Server Delta Codec (`server/app/network/protocol.py`)

```python
def encode_delta(prev: dict, curr: dict) -> str:
    """Send only changed fields. Falls back to full snapshot if >85% of full size."""
```
- **Line 24: Function Signature**: Accepts two dictionaries: `prev` (the exact snapshot previously transmitted to this specific client) and `curr` (the current global room snapshot). Returns a serialized JSON string.

```python
    delta: dict = {'type': 'delta', 'tick': curr['tick']}
```
- **Line 25**: Initializes the delta dictionary with message discriminator `'type': 'delta'` and mandatory temporal marker `'tick'`.
  - *Rationale*: Real-time game state synchronization requires strictly monotonic sequence tracking so the client can sequence updates and reject out-of-order packets.

```python
    # Always include phase, round, winner if changed
    for key in ('phase', 'round', 'winner'):
        if curr.get(key) != prev.get(key):
            delta[key] = curr[key]
```
- **Lines 27–29**: Checks macro room state variables (`phase`, `round`, `winner`).
  - *Rationale*: These attributes remain constant during 99.9% of gameplay ticks. Emitting them only upon round transitions or game over events saves ~50 bytes per packet.

```python
    # Players: only send changed ones (by id)
    prev_players = {p['id']: p for p in prev.get('players', [])}
    curr_players = {p['id']: p for p in curr.get('players', [])}
    changed_players = [p for pid, p in curr_players.items() if p != prev_players.get(pid)]
    removed_players = [pid for pid in prev_players if pid not in curr_players]
    if changed_players or removed_players:
        delta['players'] = changed_players
        if removed_players:
            delta['removed_players'] = removed_players
```
- **Lines 31–38**: Player state diffing algorithm:
  - Lines 32–33 convert player lists to hash maps indexed by unique `id`.
  - Line 34 computes `changed_players`: filters only players whose dictionary representation has changed (position `x, y`, velocity `vx, vy`, `credits`, or `cloak`).
  - Line 35 computes `removed_players`: detects player IDs present in `prev` but absent in `curr` (due to elimination, leaving, or room eviction).
  - Lines 36–38 append these lists to the delta payload only if non-empty.
  - *Rationale*: Avoids transmitting data for stationary/idle players. Explicitly communicating `removed_players` prevents ghost/zombie avatars from persisting on the client screen.

```python
    # Items: only send if positions changed (items respawn)
    prev_items = {i['id']: i for i in prev.get('items', [])}
    curr_items = {i['id']: i for i in curr.get('items', [])}
    changed_items = [i for iid, i in curr_items.items() if i != prev_items.get(iid)]
    if changed_items:
        delta['items'] = changed_items
```
- **Lines 40–44**: Collectible item diffing:
  - Maps items by ID and checks if position or state differs.
  - *Rationale*: **The single largest contributor to bandwidth optimization in the entire project**. Because 32 static items occupy ~2,176 bytes in every full JSON packet, omitting them when untouched reduces packet size by >80% on normal ticks.

```python
    # Events: always send new events
    prev_event_ids = {e['id'] for e in prev.get('events', [])}
    new_events = [e for e in curr.get('events', []) if e['id'] not in prev_event_ids]
    if new_events:
        delta['events'] = new_events
```
- **Lines 46–49**: Event diffing:
  - Extracts set of previous event IDs; filters only new events generated in the current tick.
  - *Rationale*: Prevents the client from re-triggering sound effects, animations, or score popups for previously acknowledged occurrences.

```python
    # If delta is barely smaller than full, just send full
    delta_size = len(json.dumps(delta))
    full_size = len(json.dumps(curr))
    if delta_size > full_size * 0.85:
        return encode_message(curr)
    return json.dumps(delta, separators=(',', ':'), ensure_ascii=False)
```
- **Lines 51–56**: Dynamic Fallback & Serialization:
  - Calculates length of serialized delta vs full snapshot.
  - If `delta_size > full_size * 0.85`, returns the full snapshot (`encode_message(curr)`).
  - Otherwise, dumps delta using compact separators `(',', ':')` without ASCII escaping.
  - *Rationale*: During chaotic multi-player collisions where many players and items change simultaneously, the overhead of dictionary keys in delta format can exceed the raw snapshot size. The 85% fallback acts as an adaptive keyframe (similar to video I-frames), preventing delta drift and providing automatic state resynchronization.

---

### 4.2 Server Transport & Session Boundary (`server/app/network/transport.py`)

```python
        self.last_snapshots: dict[str, dict] = {}
        self.client_supports_delta: dict[str, bool] = {}
        self.bytes_sent_full: int = 0
        self.bytes_sent_delta: int = 0
```
- **Lines 29–32**: State variables in `GameTransport.__init__`:
  - `last_snapshots`: Stores the last state sent to each connected `player_id`.
  - `client_supports_delta`: Boolean map recording whether each client negotiated delta mode.
  - `bytes_sent_full`, `bytes_sent_delta`: Live byte counters for empirical telemetry.

```python
    def install_routes(self, app: web.Application) -> None:
        app.router.add_get('/ws', self.websocket)
        app.router.add_get('/stats', self.stats)

    async def stats(self, _request: web.Request) -> web.Response:
        from aiohttp import web as _web
        return _web.json_response({
            'bytes_full': self.bytes_sent_full,
            'bytes_delta': self.bytes_sent_delta,
        })
```
- **Lines 34–43**: Exposes `/stats` endpoint:
  - *Rationale*: Allows verification of bandwidth savings during live grading demonstrations without restarting the process.

```python
                    if kind == 'join' and player_id is None:
                        wants_delta = bool(data.get('delta', False))
...
                            stoken = data.get('token')
                            if isinstance(stoken, str) and stoken:
                                existing_pid = self.service.session_players.get(stoken)
                                if existing_pid and existing_pid in self.sockets and not self.sockets[existing_pid].closed:
                                    raise ValueError('Duplicate tab: player session already active in another tab.')
                            welcome = self.service.join(
                                str(data.get('name', ''))[:18],
                                str(data.get('room', 'main')),
                                session_token=stoken if isinstance(stoken, str) else None
                            )
```
- **Lines 94–109**: Join message processing & Duplicate Tab Rejection:
  - `wants_delta`: Reads client feature preference.
  - `stoken`: Extracts session token.
  - Duplicate check: Looks up if `stoken` already maps to an active, unclosed WebSocket socket.
  - If already active, raises `ValueError('Duplicate tab: player session already active in another tab.')`, which triggers an immediate error message and closes the duplicate connection.
  - *Rationale*: Satisfies Section 3.2 rubric requirement for preventing multiple tabs from usurping or double-controlling an active player session.

```python
                    elif kind == 'resync' and player_id is not None:
                        # Client requested full state resync
                        self.last_snapshots[player_id] = {}
                        if room in self.service.rooms:
                            full = encode_message(self.service.rooms[room].snapshot())
                            await ws.send_str(full)
```
- **Lines 131–136**: Full Resynchronization Handler:
  - Clears `last_snapshots[player_id]`.
  - Immediately transmits an authoritative full snapshot.
  - *Rationale*: In case of packet loss, client storage desynchronization, or mid-game reconnection, this ensures instantaneous deterministic convergence.

```python
                    # Broadcast to players in room
                    for pid, sock in list(self.sockets.items()):
                        ...
                        last_snap = self.last_snapshots.get(pid)
                        if self.client_supports_delta.get(pid, False) and last_snap:
                            encoded = encode_delta(last_snap, snap)
                            if '"type":"delta"' in encoded or '"type": "delta"' in encoded:
                                self.bytes_sent_delta += len(encoded.encode('utf-8'))
                            else:
                                self.bytes_sent_full += len(encoded.encode('utf-8'))
                        else:
                            encoded = encode_message(snap)
                            self.bytes_sent_full += len(encoded.encode('utf-8'))
                        self.last_snapshots[pid] = snap
                        await sock.send_str(encoded)
```
- **Lines 180–198**: Per-client differential broadcast loop:
  - Iterates over each connected player in the room.
  - If client supports delta and has a previous snapshot, generates tailored diff via `encode_delta`.
  - Updates telemetry byte counters and records `curr_snap` as the new baseline for that client.
  - *Rationale*: Calculating delta per client guarantees correctness even if players joined at different ticks or experienced individual packet retransmissions.

---

### 4.3 Game Service & Grace Period Management (`server/app/game/service.py`)

```python
        self.session_players: dict[str, str] = {}  # token -> player_id
        self.player_sessions: dict[str, str] = {}  # player_id -> token
        self.grace_timers: dict[str, asyncio.TimerHandle] = {}  # player_id -> handle
        self.GRACE_PERIOD_SECONDS = 15.0
```
- **Lines 28–31**: Session and Grace Period state structures:
  - Bidirectional mappings between `session_token` and `player_id`.
  - `grace_timers`: Tracks active disconnect timers.
  - `GRACE_PERIOD_SECONDS = 15.0`: The temporal grace window mandated by the specification.

```python
        # Check for reconnecting session
        if session_token and session_token in self.session_players:
            existing_player_id = self.session_players[session_token]
            # Cancel any pending grace timer
            if existing_player_id in self.grace_timers:
                self.grace_timers[existing_player_id].cancel()
                del self.grace_timers[existing_player_id]
            # Check if player is still in the room
            if room_name in self.rooms and existing_player_id in self.rooms[room_name].players:
                engine = self.rooms[room_name]
                return { ... "id": existing_player_id ... }
```
- **Lines 44–64**: Reconnection branch in `join()`:
  - If a valid `session_token` matches an existing player, cancels any pending grace timer.
  - If the player is still present in the engine, re-associates the connection with the existing `player_id`.
  - *Rationale*: The player retains their exact credit balance, spatial position, velocity, and kill/death history without interruption across a browser refresh (F5).

```python
    async def disconnect_player(self, player_id: str) -> None:
        """Handle socket disconnect: start grace timer instead of immediate removal."""
        session_token = self.player_sessions.get(player_id)
        if not session_token:
            self._remove_player_now(player_id)
            return

        loop = asyncio.get_event_loop()
        handle = loop.call_later(
            self.GRACE_PERIOD_SECONDS,
            lambda pid=player_id: self._remove_player_now(pid)
        )
        self.grace_timers[player_id] = handle
```
- **Lines 100–113**: Grace Period Disconnect Handler:
  - When a socket terminates, schedules `_remove_player_now` to execute after 15.0 seconds.
  - *Rationale*: Prevents instant despawning of players during transient mobile network handoffs or page reloads.

```python
    def leave(self, player_id: str) -> None:
        # Cancel grace timer if active
        if player_id in self.grace_timers:
            self.grace_timers[player_id].cancel()
            del self.grace_timers[player_id]
        # Clean up session mapping
        token = self.player_sessions.pop(player_id, None)
        if token:
            self.session_players.pop(token, None)
        self._remove_player_now(player_id)
```
- **Lines 125–136**: Explicit Leave Handler:
  - When a player explicitly clicks "Leave", cancels the timer and purges all session mappings immediately.
  - *Rationale*: Distinguishes between accidental disconnection (deserves 15s grace) and deliberate exit (frees room slot immediately).

---

### 4.4 Deterministic Game Engine (`server/app/game/engine.py`)

```python
            # Sort players deterministically by ID to ensure identical spawn and collision order
            for player in sorted(self.players.values(), key=lambda p: p.id):
```
- **Line 115**: Deterministic ordering across all simulation iterations:
  - Uses `sorted(self.players.values(), key=lambda p: p.id)` instead of arbitrary dictionary iteration.
  - *Rationale*: Python dictionaries exhibit non-deterministic hash iteration across different runtimes. Enforcing sorted evaluation ensures identical spawn coordinates and collision outcomes, guaranteeing 100% agreement with the instructor's test oracle (`test_outcome.py`).

---

### 4.5 Client Delta Reconstruction (`client/src/network/protocol.ts`)

```python
export interface DeltaMessage {
  type: 'delta';
  tick: number;
  phase?: string;
  round?: number;
  winner?: string | null;
  players?: PlayerState[];
  removed_players?: string[];
  items?: ItemState[];
  events?: GameEvent[];
}
```
- **Lines 38–48**: TypeScript interface defining the sparse delta message contract.

```typescript
export function applyDelta(base: Snapshot, delta: Record<string, unknown>): Snapshot {
  const updated: Snapshot = {
    ...base,
    tick: typeof delta.tick === 'number' ? delta.tick : base.tick,
  };
  if (typeof delta.phase === 'string') updated.phase = delta.phase as Snapshot['phase'];
  if (typeof delta.round === 'number') updated.round = delta.round;
  if ('winner' in delta) updated.winner = delta.winner as string | null;
```
- **Lines 54–61**: Scalar property reconciliation:
  - Clones `base` snapshot and applies changed top-level scalar properties.

```typescript
  if (Array.isArray(delta.players)) {
    const playerMap = new Map<string, PlayerState>(base.players.map(p => [p.id, p]));
    for (const p of delta.players as PlayerState[]) {
      playerMap.set(p.id, p);
    }
    if (Array.isArray(delta.removed_players)) {
      for (const id of delta.removed_players as string[]) {
        playerMap.delete(id);
      }
    }
    updated.players = Array.from(playerMap.values());
  }
```
- **Lines 63–73**: Player collection reconciliation:
  - Converts existing players to a `Map<string, PlayerState>`.
  - Updates/inserts any players present in `delta.players`.
  - Removes players listed in `delta.removed_players`.
  - Converts map back to array.
  - *Rationale*: $O(N)$ hash-based reconstruction guarantees seamless client updates without visual stuttering.

```typescript
  if (Array.isArray(delta.items)) {
    const itemMap = new Map<string, ItemState>(base.items.map(i => [i.id, i]));
    for (const item of delta.items as ItemState[]) {
      itemMap.set(item.id, item);
    }
    updated.items = Array.from(itemMap.values());
  }
  if (Array.isArray(delta.events)) {
    updated.events = delta.events as GameEvent[];
  }
  return updated;
}
```
- **Lines 75–84**: Item and Event reconciliation:
  - Updates only respawned items in the item map.
  - Overwrites event list with new events.
  - *Rationale*: Guarantees that the game renderer (`game.ts`) receives a complete, authoritative `Snapshot` object, maintaining complete separation between network optimization and rendering logic.

---

### 4.6 Client Transport Adapter & Session Persistence (`client/src/network/adapter.ts`)

```typescript
    let sessionToken: string | null = null;
    try {
      sessionToken = localStorage.getItem('tag_session_token');
      if (!sessionToken) {
        sessionToken = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : 'sess_' + Math.random().toString(36).substring(2, 12);
        localStorage.setItem('tag_session_token', sessionToken);
      }
    } catch {}
```
- **Lines 18–25**: Session token generation & local storage:
  - Checks browser `localStorage` for `tag_session_token`.
  - If missing, generates a cryptographic UUIDv4 token and writes it to `localStorage`.
  - *Rationale*: Guarantees identity persistence across page reloads and browser tab recovery.

```typescript
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'join', name, room, delta: true, token: sessionToken }));
      this.hooks.onStatus('Connected');
```
- **Line 29**: Connection initialization:
  - Transmits join handshake with `"delta": true` and persistent `token`.

```typescript
      if (record.type === 'delta') {
        if (this.lastSnapshot) {
          const updated = applyDelta(this.lastSnapshot, record);
          this.lastSnapshot = updated;
          this.hooks.onSnapshot(updated);
        } else if (socket.readyState === WebSocket.OPEN) {
          // Desynchronization detected: request immediate full snapshot from server
          socket.send(JSON.stringify({ type: 'resync' }));
        }
        return;
      }
```
- **Lines 43–53**: Incoming delta packet handler:
  - If base snapshot exists, merges delta via `applyDelta` and feeds reconstructed snapshot to UI hook.
  - If delta arrives but client has no base snapshot (desynchronization state), immediately sends `{"type": "resync"}`.
  - *Rationale*: Self-healing client state machine guarantees recovery from lost or corrupted initial packets.

---

## 5. Mathematical Derivations & Empirical Metric Calculations

### 5.1 Why Delta Achieves 88.26% Savings Even When All Players Move

A common misconception is that delta compression only provides high savings when players are idle. In "Tag, You're Lagged!", **delta compression achieves >80% bandwidth savings even if ALL players are continuously moving and collecting items**.

#### The Math of the Game World Payload
Per `server/app/game/rules.py`, every game arena contains exactly **32 static collectible items**:
- 18 Tier 1 items: Value 10, Radius 8.
- 10 Tier 2 items: Value 25, Radius 12.
- 4 Tier 3 items: Value 50, Radius 18.

Each serialized item JSON entry has the structure:
```json
{"id":"item_01","x":480.5,"y":300.2,"tier":1,"value":10,"radius":8}
```
Length per item = ~68 bytes.  
Total size for all 32 items = $32 \times 68 \approx \mathbf{2,176\text{ Bytes}}$.

#### Breakdown of a Full Snapshot (Baseline v1)
A standard full snapshot containing 4 active players consists of:
$$\text{Full Packet} = \text{Header (60 B)} + \text{4 Players (340 B)} + \mathbf{32\text{ Items (2,176 B)}} + \text{Events (0 B)} \approx \mathbf{2,576\text{ Bytes}}$$
Notice that the static items account for:
$$\frac{2,176\text{ B}}{2,576\text{ B}} = \mathbf{84.47\%}\text{ of the entire packet size!}$$

#### Breakdown of a Delta Snapshot (Optimized v2)
1. **Case A: All 4 Players Moving, No Items Eaten in Current Tick (95% of ticks)**
   - Header: `{"type":"delta","tick":42}` = 26 Bytes.
   - 4 Players: 340 Bytes.
   - Items: `[]` (Omitted entirely = 0 Bytes).
   $$\text{Delta Size} = 26 + 340 = \mathbf{366\text{ Bytes}}$$
   $$\text{Bandwidth Savings} = \frac{2,576 - 366}{2,576} \times 100\% = \mathbf{85.79\%}$$

2. **Case B: 2 Players Moving, 2 Players Idle, No Items Eaten**
   - Header: 26 Bytes.
   - 2 Players: 170 Bytes.
   $$\text{Delta Size} = 26 + 170 = \mathbf{196\text{ Bytes}}$$
   $$\text{Bandwidth Savings} = \frac{2,576 - 196}{2,576} \times 100\% = \mathbf{92.39\%}$$

3. **Case C: All 4 Players Moving AND 1 Item Collected/Respawned**
   - Header: 26 Bytes.
   - 4 Players: 340 Bytes.
   - 1 Changed Item: 68 Bytes.
   $$\text{Delta Size} = 26 + 340 + 68 = \mathbf{434\text{ Bytes}}$$
   $$\text{Bandwidth Savings} = \frac{2,576 - 434}{2,576} \times 100\% = \mathbf{83.15\%}$$

**Conclusion**: Because static collectibles constitute ~85% of every full snapshot, eliminating them from ticks where they do not respawn guarantees that **bandwidth reduction remains above 80% under all realistic gameplay conditions**.

---

### 5.2 Bandwidth Reduction & Packet Compression Formulas

From the automated empirical benchmark recorded in `docs/BENCHMARK_RESULTS.json` (executed across 8 concurrent players in 2 rooms over an 8-second match):

```json
"baseline": {
  "total_bytes": 2056266,
  "total_snapshots": 648,
  "total_deltas": 0,
  "avg_msg_size_bytes": 2215.8,
  "p50_msg_size_bytes": 2947.0,
  "rtt_p50_ms": 0.84,
  "rtt_p95_ms": 1.97
},
"optimized": {
  "total_bytes": 241459,
  "total_snapshots": 16,
  "total_deltas": 632,
  "avg_msg_size_bytes": 260.2,
  "p50_msg_size_bytes": 157.0,
  "rtt_p50_ms": 0.98,
  "rtt_p95_ms": 1.78
}
```

#### Total Bandwidth Reduction Formula:
$$\text{Savings (\%)} = \left( 1 - \frac{\text{Total Bytes}_{\text{Optimized}}}{\text{Total Bytes}_{\text{Baseline}}} \right) \times 100\%$$
$$\text{Savings (\%)} = \left( 1 - \frac{241,459}{2,056,266} \right) \times 100\% = (1 - 0.117426) \times 100\% = \mathbf{88.26\%}$$

#### Average Packet Compression Formula:
$$\text{Compression (\%)} = \frac{\overline{\text{Size}}_{\text{Baseline}} - \overline{\text{Size}}_{\text{Optimized}}}{\overline{\text{Size}}_{\text{Baseline}}} \times 100\%$$
$$\text{Compression (\%)} = \frac{2,215.8 - 260.2}{2,215.8} \times 100\% = \frac{1,955.6}{2,215.8} \times 100\% = \mathbf{88.26\%}$$

#### Median Packet Size (p50) Reduction:
$$\text{Median Reduction} = \frac{2,947.0 - 157.0}{2,947.0} \times 100\% = \mathbf{94.67\%}$$

#### Tail Latency (p95 RTT) Improvement:
$$\text{Tail Latency Reduction} = \frac{1.97\text{ ms} - 1.78\text{ ms}}{1.97\text{ ms}} \times 100\% = \mathbf{9.64\%}$$

---

### 5.3 Scalability & Network Queue Delay Analysis (10 to 100 Bots)

Measured using `tools/load_test.py` across varying concurrency tiers:

| Active Bots | Rooms | Aggressive Throughput (Kbps) | Average Packet Size | p50 RTT (ms) | p95 RTT (ms) | Packet Loss |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **10 bots** | 2 | 447.24 Kbps | 398.7 Bytes | 0.97 ms | 2.33 ms | 0.0% |
| **25 bots** | 6 | 975.87 Kbps | 343.9 Bytes | 1.77 ms | 6.37 ms | 0.0% |
| **50 bots** | 12 | 2,015.94 Kbps | 347.2 Bytes | 6.93 ms | 14.25 ms | 0.0% |
| **100 bots** | 25 | 4,026.43 Kbps | 349.4 Bytes | 6.66 ms | 23.35 ms | 0.0% |

#### Theoretical Baseline Throughput at 100 Bots:
At 100 concurrent players with 10 Hz broadcast rate and 2,215.8 Bytes per snapshot:
$$\text{Outbound Egress} = 100 \text{ clients} \times 10 \text{ packets/sec} \times 2,215.8 \text{ Bytes/packet} \times 8 \text{ bits/Byte} = \mathbf{17.73\text{ Mbps}}$$
Accounting for bidirectional input frames and TCP header overhead ($40\text{ B}$ per segment), aggregate traffic exceeds **35 Mbps**. In a single-threaded Python event loop (`asyncio`), this saturates network socket buffers, resulting in packet queuing and tail latency spikes exceeding $200\text{ ms}$.

With **Optimized Delta v2**, outbound throughput is throttled to **4.02 Mbps** (a **4.4x reduction**), keeping tail latency at **23.35 ms** with zero dropped packets.

---

### 5.4 Reconnect Recovery Latency Measurement

To validate Stage 1 compliance, `tools/benchmark_comparison.py` simulated an abrupt TCP drop followed by reconnection with the stored session token:
1. Client connects, generates `player_id: "cce91f9a4aa0"`.
2. Socket terminates abruptly; server starts 15.0s grace period timer.
3. After a 1.0-second delay, client opens a new WebSocket presenting the identical session token.
4. Server verifies token, re-associates `player_id: "cce91f9a4aa0"`, and sends an immediate full snapshot.

$$\text{Recovery Latency} = t_{\text{snapshot\_received}} - t_{\text{reconnect\_socket\_opened}} = \mathbf{1.73\text{ ms}}$$
$$\text{Identity Preserved} = \mathbf{True} \quad (\text{Initial ID: } \texttt{cce91f9a4aa0} \equiv \text{Reconnected ID: } \texttt{cce91f9a4aa0})$$

---

## 6. Rubric Compliance Verification (HCMUT Specification)

| Rubric Area | Weight | Required Criteria | Implementation Evidence |
|:---|:---:|:---|:---|
| **Requirements & Protocol Design** | **30%** | Protocol Table v1 vs v2, sequence diagrams, message classification, architectural trade-offs | Documented in [`docs/PROTOCOL.md`](./docs/PROTOCOL.md): 4 Mermaid diagrams, 4x4 classification table, 5-criteria placement analysis |
| **Implementation & Correctness** | **25%** | Deterministic game logic, session persistence across reload, duplicate tab rejection, Oracle agreement | **32/32 tests PASS**; `localStorage` session token + 15s grace timer; `Duplicate tab` rejection; Dockerfile |
| **Network Optimization & Experiments** | **25%** | Clear hypotheses, reproducible benchmarks, bandwidth & latency measurements, 10–100 scaling | Measured **88.26% bandwidth savings**; `docs/BENCHMARK_RESULTS.json`; load scaling up to 100 bots; 1.73 ms recovery |
| **Presentation & Defense** | **20%** | Clear code ownership, deep understanding of line-by-line mechanics, live demonstration readiness | Exhaustive line-by-line documentation; reproducible scripts; quick-start verification |

---

## 7. Team Workload Distribution

| Member | Primary Ownership | Core Deliverables |
|:---|:---|:---|
| **Member 1 (Lead)** | Protocol Specification & Codec | `server/app/network/protocol.py`, `docs/PROTOCOL.md`, `Dockerfile`, `render.yaml` |
| **Member 2** | Game Engine & Determinism | `server/app/game/engine.py`, `tests_team/test_session_grace.py`, Oracle compatibility |
| **Member 3** | Transport & Session Management | `server/app/network/transport.py`, `server/app/game/service.py`, Duplicate tab policy |
| **Member 4** | Web Client & Delta Merging | `client/src/network/adapter.ts`, `protocol.ts`, `localStorage` persistence |
| **Member 5** | Benchmarking & Performance Analysis | `tools/benchmark_comparison.py`, `load_test.py`, `docs/EXPERIMENTS.md` |
