"""Completed-game outcome is the oracle; intermediate ticks are not."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from aiohttp.test_utils import AioHTTPTestCase
from app.main import create_app
from tools.final_outcome import (
    canonical_terminal_outcome, compare_terminal_outcomes,
    merge_terminal_observations,
)
from tools.scenario_runner import load, live, replay


class OutcomeProjectionTests(unittest.TestCase):
    def test_identical_result_ignores_tick_coordinates_and_events(self):
        a = {'phase': 'finished', 'round': 1, 'winner': 'a', 'tick': 80,
             'players': [{'id': 'a', 'credits': 20, 'alive': True, 'x': 100, 'y': 200},
                         {'id': 'b', 'credits': 3, 'alive': False, 'x': 230, 'y': 300}]}
        b = {'phase': 'finished', 'round': 1, 'winner': 'x7', 'tick': 140,
             'players': [{'id': 'b8', 'credits': 3, 'alive': False, 'x': 5, 'y': 25},
                         {'id': 'x7', 'credits': 20, 'alive': True, 'x': 800, 'y': 600}]}
        expected = canonical_terminal_outcome(a)
        actual = canonical_terminal_outcome(b, {'x7': 'a', 'b8': 'b'})
        self.assertEqual(compare_terminal_outcomes(expected, actual)['status'], 'pass')

    def test_wrong_winner_or_credits_fail(self):
        expected = {'phase': 'finished', 'round': 1, 'winner': 'a',
                    'players': {'a': {'alive': True, 'credits': 10}}}
        incorrect = {'phase': 'finished', 'round': 1, 'winner': 'b',
                     'players': {'a': {'alive': True, 'credits': 9}}}
        report = compare_terminal_outcomes(expected, incorrect)
        self.assertEqual(report['status'], 'fail')
        self.assertTrue(any('winner' in error for error in report['differences']))
        self.assertTrue(any('players' in error for error in report['differences']))

    def test_in_progress_scenario_is_not_graded_as_completed(self):
        expected = canonical_terminal_outcome({'phase': 'running', 'round': 1})
        self.assertIsNone(expected)
        self.assertEqual(compare_terminal_outcomes(expected, None)['status'], 'not_terminal')

    def test_final_projection_merges_invisible_player_views(self):
        alice = {'phase': 'finished', 'round': 1, 'winner': 'a1',
                 'players': [{'id': 'a1', 'credits': 12, 'alive': True},
                             {'id': 'b1', 'credits': 3, 'alive': False}]}
        bob = {'phase': 'finished', 'round': 1, 'winner': 'a1',
               'players': [{'id': 'b1', 'credits': 3, 'alive': False}]}
        actual, errors = merge_terminal_observations(
            {'alice': alice, 'bob': bob}, {'a1': 'alice', 'b1': 'bob'})
        self.assertFalse(errors)
        self.assertEqual(actual['winner'], 'alice')
        self.assertEqual(actual['players']['alice']['credits'], 12)


class LiveTerminalOutcomeTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_scripted_terminal_result_matches_oracle(self):
        root = Path(__file__).resolve().parents[2]
        scenario = load(str(root / 'scenarios' / 'terminal_winner.json'))
        self.assertEqual(replay(scenario)['final_result']['winner'], 'alice')
        args = SimpleNamespace(
            url=str(self.server.make_url('/')).rstrip('/'), seed=123,
            delay_ms=0, jitter_ms=0, drop_rate=0, duplicate_rate=0,
            settle_seconds=0.35,
        )
        observed = await live(scenario, args)
        self.assertEqual(observed['errors'], [])
        self.assertEqual(observed['final_comparison']['status'], 'pass',
                         observed['final_comparison']['differences'])
        self.assertEqual(observed['final_comparison']['observed']['winner'], 'alice')
