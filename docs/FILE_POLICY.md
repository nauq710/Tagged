# Editing policy

The grading contract is **observable game behavior**, not a particular code layout or message format. Students may create files and reorganize the monorepo as necessary.

| Path | Policy | Why |
|---|---|---|
| `server/app/game/rules.py` | **DO NOT EDIT** | Instructor-defined gameplay constants and rule functions |
| `server/tests/` and `scenarios/` | **DO NOT EDIT** | Published behavioral tests and standard scenario inputs |
| `client/src/ui/`, `client/src/network/` | **EDIT** | Appearance, network protocol, transport, buffering |
| `client/src/core/`, `client/src/main.ts` | **EDIT** | Client state, local prediction, input scheduling, app lifecycle |
| `server/app/game/engine.py` | **EDIT** | Authoritative state representation and storage, state update/synchronization (must preserve game rules) |
| `server/app/game/service.py` | **EDIT** | Room/session lifecycle implementation and state management |
| `server/app/network/`, `server/app/main.py` | **EDIT** | HTTP/WebSocket endpoints, encoding, transport, game loop implementation |
| `tools/` (except instructor fixtures) | **EDIT** | Load generation, network experiments and adapters |
| `docs/`, `client/package.json`, deployment | **EDIT** | Docs and justified build/deploy changes |

**Game mechanics are hard constraints.** Do not alter start/end conditions, map dimensions, collectible values, movement restrictions, cloak duration/cost, credit-to-size formula, credit-to-speed scaling, periodic credit decay, or collision/credit transfer rules. The final tests validate behavior, including hidden state and rejoin semantics. Your code may implement these rules in any architecture, but it must produce equivalent outcomes.

## Networking libraries

Use transport-level primitives, e.g. browser `WebSocket` / `fetch`, Python `asyncio`, and `aiohttp` low-level HTTP or WS interfaces. WebSocket is the **reference**, not a requirement; HTTP short/long polling and other suitable transports are allowed. Do not use high-level libraries that provide ready-made game sessions, room management, replication, or automatic game synchronization (Socket.IO, Colyseus, Nakama, Photon, Firebase/Supabase Realtime, or equivalent). Ordinary graphics/frontend/UI libraries are allowed. Additional source files are allowed.

Do not depend on network simulator/fault tools for ordinary gameplay; use them only in controlled experiments.

## Final-state grading contract

Completed-match scenarios are graded on the final **winner, round, alive/eliminated roster, and remaining credits**, using scenario identities rather than internal network-generated IDs. Per-tick snapshot equality and final player coordinates are not requirements. Students may change tick handling, communication cadence, buffering and synchronization while preserving the completed-game outcome.


## Browser scenario input/output contract

The versioned JSON input schema, fixed sample scenarios and expected output files in `scenarios/browser/`, and the instructor tests remain unchanged. Browser scenario clients upload the same scenario, select distinct player slots and wait at a server-driven Ready barrier. The complete result file uses `tag-lagged-browser-result-v1` and compares the winner, round, alive roster and remaining credits. Client and server implementation may change; preserve the visible JSON input/output contract.

Simulator test orchestration runs over `/sim/ws` and must never apply game events directly. The scripted player must use the same gameplay data-plane used for ordinary play. Students adopting HTTP polling/long polling must adapt `ScenarioDataTransport` in `client/src/network/adapter.ts` and the corresponding server networking adapter; using baseline `/ws` solely for tests does not demonstrate the chosen alternative transport. The reference game rules and published scenario fixtures remain authoritative.
