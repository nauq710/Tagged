"""Canonical, transport-independent completed-match outcome comparison.

Intermediate server ticks, positions and snapshot arrival times are not compared.
A strict check is only meaningful when the scenario ends a completed round.
"""
from __future__ import annotations
from typing import Any, Mapping


def canonical_terminal_outcome(
    snapshot: Mapping[str, Any] | None,
    ids: Mapping[str, str] | None = None,
) -> dict | None:
    if not snapshot or snapshot.get('phase') != 'finished':
        return None
    ids = ids or {}
    players = {}
    for player in snapshot.get('players', []):
        stable_id = ids.get(player['id'], player['id'])
        players[stable_id] = {
            'alive': bool(player['alive']),
            'credits': int(player['credits']),
        }
    winner_id = snapshot.get('winner')
    return {
        'phase': 'finished',
        'round': int(snapshot['round']),
        'winner': ids.get(winner_id, winner_id) if winner_id is not None else None,
        'players': dict(sorted(players.items())),
    }


def merge_terminal_observations(
    snapshots: Mapping[str, Mapping[str, Any]],
    ids: Mapping[str, str],
) -> tuple[dict | None, list[str]]:
    """Combine final client views; a hidden player is present in its own view.

    The game is stopped once finished, so client reports may have different tick
    numbers but must converge on the same result before the settling deadline.
    """
    errors = []
    outcomes = {}
    for observer, snapshot in snapshots.items():
        outcome = canonical_terminal_outcome(snapshot, ids)
        if outcome is None:
            errors.append(f'{observer}: did not observe a finished round')
        else:
            outcomes[observer] = outcome
    if not outcomes:
        if not snapshots:
            errors.append('No connected client returned a final snapshot')
        return None, errors
    first = next(iter(outcomes.values()))
    merged_players: dict[str, dict] = {}
    for observer, outcome in outcomes.items():
        for field in ('phase', 'round', 'winner'):
            if outcome[field] != first[field]:
                errors.append(f'{observer}: inconsistent final {field}')
        for player_id, score in outcome['players'].items():
            if player_id in merged_players and merged_players[player_id] != score:
                errors.append(f'{observer}: inconsistent final credits/alive for {player_id}')
            merged_players[player_id] = score
    return {
        'phase': first['phase'], 'round': first['round'],
        'winner': first['winner'], 'players': dict(sorted(merged_players.items())),
    }, errors


def compare_terminal_outcomes(
    expected: dict | None,
    observed: dict | None,
    observer_errors: list[str] | None = None,
) -> dict:
    """Compare final game results, not positions or per-tick world states."""
    errors = list(observer_errors or [])
    if expected is None:
        return {
            'status': 'not_terminal',
            'matches_oracle': None,
            'differences': [],
            'expected': None,
            'observed': observed,
        }
    if observed is None:
        errors.append('No completed-game outcome was observed')
    else:
        for field in ('phase', 'round', 'winner', 'players'):
            if observed.get(field) != expected.get(field):
                errors.append(f'{field}: expected {expected.get(field)!r}; got {observed.get(field)!r}')
    return {
        'status': 'pass' if not errors else 'fail',
        'matches_oracle': not errors,
        'differences': errors,
        'expected': expected,
        'observed': observed,
    }
