# Browser Scenario Mode — Network-Aware Input/Output Tests

The test runner coordinates multiple real browsers using a shared Run ID. Each browser loads the **same JSON scenario**, selects a different scripted player, joins the lobby, and clicks **Ready**. The test begins automatically only after **all players are Ready**.

## Run a browser test

1. Start the game locally or open the public HTTPS deployment.
2. In **Browser Scenario Mode**, upload the same `.input.json` file in every participating browser. Download samples from the UI or from `scenarios/browser/`.
3. Select a different scenario actor per browser (`alice`, `bob`, optionally `charlie`). Enter the same unique Run ID.
4. Choose **Correctness — lockstep** or **Networking — real time** in every browser.
5. Click **Connect to test lobby** and **Ready** in each browser, in any order.
6. The server runs the script. Each browser shows a final result and can download `<run-id>.result.json`.

The reference client uses the **ordinary application networking adapter** for scripted game actions. This is important: the separate test control channel cannot bypass or directly mutate game state.

## Two test modes

| Mode | Tick advancement | What it measures |
|---|---|---|
| **Correctness / lockstep** | The server requests player actions in the published input order within each logical tick, waits for confirmations from the *gameplay transport*, then advances the game | Mechanics, protocol correctness, ordering, duplication, loss/recovery under controlled conditions |
| **Networking / real time** | The server advances at 20 simulation ticks/sec whether or not player messages arrive | Actual latency consequences, late actions, end-to-end game correctness, player experience over LAN/Internet |

Input actions for the same player within one tick must appear contiguously in the scenario JSON. The lockstep runner serializes different actors' same-tick batches in the published order so browser/network arrival races cannot alter deterministic spawn and collision ordering.

The reported `tick_to_action_delivery_p50_ms`/`p95_ms` measure time from a simulator tick request to the game server confirming receipt of its action. This includes browser scheduling and network delivery; it is **not** TCP RTT or full cross-player action-to-observation latency.

In both modes the **Ready barrier** is shared. Users do not synchronize manual Start clicks or device clocks. The difference is that **real-time simulation never waits for slow network messages**.

A correctness PASS does not mean an application has low latency; run real-time tests separately. Scripted ticks and final state may diverge in real-time mode when messages are delayed. That is precisely what the networking evaluation should expose.

## Actual communication paths

```text
Browser A                              Browser B
    |                                     |
    +----------- TEST CONTROL -----------+
                 /sim/ws (Ready, tick, result)
                            |
                      Coordinator
                            |
           schedule request; verify delivery
                            |
    +------------ GAME DATA PLANE --------+
    |                                     |
   /ws        Student game protocol      /ws
    |                                     |
    +----------> GameService <------------+
                          |
                    Authoritative game
                          |
                     Final outcome
```

The **control channel** `/sim/ws` coordinates test sessions only. Browser actions (`join`, `input`, `rejoin`, `leave`) traverse the ordinary gameplay `/ws` adapter in the baseline; the game adapter sends `sim_game_ack` only after processing an action. The control channel verifies those confirmations before stepping in lockstep mode. Snapshots displayed in the browser also arrive from the **gameplay transport**.

Students replacing WebSocket with HTTP short/long polling or another low-level transport must update both the normal game adapter and **`ScenarioDataTransport` in `client/src/network/adapter.ts`** to exercise their own transport. Keeping the reference WebSocket data path solely for tests does not validate an alternative gameplay transport.

## Scenario inputs

The versioned input format is in `scenarios/browser/*.input.json`. Each event includes a scheduled integer `tick`, `op` (join, leave, rejoin, input) and stable `player` ID. Input events also contain `seq`, cardinal movement (`dx`, `dy`) and optional `cloak`.

Published sample pairs:

| Pair | Participants | Focus |
|---|---:|---|
| `two_player_finish` | 2 | Join, movement, match end |
| `late_join_finish` | 3 | Mid-game join and departures |
| `duplicate_input_finish` | 2 | Stale/duplicate input sequence handling |
| `credit_cloak_finish` | 2 | Deterministic collection of 7 credits, 5-credit cloak cost, final balance 2 |

Each sample has a `*.input.json` and `*.expected.json`. The input is uploaded by every browser; it is **not** fetched from the server as a privileged script. All browsers submit the same canonical scenario SHA-256.

Maximum reference harness limits: 8 browser actor slots, 600 ticks per scenario, 1,500 scripted events, and an 8-second lockstep action deadline. Use `tools/load_test.py` for larger simulated client populations.

## Grading the final result

The canonical terminal outcome consists of the **finished round, winner, surviving/eliminated player entries still in the room and remaining credits**. Intermediate frame coordinates, snapshot timing and individual tick-state equality are **not** graded.

The browser result contains `actual`, `expected`, `scenario_sha256`, `verdict`, `mode` and statistics (confirmed actions, late data actions, tick-to-delivery p50/p95, timeouts and wall-clock duration). Public fixture outcomes are **pinned JSON**, so editing the submission's game engine does not automatically change their expected results.

Use an **independent checker** instead of trusting an application-written `PASS`:

```bash
python tools/verify_result.py \
  --expected scenarios/browser/credit_cloak_finish.expected.json \
  --result /path/to/downloaded-run.result.json
```

The checker compares the downloaded actual result with the trusted expected file and exits nonzero if incorrect. For official grading, run the checker and hidden fixture generation in an **instructor-controlled environment**; do not treat submitted code or self-reported results as authoritative.

## Testing and experiments

```bash
npm ci --prefix client
npm run build --prefix client
PYTHONPATH=server python -m unittest discover -s server/tests -v
python tools/browser_fixture_io.py --check
python -m pip install playwright
python -m playwright install chromium
python tools/browser_e2e.py
```

CI executes both the HTTP/WebSocket integration tests and real Chromium windows/tabs. Network impairment tools such as Linux `tc netem` or a dedicated network proxy may introduce latency, jitter, temporary disconnections or loss on the *game data-plane*. With TCP, packet loss generally produces retransmission delays rather than arbitrary out-of-order application messages. See [SCENARIO_TESTING.md](SCENARIO_TESTING.md).

### Input / output contract ownership

Teams may redesign state, serialization, gameplay communication, sync/update frequency and UI. Fixed mechanics, published JSON sample fixtures and the terminal-outcome comparison contract must be preserved. They may add new scenarios without changing instructor fixtures.
