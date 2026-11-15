"""INSTRUCTOR-OWNED: application bootstrap, fixed simulation timing and web serving."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import os
from pathlib import Path

from aiohttp import web

from .game.rules import SNAPSHOT_RATE, TICK_RATE
from .game.service import GameService
from .network.transport import GameTransport
from .simulator.transport import SimulatorTransport

FRONTEND_DIST = Path(__file__).resolve().parents[2] / 'client' / 'dist'


async def health(_request: web.Request) -> web.Response:
    return web.json_response({'status': 'ok', 'game': 'move-collect-tag'})


async def index(_request: web.Request) -> web.Response:
    path = FRONTEND_DIST / 'index.html'
    if not path.is_file():
        return web.Response(text='Frontend not built. Run: cd client && npm run dev', content_type='text/plain')
    return web.FileResponse(path)


async def lifecycle(app: web.Application):
    transport: GameTransport = app['transport']
    service: GameService = app['service']
    simulator: SimulatorTransport = app['simulator']

    async def ticker() -> None:
        interval = 1 / TICK_RATE
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        ticks = 0
        while True:
            next_tick += interval
            snapshots = service.advance()
            ticks += 1
            if ticks % (TICK_RATE // SNAPSHOT_RATE) == 0:
                await transport.publish(snapshots)
            await asyncio.sleep(max(0, next_tick - loop.time()))

    task = asyncio.create_task(ticker())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await simulator.close()
    await transport.close()


def create_app() -> web.Application:
    app = web.Application()
    service = GameService()
    transport = GameTransport(service)
    simulator = SimulatorTransport(service)
    app['service'] = service
    transport.simulator = simulator
    app['transport'] = transport
    app['simulator'] = simulator
    app.router.add_get('/health', health)
    transport.install_routes(app)
    simulator.install_routes(app)
    app.router.add_get('/', index)
    assets = FRONTEND_DIST / 'assets'
    if assets.is_dir():
        app.router.add_static('/assets', assets)
    samples = FRONTEND_DIST / 'samples'
    if samples.is_dir():
        app.router.add_static('/samples', samples)
    app.cleanup_ctx.append(lifecycle)
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '8000')))
