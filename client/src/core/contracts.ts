/** STUDENT-EDITABLE: baseline client state contract. The grading contract is behavioral. */
export type Action = {seq: number; dx: number; dy: number; cloak: boolean};
export type PlayerState = {id: string; name: string; x: number; y: number; credits: number; radius: number; alive: boolean; invisible: boolean};
export type ItemState = {id: number; tier: 'small'|'medium'|'large'; value: number; x: number; y: number; radius: number};
export type GameEvent = {id: number; type: 'join'|'rejoin'|'leave'|'start'|'collect'|'cloak'|'kill'|'finish'; tick: number; actor?: string; target?: string; tier?: string; value?: number; transferred?: number; winner?: string | null; round?: number};
export type Snapshot = {type: 'snapshot'; room: string; tick: number; phase: 'waiting'|'running'|'finished'; round: number; winner: string|null; players: PlayerState[]; items: ItemState[]; events: GameEvent[]};
export type Welcome = {type: 'welcome'; id: string; room: string; width: number; height: number; tick_rate: number; snapshot_rate: number; room_capacity: number};
export type ConnectionOptions = {name: string; room: string};
export type NetworkHooks = {onWelcome(message: Welcome): void; onSnapshot(message: Snapshot): void; onPong(rttMs: number): void; onStatus(status: string): void};
