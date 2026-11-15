"""Browser lockstep protocol tests with multiple independent WebSocket clients."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import unittest

from aiohttp.test_utils import AioHTTPTestCase
from app.main import create_app
from app.simulator.contract import (
    validate_scenario, replay_oracle, scenario_digest, result_report,
)

ROOT = Path(__file__).resolve().parents[2] / 'scenarios' / 'browser'


def fixture(name: str) -> dict:
    return json.loads((ROOT / (name + '.input.json')).read_text())


class ScenarioContractTests(unittest.TestCase):
    def test_sample_inputs_are_valid_terminal_scenarios(self):
        for name in ('two_player_finish', 'late_join_finish', 'duplicate_input_finish', 'credit_cloak_finish'):
            with self.subTest(name=name):
                script, slots = validate_scenario(fixture(name))
                self.assertGreaterEqual(len(slots), 2)
                expected = replay_oracle(script)
                self.assertIsNotNone(expected)
                self.assertEqual(expected['phase'], 'finished')

    def test_reject_invalid_ticks_diagonal_and_player(self):
        data = fixture('two_player_finish')
        data['events'][2]['dx'] = 1
        data['events'][2]['dy'] = 1
        with self.assertRaisesRegex(ValueError, 'invalid input'):
            validate_scenario(data)
        data = fixture('two_player_finish')
        data['events'][2]['tick'] = -1
        with self.assertRaisesRegex(ValueError, 'tick'):
            validate_scenario(data)

    def test_expected_vs_actual_verdict(self):
        script, _ = validate_scenario(fixture('two_player_finish'))
        correct = replay_oracle(script)
        report = result_report(script, correct, run_id='test-123',
                               elapsed_seconds=1.0, responses=5, timeout_count=0)
        self.assertEqual(report['verdict'], 'PASS')
        self.assertEqual(report['oracle_source'], 'pinned_fixture')
        incorrect = {**correct, 'winner': 'intruder'}
        report = result_report(script, incorrect, run_id='test-123',
                               elapsed_seconds=1.0, responses=5, timeout_count=0)
        self.assertEqual(report['verdict'], 'FAIL')
        self.assertNotEqual(report['actual'], report['expected'])


class BrowserSynchronizationTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def run_scenario(self, name: str, mode='lockstep'):
        scenario, players = validate_scenario(fixture(name))
        run_id = 'itest-' + name[:16] + '-' + mode
        control = {actor: await self.client.ws_connect('/sim/ws') for actor in players}
        data_sockets = []
        try:
            for actor, ws in control.items():
                await ws.send_json({
                    'type': 'sim_register', 'run_id': run_id,
                    'player': actor, 'scenario': scenario, 'mode': mode,
                })
            for actor in players:
                while True:
                    msg = await control[actor].receive_json(timeout=3)
                    if msg['type'] == 'sim_registered':
                        self.assertEqual(msg['scenario_sha256'], scenario_digest(scenario))
                        break
            await control[players[0]].send_json({'type': 'sim_ready'})
            await asyncio.sleep(.05)
            self.assertEqual(self.app['simulator'].runs[run_id].state, 'lobby')
            for actor in players[1:]:
                await control[actor].send_json({'type': 'sim_ready'})

            async def player_task(actor: str):
                game = None
                started = False
                async for packet in control[actor]:
                    if packet.type.name != 'TEXT':
                        break
                    msg = json.loads(packet.data)
                    if msg['type'] == 'sim_started':
                        started = True
                    elif msg['type'] == 'sim_tick':
                        tick = msg['tick']
                        actions = [e for e in scenario['events']
                                   if e['tick'] == tick and e['player'] == actor]
                        for index, action in enumerate(actions):
                            if game is None:
                                game = await self.client.ws_connect('/ws')
                                data_sockets.append(game)
                            outgoing = {
                                'type': action['op'], 'sim_run': run_id,
                                'sim_actor': actor, 'sim_tick': tick,
                                'sim_index': index,
                            }
                            outgoing.update({k: v for k, v in action.items()
                                             if k in ('name','seq','dx','dy','cloak')})
                            if action['op'] == 'join':
                                outgoing['room'] = scenario['room']
                            await game.send_json(outgoing)
                            while True:
                                response = await game.receive_json(timeout=5)
                                if response['type'] == 'error':
                                    self.fail('Game transport rejected action: ' + str(response))
                                if response['type'] == 'sim_game_ack':
                                    self.assertEqual((response['tick'], response['index']),
                                                     (tick, index))
                                    break
                        await control[actor].send_json({
                            'type': 'sim_actions', 'tick': tick,
                            'count': len(actions),
                        })
                    elif msg['type'] == 'sim_error':
                        self.fail('Unexpected control error: ' + str(msg))
                    elif msg['type'] == 'sim_result':
                        self.assertTrue(started)
                        return msg['report']
                self.fail('Scenario control channel ended without a result')

            reports = await asyncio.wait_for(
                asyncio.gather(*(player_task(a) for a in players)),
                timeout=35,
            )
            for report in reports:
                self.assertEqual(report['verdict'], 'PASS', report['differences'])
                self.assertEqual(report['actual'], report['expected'])
                self.assertEqual(report['oracle_source'], 'pinned_fixture')
                self.assertEqual(report['stats']['timeouts'], 0)
                self.assertGreater(report['stats']['data_actions_confirmed'], 0)
                self.assertEqual(report['mode'], mode)
        finally:
            await asyncio.gather(*(ws.close() for ws in data_sockets))
            await asyncio.gather(*(ws.close() for ws in control.values()))


    async def test_two_browser_tabs_synchronize_and_match(self):
        await self.run_scenario('two_player_finish')

    async def test_late_join_three_browsers(self):
        await self.run_scenario('late_join_finish')

    async def test_credit_collection_and_cloak(self):
        await self.run_scenario('credit_cloak_finish')

    async def test_real_time_mode_uses_actual_game_transport(self):
        await self.run_scenario('two_player_finish', mode='realtime')

    async def test_duplicate_stale_input(self):
        await self.run_scenario('duplicate_input_finish')

    async def test_control_channel_cannot_forge_gameplay_actions(self):
        scenario, players = validate_scenario(fixture('two_player_finish'))
        control = {p: await self.client.ws_connect('/sim/ws') for p in players}
        try:
            for actor, ws in control.items():
                await ws.send_json({'type': 'sim_register', 'run_id': 'no-bypass-test',
                                    'player': actor, 'scenario': scenario})
                while True:
                    event = await ws.receive_json(timeout=3)
                    if event['type'] == 'sim_registered':
                        break
            for ws in control.values():
                await ws.send_json({'type': 'sim_ready'})
            alice = control['alice']
            while True:
                event = await alice.receive_json(timeout=4)
                if event['type'] == 'sim_tick':
                    tick = event['tick']
                    actions = [e for e in scenario['events']
                               if e['tick'] == tick and e['player'] == 'alice']
                    self.assertEqual(tick, 0)
                    # Try to fake successful gameplay with only the control socket:
                    await alice.send_json({'type': 'sim_actions', 'tick': tick,
                                           'count': len(actions)})
                    break
            while True:
                msg = await alice.receive_json(timeout=3)
                if msg['type'] == 'sim_error':
                    self.assertIn('Game transport did not confirm', msg['message'])
                    break
        finally:
            await asyncio.gather(*(ws.close() for ws in control.values()))

    async def test_reject_different_scenario_for_same_run(self):
        initial, slots = validate_scenario(fixture('two_player_finish'))
        altered, _ = validate_scenario(fixture('two_player_finish'))
        altered['name'] = 'altered-test'
        first = await self.client.ws_connect('/sim/ws')
        second = await self.client.ws_connect('/sim/ws')
        try:
            await first.send_json({'type':'sim_register','run_id':'collision-test',
                                   'player':slots[0],'scenario':initial})
            self.assertEqual((await first.receive_json(timeout=3))['type'], 'sim_registered')
            await second.send_json({'type':'sim_register','run_id':'collision-test',
                                    'player':slots[1],'scenario':altered})
            resp = await second.receive_json(timeout=3)
            self.assertEqual(resp['type'], 'sim_error')
            self.assertIn('differs', resp['message'])
        finally:
            await first.close()
            await second.close()
