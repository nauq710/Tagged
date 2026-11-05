# Network experiments

Develop a baseline measurement and at least one protocol optimization using the *same mechanics*. Use identical scripts/seeds, identical room size and comparable network conditions. Correctness is a hard gate: a completed scenario must produce the expected final winner, remaining players and credits. Intermediate tick/state equivalence is not required.

| Stage | Setup | Observations |
|---|---|---|
| Localhost | 1–2 browser tabs | Join and game rules, input-to-update, protocol messages |
| LAN | 2–4 actual devices | Consistency, latency, ability visibility, disconnection/rejoin |
| Internet | Render Free or equivalent | Remote player gameplay, RTT, update freshness, message/byte traffic |
| Load | 10, 25, 50, 100 bots when feasible | Network load, missing actions/updates, RTT p95, convergence |

Use `tools/load_test.py` for scalable baseline WS clients and `tools/scenario_runner.py` for repeatable timelines, terminal outcome checks and controlled message faults. A `not_terminal` result indicates a scenario that has not completed a round, not a grading pass. Read `docs/SCENARIO_TESTING.md` before interpreting an oracle-to-Internet comparison. Do not compare cloud cost or CPU tuning; this assignment assesses application networking.
