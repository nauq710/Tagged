/** STUDENT-EDITABLE: WebSocket is an example, not a mandated solution.
 * You may implement polling, long polling, or another transport here while
 * preserving the public ClientTransport interface in main.ts.
 */
import type { Action, ConnectionOptions, NetworkHooks, Welcome, Snapshot } from '../core/contracts';
import { decodeServerMessage, encodeInput, applyDelta } from './protocol';

export class ClientTransport {
  private socket: WebSocket | null = null;
  private probe: number | undefined;
  private hooks: NetworkHooks;
  private lastSnapshot: Snapshot | null = null;

  constructor(hooks: NetworkHooks) { this.hooks = hooks; }

  connect({ name, room }: ConnectionOptions): void {
    this.disconnect();
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${scheme}//${location.host}/ws`;
    const socket = new WebSocket(url);
    this.socket = socket;
    this.hooks.onStatus('Connecting...');
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'join', name, room, delta: true }));
      this.hooks.onStatus('Connected');
      this.probe = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping', nonce: Math.round(performance.now()) }));
        }
      }, 2000);
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      const raw: unknown = (() => { try { return JSON.parse(event.data); } catch { return null; } })();
      if (raw === null || typeof raw !== 'object') return;
      const record = raw as Record<string, unknown>;
      if (record.type === 'delta') {
        if (this.lastSnapshot) {
          const updated = applyDelta(this.lastSnapshot, record);
          this.lastSnapshot = updated;
          this.hooks.onSnapshot(updated);
        }
        return;
      }
      const msg = decodeServerMessage(event.data);
      if (!msg) return;
      if (msg.type === 'welcome') this.hooks.onWelcome(msg);
      if (msg.type === 'snapshot') { this.lastSnapshot = msg; this.hooks.onSnapshot(msg); }
      if (msg.type === 'pong') this.hooks.onPong(Math.max(0, performance.now() - msg.nonce));
      if (msg.type === 'error') this.hooks.onStatus(`Server error: ${msg.message}`);
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.clearProbe();
      this.hooks.onStatus('Disconnected. Click Join to reconnect.');
    };
    socket.onerror = () => this.hooks.onStatus('Connection error');
  }

  sendInput(action: Action): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(encodeInput(action));
  }

  rejoin(): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'rejoin' }));
  }
  disconnect(): void {
    this.clearProbe();
    const previous = this.socket;
    this.socket = null;
    previous?.close();
  }

  private clearProbe(): void {
    if (this.probe !== undefined) window.clearInterval(this.probe);
    this.probe = undefined;
  }
}


/** Network adapter for browser scenario players.
 * Unlike the /sim/ws control channel, this uses the real gameplay endpoint.
 * Teams changing transport must adapt this as well as ClientTransport.
 */
export type ScenarioAction = {
  tick: number; op: 'join'|'leave'|'rejoin'|'input'; player: string;
  name?: string; seq?: number; dx?: number; dy?: number; cloak?: boolean;
};
export class ScenarioDataTransport {
  private socket: WebSocket | null = null;
  private opening: Promise<void> | null = null;
  private awaiting = new Map<string, {resolve: () => void; reject: (reason: Error) => void}>();
  private queue: Promise<void> = Promise.resolve();
  private lastSnapshot: Snapshot | null = null;
  constructor(private hooks: {
    onWelcome: (message: Welcome) => void;
    onSnapshot: (message: Snapshot) => void;
    onError: (message: string) => void;
  }) {}

  private ensureSocket(): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) return Promise.resolve();
    if (this.opening) return this.opening;
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(scheme + '//' + location.host + '/ws');
    this.socket = ws;
    this.opening = new Promise<void>((resolve, reject) => {
      const fail = () => reject(new Error('Gameplay network connection failed'));
      ws.addEventListener('open', () => resolve(), {once: true});
      ws.addEventListener('error', fail, {once: true});
    }).finally(() => { this.opening = null; });
    ws.addEventListener('message', (event: MessageEvent<string>) => {
      try {
        const message = JSON.parse(event.data) as Record<string, unknown>;
        if (message.type === 'welcome') this.hooks.onWelcome(message as unknown as Welcome);
        else if (message.type === 'snapshot') {
          this.lastSnapshot = message as unknown as Snapshot;
          this.hooks.onSnapshot(this.lastSnapshot);
        } else if (message.type === 'delta') {
          if (this.lastSnapshot) {
            const updated = applyDelta(this.lastSnapshot, message);
            this.lastSnapshot = updated;
            this.hooks.onSnapshot(updated);
          }
        } else if (message.type === 'sim_game_ack') {
          const key = String(message.tick) + ':' + String(message.index);
          const pending = this.awaiting.get(key);
          if (pending) { this.awaiting.delete(key); pending.resolve(); }
        } else if (message.type === 'error') {
          const err = new Error(String(message.message));
          this.hooks.onError(err.message);
          for (const [, pending] of this.awaiting) pending.reject(err);
          this.awaiting.clear();
        }
      } catch (err) { this.hooks.onError(String(err)); }
    });
    ws.addEventListener('close', () => {
      this.socket = null;
      for (const [, pending] of this.awaiting) pending.reject(new Error('Gameplay socket closed'));
      this.awaiting.clear();
    });
    return this.opening;
  }

  private async execute(runId: string, actor: string, room: string,
                        tick: number, actions: ScenarioAction[]): Promise<void> {
    if (!actions.length) return;
    await this.ensureSocket();
    for (const [index, action] of actions.entries()) {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN)
        throw new Error('Gameplay transport is disconnected');
      const key = String(tick) + ':' + String(index);
      const payload: Record<string, unknown> = {
        type: action.op, sim_run: runId, sim_actor: actor,
        sim_tick: tick, sim_index: index,
      };
      if (action.op === 'join') {
        payload.name = action.name ?? actor;
        payload.room = room;
      } else if (action.op === 'input') {
        payload.seq = action.seq; payload.dx = action.dx; payload.dy = action.dy;
        payload.cloak = action.cloak ?? false;
      }
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => {
          this.awaiting.delete(key); reject(new Error('Game action ACK timed out at tick ' + tick));
        }, 7000);
        this.awaiting.set(key, {
          resolve: () => { window.clearTimeout(timeout); resolve(); },
          reject: (error) => { window.clearTimeout(timeout); reject(error); },
        });
        this.socket!.send(JSON.stringify(payload));
      });
    }
  }

  sendBatch(runId: string, actor: string, room: string,
            tick: number, actions: ScenarioAction[]): Promise<void> {
    const current = this.queue.then(() => this.execute(runId, actor, room, tick, actions));
    this.queue = current.catch(() => undefined);
    return current;
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }
}
