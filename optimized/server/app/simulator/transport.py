"""Test control-plane coordinator.

Control messages schedule and synchronize browser actions. The control-plane
NEVER applies a scripted action to the game. All join/input/rejoin/leave events
must be confirmed after passage through the normal game networking adapter.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
import time
import statistics

from aiohttp import web, WSMsgType

from .contract import (
    RUN_ID, canonical_outcome, result_report, scenario_digest, validate_scenario,
)
from ..game.service import GameService
from ..game.rules import TICK_RATE

MAX_RUNS = 8
ACK_TIMEOUT = 8.0
TICK_SECONDS = 1.0 / TICK_RATE


class SimRun:
    def __init__(self, run_id: str, scenario: dict, actors: list[str],
                 service: GameService, mode: str = 'lockstep'):
        self.run_id, self.scenario, self.actors = run_id, scenario, actors
        self.service, self.mode = service, mode
        self.digest = scenario_digest(scenario)
        self.clients: dict[str, web.WebSocketResponse] = {}
        self.ready: set[str] = set()
        self.state = 'lobby'
        self.task: asyncio.Task | None = None
        self.pending: set[str] = set()
        self.finished: set[tuple[int, str]] = set()
        self.pending_tick = -1
        self.arrival_event = asyncio.Event()
        self.abort_reason: str | None = None
        self.expected: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for event in scenario['events']:
            self.expected[event['tick']][event['player']].append(event)
        self.confirmed: dict[tuple[int, str], set[int]] = defaultdict(set)
        self.acknowledged_batches = 0
        self.delivery_count = 0
        self.tick_requests: dict[tuple[int, str], float] = {}
        self.delivery_latency_ms: list[float] = []
        self.late_count = 0
        self.timeout_count = 0
        self.created = time.monotonic()

    def player_id(self, actor: str) -> str:
        return f'_sim_{self.run_id}_{actor}'

    async def send_all(self, data: dict) -> None:
        for ws in list(self.clients.values()):
            if not ws.closed:
                try:
                    await ws.send_json(data)
                except (ConnectionError, RuntimeError):
                    pass

    async def lobby(self) -> None:
        await self.send_all({
            'type': 'sim_lobby', 'mode': self.mode, 'players': self.actors,
            'ready': sorted(self.ready), 'connected': sorted(self.clients),
            'run_id': self.run_id, 'scenario_sha256': self.digest,
        })

    async def register(self, actor: str, ws: web.WebSocketResponse) -> None:
        if self.state != 'lobby' or actor not in self.actors or actor in self.clients:
            raise ValueError('Cannot register: run started, invalid or duplicate player')
        self.clients[actor] = ws
        await ws.send_json({
            'type': 'sim_registered', 'player': actor, 'run_id': self.run_id,
            'mode': self.mode, 'players': self.actors,
            'scenario_sha256': self.digest,
        })
        await self.lobby()

    async def mark_ready(self, actor: str) -> None:
        if self.state != 'lobby' or actor not in self.clients:
            raise ValueError('Player is not in the waiting lobby')
        self.ready.add(actor)
        await self.lobby()
        if len(self.ready) == len(self.actors) and len(self.clients) == len(self.actors):
            self.state = 'running'
            self.task = asyncio.create_task(self.execute())

    def validate_data_action(self, actor: str, tick: object, index: object,
                             event: dict) -> bool:
        """Verify action ownership/contents before the REAL game adapter applies it.

        Identical duplicate deliveries are reported as already seen, which
        prevents joins/abilities being executed twice.
        """
        if self.state != 'running' or actor not in self.clients:
            raise ValueError('No active scripted run for this actor')
        if type(tick) is not int or type(index) is not int or tick < 0 or index < 0:
            raise ValueError('Invalid scenario tick/index')
        if self.mode == 'lockstep' and tick != self.pending_tick:
            raise ValueError('Action outside current lockstep tick')
        if self.mode == 'realtime' and tick > self.pending_tick:
            raise ValueError('Action from a future tick')
        actions = self.expected.get(tick, {}).get(actor, [])
        if index >= len(actions) or actions[index] != event:
            raise ValueError(f'{actor}: data-plane action differs from scenario at tick {tick}')
        return index in self.confirmed[(tick, actor)]

    def confirm_data_action(self, actor: str, tick: int, index: int) -> None:
        self.confirmed[(tick, actor)].add(index)
        self.delivery_count += 1
        requested_at = self.tick_requests.get((tick, actor))
        if requested_at is not None:
            self.delivery_latency_ms.append((time.monotonic() - requested_at) * 1000)
        if self.mode == 'realtime' and self.service.rooms[self.scenario['room']].tick > tick:
            self.late_count += 1

    def batch_completed(self, actor: str, tick: object, count: object) -> None:
        if self.state != 'running' or type(tick) is not int:
            raise ValueError('Action batch not expected')
        if type(count) is not int:
            raise ValueError('Invalid action count')
        if self.mode == 'lockstep' and tick != self.pending_tick:
            raise ValueError('Action batch outside current tick')
        required = self.expected.get(tick, {}).get(actor)
        if required is None or count != len(required):
            raise ValueError('Action batch count does not match scenario')
        if self.confirmed.get((tick, actor), set()) != set(range(len(required))):
            raise ValueError('Game transport did not confirm all scripted actions')
        if (tick, actor) in self.finished:
            return
        self.finished.add((tick, actor))
        self.acknowledged_batches += 1
        if self.mode == 'lockstep':
            self.pending.discard(actor)
            if not self.pending:
                self.arrival_event.set()

    async def execute(self) -> None:
        start = time.monotonic()
        failure = None
        world = None
        room = self.scenario['room']
        try:
            self.service.start_sim_room(room)
            await self.send_all({
                'type': 'sim_started', 'mode': self.mode, 'run_id': self.run_id,
                'ticks': self.scenario['ticks'], 'countdown_seconds': 0.3,
            })
            await asyncio.sleep(0.3)
            start = time.monotonic()
            for tick in range(self.scenario['ticks']):
                if self.abort_reason:
                    raise RuntimeError(self.abort_reason)
                scheduled = self.expected.get(tick, {})
                self.pending_tick = tick
                if self.mode == 'lockstep':
                    # Simultaneous browser messages can arrive in different
                    # orders. Preserve the published scenario order while
                    # exercising every action through the actual game channel.
                    for actor in scheduled:
                        self.pending = {actor}
                        self.arrival_event.clear()
                        ws = self.clients.get(actor)
                        if ws is None or ws.closed:
                            raise RuntimeError(f'{actor}: control browser disconnected')
                        self.tick_requests[(tick, actor)] = time.monotonic()
                        await ws.send_json({'type': 'sim_tick', 'tick': tick, 'run_id': self.run_id})
                        try:
                            await asyncio.wait_for(self.arrival_event.wait(), ACK_TIMEOUT)
                        except asyncio.TimeoutError:
                            self.timeout_count += 1
                            raise RuntimeError(f'Game transport timeout for {actor} at tick {tick}')
                        if self.abort_reason or self.pending:
                            raise RuntimeError(self.abort_reason or f'Incomplete action batch for {actor}')
                else:
                    # Real-time test keeps simultaneous actors concurrent and
                    # NEVER holds the simulation tick open for slow messages.
                    self.pending = set(scheduled)
                    for actor in scheduled:
                        ws = self.clients.get(actor)
                        if ws is None or ws.closed:
                            raise RuntimeError(f'{actor}: control browser disconnected')
                        await ws.send_json({'type': 'sim_tick', 'tick': tick, 'run_id': self.run_id})
                    await asyncio.sleep(max(0, start + (tick + 1) * TICK_SECONDS - time.monotonic()))
                # This advances the ordinary game's own state. Crucially, no
                # event is applied here: events came via normal /ws or alternate
                # student-defined data-plane endpoints.
                self.service.sim_step(room)
                if self.mode == 'lockstep':
                    await asyncio.sleep(0)  # Yield for browser UI, no wall-clock barrier.
            if self.mode == 'realtime':
                await asyncio.sleep(0.15)
            world = self.service.rooms[room]
        except (RuntimeError, ValueError) as exc:
            failure = str(exc)
            world = self.service.rooms.get(room)
        except asyncio.CancelledError:
            failure = 'Run cancelled'
            world = self.service.rooms.get(room)
        finally:
            self.pending_tick = -1
            self.state = 'finished'
            identities = {self.player_id(a): a for a in self.actors}
            observed = canonical_outcome(world, identities) if world else None
            report = result_report(
                self.scenario, observed, run_id=self.run_id,
                elapsed_seconds=time.monotonic() - start,
                responses=self.acknowledged_batches,
                timeout_count=self.timeout_count, error=failure,
            )
            report['mode'] = self.mode
            report['stats']['data_actions_confirmed'] = self.delivery_count
            report['stats']['late_data_actions'] = self.late_count
            report['stats']['browser_action_batches'] = self.acknowledged_batches
            report['stats']['data_actions_expected'] = len(self.scenario['events'])
            # This measures tick-request -> server-side game-action delivery,
            # including browser scheduling and network, NOT application RTT.
            latencies = sorted(self.delivery_latency_ms)
            report['stats']['tick_to_action_delivery_p50_ms'] = (
                round(statistics.median(latencies), 2) if latencies else None)
            report['stats']['tick_to_action_delivery_p95_ms'] = (
                round(latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)], 2)
                if latencies else None)
            await self.send_all({'type': 'sim_result', 'report': report})
            # Delay removal so in-flight data-plane clients can close cleanly.
            self.service.finish_sim_room(room)

    async def disconnected(self, actor: str) -> None:
        self.clients.pop(actor, None)
        self.ready.discard(actor)
        if self.state == 'running':
            self.abort_reason = f'{actor}: browser disconnected from test'
            self.arrival_event.set()
        if self.state == 'lobby':
            await self.lobby()


class SimulatorTransport:
    def __init__(self, service: GameService):
        self.service = service
        self.runs: dict[str, SimRun] = {}

    def install_routes(self, app: web.Application) -> None:
        app.router.add_get('/sim/ws', self.websocket)

    def cleanup(self) -> None:
        for run_id, run in list(self.runs.items()):
            if run.state != 'running' and not run.clients:
                del self.runs[run_id]

    def authorize(self, run_id: str, actor: str) -> SimRun:
        run = self.runs.get(run_id)
        if run is None or run.state != 'running' or actor not in run.clients:
            raise ValueError('Player is not registered in an active scenario')
        return run

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=131072)
        await ws.prepare(request)
        run: SimRun | None = None
        actor: str | None = None
        try:
            async for packet in ws:
                if packet.type != WSMsgType.TEXT:
                    continue
                try:
                    import json
                    data = json.loads(packet.data)
                    if not isinstance(data, dict):
                        raise ValueError('Invalid simulator control message')
                    kind = data.get('type')
                    if kind == 'sim_register' and run is None:
                        self.cleanup()
                        run_id = data.get('run_id')
                        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
                            raise ValueError('Invalid Run ID')
                        script, roster = validate_scenario(data.get('scenario'))
                        mode = data.get('mode', 'lockstep')
                        if mode not in ('lockstep', 'realtime'):
                            raise ValueError('Mode must be lockstep or realtime')
                        if run_id not in self.runs:
                            if len(self.runs) >= MAX_RUNS:
                                raise ValueError('Too many simultaneous scenario runs')
                            if any(r.scenario['room'] == script['room'] for r in self.runs.values()):
                                raise ValueError('Scenario room in use; choose another scenario room')
                            self.runs[run_id] = SimRun(run_id, script, roster, self.service, mode)
                        selected = self.runs[run_id]
                        if selected.digest != scenario_digest(script) or selected.mode != mode:
                            raise ValueError('Scenario or execution mode differs from active run')
                        player = data.get('player')
                        if not isinstance(player, str):
                            raise ValueError('Choose a scripted player')
                        await selected.register(player, ws)
                        run, actor = selected, player
                    elif kind == 'sim_ready' and run and actor:
                        await run.mark_ready(actor)
                    elif kind == 'sim_actions' and run and actor:
                        run.batch_completed(actor, data.get('tick'), data.get('count'))
                    else:
                        raise ValueError('Register and Ready before submitting actions')
                except (TypeError, ValueError, KeyError) as exc:
                    await ws.send_json({'type': 'sim_error', 'message': str(exc)})
        finally:
            if run and actor:
                await run.disconnected(actor)
        return ws

    async def close(self) -> None:
        for run in self.runs.values():
            if run.task and not run.task.done():
                run.task.cancel()
        await asyncio.gather(
            *(run.task for run in self.runs.values() if run.task),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(ws.close() for run in self.runs.values() for ws in run.clients.values()),
            return_exceptions=True,
        )
