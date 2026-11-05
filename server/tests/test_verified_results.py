"""Independent verification must reject incorrect terminal outcomes and forged PASS."""
import unittest
from tools.verify_result import verify

EXPECTED = {
    'format': 'tag-lagged-expected-v1', 'scenario': 'test-final',
    'scenario_sha256': 'a' * 64,
    'expected': {'phase': 'finished', 'round': 1, 'winner': 'alice',
                 'players': {'alice': {'alive': True, 'credits': 2}}},
}

RESULT = {
    'format': 'tag-lagged-browser-result-v1', 'run_id': 'test-1',
    'scenario': EXPECTED['scenario'], 'scenario_sha256': EXPECTED['scenario_sha256'],
    'expected': EXPECTED['expected'], 'actual': EXPECTED['expected'],
    'verdict': 'PASS', 'stats': {'timeouts': 0},
}

class TrustedOutcomeTests(unittest.TestCase):
    def test_correct_final_result(self):
        self.assertEqual(verify(EXPECTED, RESULT)['verdict'], 'PASS')

    def test_fake_pass_with_wrong_game_state_fails(self):
        modified = {**RESULT, 'actual': {**RESULT['actual'], 'winner': 'bob'}}
        self.assertEqual(verify(EXPECTED, modified)['verdict'], 'FAIL')


    def test_forged_pass_does_not_override_independent_expected(self):
        modified = {**RESULT, 'verdict': 'PASS',
                    'actual': {'phase': 'finished', 'round': 1,
                               'winner': 'bob', 'players': {}}}
        report = verify(EXPECTED, modified)
        self.assertEqual(report['verdict'], 'FAIL')

    def test_wrong_fixture_or_injected_expected_fails(self):
        modified = {**RESULT, 'scenario_sha256': 'b'*64}
        self.assertEqual(verify(EXPECTED, modified)['verdict'], 'FAIL')
        modified = {**RESULT, 'expected': {'phase': 'finished', 'winner': 'bob'}}
        self.assertEqual(verify(EXPECTED, modified)['verdict'], 'FAIL')
