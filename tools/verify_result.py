#!/usr/bin/env python3
"""Independent terminal-outcome verifier (standard library only).

Use from an instructor-controlled checkout with trusted expected fixture files.
Do not trust the PASS string emitted by an application under test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(expected: dict, result: dict) -> dict:
    issues = []
    if expected.get('format') != 'tag-lagged-expected-v1':
        issues.append('Expected fixture has invalid format')
    if result.get('format') != 'tag-lagged-browser-result-v1':
        issues.append('Result has invalid format')
    if expected.get('scenario') != result.get('scenario'):
        issues.append('Scenario name mismatch')
    if expected.get('scenario_sha256') != result.get('scenario_sha256'):
        issues.append('Scenario hash mismatch')
    canonical = expected.get('expected')
    if not isinstance(canonical, dict) or canonical.get('phase') != 'finished':
        issues.append('Expected fixture has no completed-game outcome')
    if result.get('actual') != canonical:
        issues.append('Actual terminal outcome differs from trusted expected outcome')
    if result.get('expected') != canonical:
        issues.append('Application-embedded expected value differs from trusted fixture')
    if result.get('verdict') != 'PASS':
        issues.append('Application did not report PASS')
    stats = result.get('stats')
    if not isinstance(stats, dict) or stats.get('timeouts') != 0:
        issues.append('Missing statistics or simulator timeouts occurred')
    return {
        'verdict': 'PASS' if not issues else 'FAIL',
        'scenario': expected.get('scenario'),
        'run_id': result.get('run_id'),
        'differences': issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Verify browser result against trusted expected JSON')
    parser.add_argument('--expected', required=True, type=Path)
    parser.add_argument('--result', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text(encoding='utf-8'))
    result = json.loads(args.result.read_text(encoding='utf-8'))
    report = verify(expected, result)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)
    if report['verdict'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
