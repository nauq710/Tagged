#!/usr/bin/env python3
"""Generate/check stable browser scenario .expected.json fixtures."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from app.simulator.contract import validate_scenario, replay_oracle, scenario_digest

DIRECTORY = ROOT / 'scenarios' / 'browser'
PUBLIC = ROOT / 'client' / 'public' / 'samples'


def expected_payload(script: dict) -> dict:
    return {
        'format': 'tag-lagged-expected-v1',
        'scenario': script['name'],
        'scenario_sha256': scenario_digest(script),
        'expected': replay_oracle(script),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--print', action='store_true')
    parser.add_argument('--suggest-credit', action='store_true')
    args = parser.parse_args()
    if args.suggest_credit:
        from app.simulator.contract import make_world
        for seed_index in range(1, 1201):
            room = f'sim-credit-{seed_index}'
            world = make_world({'room': room})
            world.add_player('alice', 'Alice')
            world.add_player('bob', 'Bob')
            world.step()
            if (world.phase == 'running' and world.players['alice'].credits >= 7
                    and world.players['bob'].credits == 0):
                print(f'CREDIT_FIXTURE_ROOM={room} CREDIT={world.players["alice"].credits}')
                return
        raise SystemExit('No qualifying deterministic room seed found')
    failed = False
    for file in sorted(DIRECTORY.glob('*.input.json')):
        script, actors = validate_scenario(json.loads(file.read_text()))
        expected = expected_payload(script)
        if expected['expected'] is None:
            raise SystemExit(f'{file}: scenario must finish a game')
        target = file.with_name(file.name.replace('.input.json', '.expected.json'))
        public_input = PUBLIC / file.name
        public_expected = PUBLIC / target.name
        content = json.dumps(expected, indent=2, ensure_ascii=False) + '\n'
        if args.write:
            target.write_text(content)
            public_expected.write_text(content)
            public_input.write_text(file.read_text())
        if args.check and (
            not target.is_file() or target.read_text() != content
            or not public_input.is_file() or public_input.read_bytes() != file.read_bytes()
            or not public_expected.is_file() or public_expected.read_text() != content
        ):
            print(f'MISMATCH: {file.name} and its expected/public fixture files')
            failed = True
        if args.print:
            print('FIXTURE_START ' + target.name)
            print(content)
            print('FIXTURE_END ' + target.name)
        else:
            print(f'{file.name}: {len(actors)} browser players, expected winner: '
                  f'{expected["expected"]["winner"]}, hash: {expected["scenario_sha256"][:12]}')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
