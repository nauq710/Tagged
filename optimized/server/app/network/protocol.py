"""Student-editable baseline JSON message encoding and input decoding."""
import json

def decode_message(raw: str) -> dict | None:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None

def encode_message(obj: dict) -> str:
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False)

def parse_input(data: dict) -> tuple[int, int, int, bool] | None:
    seq, dx, dy, cloak = (data.get(key) for key in ('seq', 'dx', 'dy', 'cloak'))
    if not isinstance(seq, int) or isinstance(seq, bool) or not 0 <= seq <= 2**53:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and v in (-1, 0, 1) for v in (dx, dy)):
        return None
    if abs(dx) + abs(dy) > 1 or not isinstance(cloak, bool):
        return None
    return seq, dx, dy, cloak

def encode_delta(prev: dict, curr: dict) -> str:
    """Send only changed fields. Falls back to full snapshot if >85% of full size."""
    delta: dict = {'type': 'delta', 'tick': curr['tick']}
    # Always include phase, round, winner if changed
    for key in ('phase', 'round', 'winner'):
        if curr.get(key) != prev.get(key):
            delta[key] = curr[key]
    # Players: only send changed ones (by id)
    prev_players = {p['id']: p for p in prev.get('players', [])}
    curr_players = {p['id']: p for p in curr.get('players', [])}
    changed_players = [p for pid, p in curr_players.items() if p != prev_players.get(pid)]
    removed_players = [pid for pid in prev_players if pid not in curr_players]
    if changed_players or removed_players:
        delta['players'] = changed_players
        if removed_players:
            delta['removed_players'] = removed_players
    # Items: only send if positions changed (items respawn)
    prev_items = {i['id']: i for i in prev.get('items', [])}
    curr_items = {i['id']: i for i in curr.get('items', [])}
    changed_items = [i for iid, i in curr_items.items() if i != prev_items.get(iid)]
    if changed_items:
        delta['items'] = changed_items
    # Events: always send new events
    prev_event_ids = {e['id'] for e in prev.get('events', [])}
    new_events = [e for e in curr.get('events', []) if e['id'] not in prev_event_ids]
    if new_events:
        delta['events'] = new_events
    # If delta is barely smaller than full, just send full
    delta_size = len(json.dumps(delta))
    full_size = len(json.dumps(curr))
    if delta_size > full_size * 0.85:
        return encode_message(curr)
    return json.dumps(delta, separators=(',', ':'), ensure_ascii=False)
