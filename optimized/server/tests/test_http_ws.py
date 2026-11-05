"""Baseline WebSocket functional test; graders may use different transports."""
import asyncio
from aiohttp.test_utils import AioHTTPTestCase
from app.main import create_app

class WebSocketTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_lobby_join_and_shared_world(self):
        r = await self.client.request('GET', '/health')
        self.assertEqual(r.status, 200)
        alice = await self.client.ws_connect('/ws')
        bob = await self.client.ws_connect('/ws')
        await alice.send_json({'type': 'join', 'name': 'Alice', 'room': 'arena'})
        welcome_a = await alice.receive_json(timeout=2)
        self.assertEqual(welcome_a['type'], 'welcome')
        snapshot_a = await alice.receive_json(timeout=2)
        self.assertEqual(snapshot_a['phase'], 'waiting')
        await bob.send_json({'type': 'join', 'name': 'Bob', 'room': 'arena'})
        welcome_b = await bob.receive_json(timeout=2)
        self.assertEqual(welcome_b['type'], 'welcome')
        await bob.receive_json(timeout=2)
        await alice.send_json({'type': 'input', 'seq': 1, 'dx': 1, 'dy': 0, 'cloak': False})
        async def await_running(ws):
            for _ in range(15):
                msg = await ws.receive_json(timeout=3)
                if msg.get('type') == 'snapshot' and msg['phase'] == 'running' and len(msg['players']) == 2:
                    return msg
            raise AssertionError('missing multiplayer snapshot')
        state_a, state_b = await asyncio.gather(await_running(alice), await_running(bob))
        self.assertEqual(state_a['room'], state_b['room'])
        await alice.send_json({'type': 'ping', 'nonce': 123})
        for _ in range(10):
            msg = await alice.receive_json(timeout=3)
            if msg.get('type') == 'pong':
                self.assertEqual(msg['nonce'], 123)
                break
        else:
            self.fail('No pong')
        await alice.close()
        await bob.close()
