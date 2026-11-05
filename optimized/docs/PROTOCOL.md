# Reference application protocol

These message types document **one playable baseline**, not the expected final student design.

| Message | Direction | Fields | Meaning |
|---|---|---|---|
| `join` | C→S | `name`, `room` | Create or enter a room; first player waits |
| `welcome` | S→C | `id`, `room`, world size, rates | Identity and environment metadata |
| `input` | C→S | `seq`, `dx`, `dy`, `cloak` | Four-direction input; `cloak=true` requests ability |
| `snapshot` | S→C | `tick`, `round`, `phase`, `winner`, `players`, `items`, `events` | Reference full-state broadcast (10 Hz) |
| `rejoin` | C→S | no fields | Re-enter as a fresh player after elimination; or start next round |
| `ping` / `pong` | C↔S | `nonce` | Application-level RTT measurement |
| `error` | S→C | `message` | Rejected operation |

## Room lifecycle

- First player creates a waiting room. The match starts automatically with at least two players.
- Additional players can join an in-progress round with zero credits.
- A player who dies is eliminated from the current life, but can `rejoin` with zero credits.
- When one player remains alive, the match finishes, recording the winner. A subsequent join/rejoin opens a new round and resets the remaining participants.
- A disconnected participant leaves the room. An empty room is removed.

## Game mechanics

See `server/app/game/rules.py` for the canonical values. Fixed map: 960×600. 20 simulation ticks/sec; baseline sends full snapshots 10/sec. Cardinal movement only (up, down, left, right), with continuous floating-point map coordinates. Movement slows smoothly as credits grow: `speed_for(c) = max(65, 170 / (1 + 0.09 * sqrt(c)))` world units/second. This results in steps of at most 8.5 world units at 20 simulation ticks/sec. Items respawn at deterministic pseudo-random positions; three tiers award 1, 3 and 7 credits. Radius grows with credits. Every 5 seconds (100 ticks) after entering a life/round, an alive player loses `ceil(0.02 * credits)` credits (zero if empty). Decay occurs at the end of the simulation tick, after abilities, movement, collectibles and collisions, and produces a `decay` event when credits decrease. Cloak lasts 3 seconds (60 ticks) and costs 5 credits; it hides the player from opponents' snapshots but does not protect against contact. On contact, the player with **strictly greater** credits eliminates the smaller-credit player and acquires ceil(40% of the eliminated player's credits); equal-credit collision causes no elimination. Only the server decides collection/collisions.

## Design questions

Specify encoding, semantics, ordering, rate, reliability, delivery recipients, recovery from disconnection, client state prediction, reconciliation, protocol correctness, and measurements. You may implement an alternative protocol/transport as long as these game semantics hold.

## Completed-match output

Automated outcome validation compares the completed round number, winner identity, alive/eliminated roster and final credits. It does not require equal intermediate ticks, snapshot timing, final positions, or a particular state representation. Teams may use any permitted low-level transport and serialization as long as the canonical game results are preserved.
