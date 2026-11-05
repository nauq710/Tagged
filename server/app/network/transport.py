"""Student-editable baseline WebSocket game transport.

The simulator control channel (/sim/ws) never changes game state.
Scripted browser actions must traverse this *ordinary* application transport.
Teams replacing WebSocket must implement equivalent scenario action/ack support
in their own data-plane adapter, keeping the published input/output contract.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING
from aiohttp import WSMsgType, web
from .protocol import decode_message, encode_message, encode_delta, parse_input
from ..game.service import GameService

if TYPE_CHECKING:
    from ..simulator.transport import SimulatorTransport, SimRun

logger = logging.getLogger(__name__)


class GameTransport:
    def __init__(self, service: GameService):
        self.service = service
        self.simulator: SimulatorTransport | None = None
        self.sockets: dict[str, web.WebSocketResponse] = {}
        self.last_snapshots: dict[str, dict] = {}
        self.client_supports_delta: dict[str, bool] = {}
        self.bytes_sent_full: int = 0
        self.bytes_sent_delta: int = 0

    def install_routes(self, app: web.Application) -> None:
        app.router.add_get('/ws', self.websocket)
        app.router.add_get('/stats', self.stats)

    async def stats(self, _request: web.Request) -> web.Response:
        from aiohttp import web as _web
        return _web.json_response({
            'bytes_full': self.bytes_sent_full,
            'bytes_delta': self.bytes_sent_delta,
        })

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8192)
        await ws.prepare(request)
        player_id: str | None = None
        sim_run: str | None = None
        sim_actor: str | None = None
        try:
            async for packet in ws:
                if packet.type != WSMsgType.TEXT:
                    continue
                data = decode_message(packet.data)
                if data is None:
                    await ws.send_json({'type': 'error', 'message': 'Invalid message JSON'})
                    continue
                kind = data.get('type')
                try:
                    ctx = None
                    event = None
                    tick = index = None
                    if 'sim_run' in data:
                        if not self.simulator:
                            raise ValueError('Scenario adapter disabled')
                        token, actor = data.get('sim_run'), data.get('sim_actor')
                        if not isinstance(token, str) or not isinstance(actor, str):
                            raise ValueError('Missing simulated run and actor')
                        if sim_run is not None and (token != sim_run or actor != sim_actor):
                            raise ValueError('Scenario actor cannot change on a connection')
                        ctx = self.simulator.authorize(token, actor)
                        tick, index = data.get('sim_tick'), data.get('sim_index')
                        if kind == 'join':
                            event = {'tick': tick, 'op': 'join', 'player': actor,
                                     'name': str(data.get('name', actor))}
                        elif kind == 'input':
                            action = parse_input(data)
                            if action is None:
                                raise ValueError('Invalid input action')
                            seq, dx, dy, cloak = action
                            event = {'tick': tick, 'op': 'input', 'player': actor,
                                     'seq': seq, 'dx': dx, 'dy': dy, 'cloak': cloak}
                        elif kind in ('leave', 'rejoin'):
                            event = {'tick': tick, 'op': kind, 'player': actor}
                        else:
                            raise ValueError('Unsupported scenario operation')
                        repeated = ctx.validate_data_action(actor, tick, index, event)
                        if repeated:
                            await ws.send_json({'type': 'sim_game_ack', 'tick': tick,
                                                'index': index, 'duplicate': True})
                            continue

                    if kind == 'join' and player_id is None:
                        wants_delta = bool(data.get('delta', False))
                        if ctx:
                            player_id = ctx.player_id(actor)
                            welcome = self.service.sim_join(
                                actor, ctx.scenario['room'], token, event['name'])
                            sim_run, sim_actor = token, actor
                        else:
                            welcome = self.service.join(
                                str(data.get('name', ''))[:18],
                                str(data.get('room', 'main')))
                            player_id = welcome['id']
                        self.sockets[player_id] = ws
                        self.client_supports_delta[player_id] = wants_delta
                        await ws.send_json(welcome)
                        snapshot = self.service.snapshot_for(player_id)
                        if snapshot is not None:
                            await ws.send_json(snapshot)
                    elif kind == 'input' and player_id is not None:
                        action = parse_input(data)
                        if action is None:
                            raise ValueError('Invalid movement or ability input')
                        self.service.apply_input(player_id, *action)
                    elif kind == 'rejoin' and player_id is not None:
                        if not self.service.rejoin(player_id):
                            raise ValueError('Rejoin unavailable')
                    elif kind == 'leave' and player_id is not None and ctx:
                        self.service.leave(player_id)
                    elif kind == 'ping':
                        nonce = data.get('nonce')
                        if isinstance(nonce, (float, int)) and not isinstance(nonce, bool):
                            await ws.send_json({'type': 'pong', 'nonce': nonce})
                        continue
                    else:
                        raise ValueError('Join first or unknown message')
                    if ctx and event is not None:
                        ctx.confirm_data_action(actor, tick, index)
                        await ws.send_json({'type': 'sim_game_ack', 'tick': tick,
                                            'index': index, 'duplicate': False})
                except (ValueError, KeyError, TypeError) as exc:
                    await ws.send_json({'type': 'error', 'message': str(exc)})
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            if player_id:
                self.sockets.pop(player_id, None)
                self.last_snapshots.pop(player_id, None)
                self.client_supports_delta.pop(player_id, None)
                self.service.leave(player_id)
        return ws

    async def publish(self, snapshots: dict[str, dict]) -> None:
        jobs = []
        sends: list[tuple[str, str]] = []  # (player_id, encoded)
        for player_id, ws in list(self.sockets.items()):
            room = self.service.player_rooms.get(player_id)
            if room and room in snapshots and not ws.closed:
                snapshot = self.service.snapshot_for(player_id)
                if snapshot is not None:
                    prev = self.last_snapshots.get(player_id)
                    if prev is not None and self.client_supports_delta.get(player_id, False):
                        encoded = encode_delta(prev, snapshot)
                    else:
                        encoded = encode_message(snapshot)
                    self.last_snapshots[player_id] = snapshot
                    sends.append((player_id, encoded))
                    jobs.append(ws.send_str(encoded))
        if jobs:
            results = await asyncio.gather(*jobs, return_exceptions=True)
            for (player_id, encoded), result in zip(sends, results):
                if isinstance(result, Exception):
                    logger.debug('Snapshot write error: %r', result)
                else:
                    try:
                        msg_type = json.loads(encoded).get('type')
                    except Exception:
                        msg_type = 'snapshot'
                    if msg_type == 'delta':
                        self.bytes_sent_delta += len(encoded.encode())
                    else:
                        self.bytes_sent_full += len(encoded.encode())

    async def close(self) -> None:
        await asyncio.gather(*(ws.close() for ws in list(self.sockets.values())),
                             return_exceptions=True)
