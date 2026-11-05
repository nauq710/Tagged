# Scripted scenarios and completed-match oracle

A scripted scenario lists `join`, `rejoin`, `leave` and `input` actions scheduled along an intended tick timeline. Its local oracle uses a deterministic room seed and game rules. The live runner sends the corresponding actions through the network. The **grading comparison is the result of a completed match**, not an exact match of each tick or of every snapshot.

## What the oracle checks

A scenario that ends in a `finished` round has a canonical `final_result` with:

- Completed round number and winner (resolved to scenario player identities).
- Alive/eliminated status for the final participating players.
- Credits held by each participating player at the end of the round.

Players are matched by their stable scenario IDs rather than randomized WebSocket session IDs. The evaluation disregards intermediate ticks, how often a state is transmitted, intermediate snapshots, final player coordinates, and network-message arrival order unless they change the **final game result**. The game mechanics themselves remain fixed in `server/app/game/rules.py`.

A scenario whose last round is still `running` or `waiting` receives `final_comparison.status = "not_terminal"`. Such scenarios are useful for functional testing but do not establish terminal-outcome correctness.

## Run the local oracle

```sh
python tools/scenario_runner.py scenarios/terminal_winner.json --mode oracle --output oracle.json
python tools/scenario_runner.py scenarios/room_lifecycle.json --mode oracle --output lifecycle.json
```

The terminal oracle writes `final_result` to the JSON output. Full tick traces are retained for debugging, not for grading equality.

## Run the same scenario over networking

Start the Python server, then:

```sh
python tools/scenario_runner.py scenarios/terminal_winner.json --mode live --url http://127.0.0.1:8000 --output local-run.json
python tools/scenario_runner.py scenarios/terminal_winner.json --mode live --url https://YOUR-DEPLOYMENT.onrender.com --output internet-run.json
```

Live results include `final_result` and `final_comparison`. A terminal scenario **passes** when the completed-game results agree. A wrong winner, missing/extra player, wrong surviving status or credit total **fails**. Clients are allowed a configurable settling period (`--settle-seconds`, default 1 second) to receive the finished result. Their reported snapshot ticks need not be equal; inconsistent terminal outcomes across observers fail the check.

## Controlled network impairment

```sh
python tools/scenario_runner.py scenarios/terminal_winner.json --mode live \
  --url http://127.0.0.1:8000 --delay-ms 120 --jitter-ms 50 \
  --drop-rate 0.20 --duplicate-rate 0.10 --output impaired-run.json
```

The runner applies faults to **application input messages**. This is not IP packet loss. For TCP-level latency or loss experiments, use a dedicated Linux test interface with `tc netem`, or a reversible TCP proxy (e.g. Toxiproxy) for latency/disconnection tests.

```sh
sudo tc qdisc add dev eth0 root netem delay 100ms 30ms loss 5%
sudo tc qdisc del dev eth0 root
```

Apply such rules only on a dedicated test interface, VM or container.

A delayed action can be processed at a different simulation tick, and a dropped action may never reach the server. **If that changes the final result, the scenario fails**; the network implementation must recover, compensate or report its limitations. This is different from requiring identical intermediate state, which is unnecessary. Besides the outcome verdict, record delivery counts, latency and bandwidth to explain differences and optimization trade-offs.

## Extending the harness

The supplied live driver uses baseline JSON/WebSocket. A group adopting polling, long polling or another permitted transport may replace that driver, while preserving published scenarios and the same outcome projection/verification contract. Do not edit `server/tests/` or `scenarios/`; create extra tests/scenarios separately.

The reference game rules are also verified by unit tests for collectible credits, growth, movement/speed scaling, decay, cloak, collisions, elimination, match lifecycle and rejoining.
