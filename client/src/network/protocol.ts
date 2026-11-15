/** STUDENT-EDITABLE: baseline JSON message encoding and decoding. */
import type { Action, Snapshot, Welcome } from '../core/contracts';
export type ServerMessage = Welcome | Snapshot | { type: 'pong'; nonce: number } | { type: 'error'; message: string };

export function encodeInput(action: Action): string {
  return JSON.stringify({ type: 'input', ...action });
}
export function decodeServerMessage(raw: string): ServerMessage | null {
  try {
    const data: unknown = JSON.parse(raw);
    if (data === null || typeof data !== 'object' || !('type' in data)) return null;
    const record = data as Record<string, unknown>;
    if (record.type === 'welcome' && typeof record.id === 'string') return record as Welcome;
    if (record.type === 'snapshot' && typeof record.tick === 'number' && Array.isArray(record.players)) return record as Snapshot;
    if (record.type === 'pong' && typeof record.nonce === 'number') return { type: 'pong', nonce: record.nonce };
    if (record.type === 'error' && typeof record.message === 'string') return { type: 'error', message: record.message };
    return null;
  } catch { return null; }
}

/** Merge a delta message onto a full snapshot, returning the updated snapshot. */
export function applyDelta(base: Snapshot, delta: Record<string, unknown>): Snapshot {
  const result: Snapshot = { ...base, tick: delta.tick as number };
  if ('phase' in delta) result.phase = delta.phase as Snapshot['phase'];
  if ('round' in delta) result.round = delta.round as number;
  if ('winner' in delta) result.winner = delta.winner as string | null;

  // Merge players: update/add changed, keep rest
  if ('players' in delta || 'removed_players' in delta) {
    const removedIds = new Set<string>(
      Array.isArray(delta.removed_players) ? (delta.removed_players as string[]) : []
    );
    const changedPlayers = Array.isArray(delta.players)
      ? (delta.players as Snapshot['players'])
      : [];
    const changedById = new Map(changedPlayers.map(p => [p.id, p]));
    const merged = base.players
      .filter(p => !removedIds.has(p.id))
      .map(p => changedById.has(p.id) ? changedById.get(p.id)! : p);
    // Add brand-new players not in base
    for (const p of changedPlayers) {
      if (!base.players.some(bp => bp.id === p.id)) merged.push(p);
    }
    result.players = merged;
  }

  // Merge items: update changed, keep rest
  if ('items' in delta) {
    const changedItems = Array.isArray(delta.items) ? (delta.items as Snapshot['items']) : [];
    const changedById = new Map(changedItems.map(i => [i.id, i]));
    const merged = base.items.map(i => changedById.has(i.id) ? changedById.get(i.id)! : i);
    for (const i of changedItems) {
      if (!base.items.some(bi => bi.id === i.id)) merged.push(i);
    }
    result.items = merged;
  }

  // Append new events
  if ('events' in delta && Array.isArray(delta.events)) {
    result.events = [...base.events, ...(delta.events as Snapshot['events'])];
  }

  return result;
}
