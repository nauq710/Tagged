/** STUDENT-EDITABLE: visuals, labels, layout, animations and themes. */
import type { GameEvent, Snapshot } from '../core/contracts';

type JoinHandler = (name: string, room: string) => void;

export class GameUI {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private status: HTMLElement;
  private metrics: HTMLElement;
  private scoreboard: HTMLElement;
  private feed: HTMLElement;
  private roomLabel: HTMLElement;
  private nameInput: HTMLInputElement;
  private roomInput: HTMLInputElement;
  private keys = new Set<string>();
  private pendingCloak = false;
  private snapshot: Snapshot | null = null;
  private ownId = '';
  private width = 960;
  private height = 600;
  private rtt = 0;
  private seenEvents = new Set<number>();

  constructor(mount: HTMLElement) {
    mount.innerHTML = `
      <div class="shell">
        <header class="topbar"><div><span class="eyebrow">COMPUTER NETWORKS · ASSIGNMENT 1</span>
          <h1>Tag, You're Lagged<span class="accent">!</span></h1>
          <p>Move. Collect. Survive. Design the network.</p></div>
          <div class="signal"><span class="signal-dot"></span><span id="status">Not connected</span></div>
        </header>
        <section class="toolbar">
          <label>Player name<input id="player-name" maxlength="18" value="Player" autocomplete="off" /></label>
          <label>Room<input id="room-name" maxlength="20" value="main" autocomplete="off" /></label>
          <button id="join-btn">Create / Join</button><button id="rejoin-btn" class="secondary">Rejoin</button><button id="leave-btn" class="secondary">Leave</button>
          <div class="stats" id="metrics">RTT — · Tick —</div>
        </section>
        <div class="main-grid">
          <div class="game-column">
            <div class="arena"><canvas id="arena" width="960" height="600" aria-label="Game arena"></canvas>
              <div class="arena-corner">ROOM <span id="room-label">—</span></div></div>
            <div class="hint"><strong>WASD / ARROW KEYS</strong> Move <i>·</i> <strong>SPACE</strong> Cloak for 3s (5 credits) <i>·</i> Collect orbs and outgrow rivals</div>
          </div>
          <aside><section class="panel"><h2>Players</h2><div id="scoreboard" class="scores"><p class="empty">Join a room to play.</p></div></section>
          <section class="panel"><h2>Game events</h2><div id="feed" class="feed"><p class="empty">Events will appear here.</p></div></section>
          <section class="panel"><h2>Network lab</h2><p>Baseline: JSON messages over WebSocket.</p><p class="muted">Edit the transport and protocol implementation to compare other networking strategies.</p></section></aside>
        </div>
      </div>`;
    this.canvas = mount.querySelector('#arena')!;
    this.ctx = this.canvas.getContext('2d')!;
    this.status = mount.querySelector('#status')!;
    this.metrics = mount.querySelector('#metrics')!;
    this.scoreboard = mount.querySelector('#scoreboard')!;
    this.feed = mount.querySelector('#feed')!;
    this.roomLabel = mount.querySelector('#room-label')!;
    this.nameInput = mount.querySelector('#player-name')!;
    this.roomInput = mount.querySelector('#room-name')!;
    document.addEventListener('keydown', e => {
      if (e.target instanceof HTMLInputElement) return;
      const key = e.key.toLowerCase();
      if (['arrowup','arrowdown','arrowleft','arrowright',' '].includes(key)) e.preventDefault();
      this.keys.add(key);
      if (key === ' ' && !e.repeat) this.pendingCloak = true;
    });
    document.addEventListener('keyup', e => this.keys.delete(e.key.toLowerCase()));
    window.addEventListener('blur', () => this.keys.clear());
  }
  onJoin(fn: JoinHandler): void {
    document.getElementById('join-btn')!.addEventListener('click', () => fn(this.nameInput.value.trim() || 'Player', this.roomInput.value.trim() || 'main'));
  }
  onRejoin(fn: () => void): void { document.getElementById('rejoin-btn')!.addEventListener('click', fn); }
  onLeave(fn: () => void): void { document.getElementById('leave-btn')!.addEventListener('click', fn); }
  setWorldSize(width: number, height: number): void { this.width = width; this.height = height; }
  setPlayerId(id: string): void { this.ownId = id; this.seenEvents.clear(); this.snapshot = null; }
  setRoom(room: string): void { this.roomLabel.textContent = room; }
  setStatus(status: string): void { this.status.textContent = status; }
  setRtt(value: number): void { this.rtt = value; this.updateStats(); }
  readInput(): { dx: number; dy: number; cloak: boolean } {
    const on = (...names: string[]) => names.some(n => this.keys.has(n));
    const dx = Number(on('d','arrowright')) - Number(on('a','arrowleft'));
    const dy = Number(on('s','arrowdown')) - Number(on('w','arrowup'));
    const cloak = this.pendingCloak;
    this.pendingCloak = false;
    // Only four cardinal directions (no diagonal).
    return { dx: dx !== 0 ? dx : 0, dy: dx !== 0 ? 0 : dy, cloak };
  }
  update(snapshot: Snapshot): void {
    this.snapshot = snapshot;
    this.updateStats();
    this.updateScoreboard();
    this.updateFeed(snapshot.events);
    if (snapshot.phase === 'waiting') this.setStatus('Waiting for at least two players...');
    else if (snapshot.phase === 'finished') this.setStatus(snapshot.winner === this.ownId ? 'You win!' : 'Round finished — rejoin to play again');
    else if (snapshot.players.find(p => p.id === this.ownId)?.alive === false) this.setStatus('Eliminated — click Rejoin');
    else this.setStatus(`Round ${snapshot.round} running`);
  }
  private updateStats(): void {
    this.metrics.textContent = `App RTT ${this.rtt ? this.rtt.toFixed(0) + ' ms' : '—'}  ·  Tick ${this.snapshot?.tick ?? '—'}  ·  Players ${this.snapshot?.players.length ?? 0}`;
  }
  private updateScoreboard(): void {
    const players = [...(this.snapshot?.players ?? [])].sort((a,b) => b.credits-a.credits);
    this.scoreboard.replaceChildren(...players.map((player,i) => {
      const entry = document.createElement('div');
      entry.className = `score-row ${player.id === this.ownId ? 'mine' : ''}`;
      const index = document.createElement('span'); index.textContent = `#${i+1}`;
      const name = document.createElement('span'); name.textContent = player.name;
      const score = document.createElement('strong'); score.textContent = `${player.credits}`;
      entry.append(index,name,score);
      return entry;
    }));
  }
  private updateFeed(events: GameEvent[]): void {
    const players = new Map(this.snapshot?.players.map(p => [p.id, p.name]) ?? []);
    for (const event of events) {
      if (this.seenEvents.has(event.id)) continue;
      this.seenEvents.add(event.id);
      const line = document.createElement('p');
      const actor = players.get(event.actor ?? '') ?? 'A player';
      line.textContent = event.type === 'collect'
        ? `${actor} collected ${event.tier} (+${event.value})`
        : event.type === 'kill' ? `${actor} eliminated ${players.get(event.target ?? '') ?? 'a player'}`
        : event.type === 'cloak' ? `${actor} activated cloak`
        : event.type === 'start' ? `Round ${event.round} started`
        : event.type === 'finish' ? 'Round finished'
        : `${event.type}: ${actor}`;
      this.feed.prepend(line);
    }
    while (this.feed.children.length > 7) this.feed.lastElementChild?.remove();
    if (this.seenEvents.size > 1000) this.seenEvents.clear();
  }
  start(): void { const render = () => { this.draw(); requestAnimationFrame(render); }; requestAnimationFrame(render); }
  private draw(): void {
    const ctx = this.ctx, w = this.canvas.width, h = this.canvas.height;
    ctx.clearRect(0,0,w,h);
    ctx.fillStyle = '#111c2c'; ctx.fillRect(0,0,w,h);
    ctx.strokeStyle = '#203249'; ctx.lineWidth = 1;
    for (let x=0;x<w;x+=40) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,h); ctx.stroke(); }
    for (let y=0;y<h;y+=40) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }
    if (!this.snapshot) {
      ctx.fillStyle = '#a4b5ce'; ctx.font = '600 22px system-ui'; ctx.textAlign='center';
      ctx.fillText('JOIN A ROOM TO PLAY',w/2,h/2); ctx.textAlign='left'; return;
    }
    const sx=w/this.width, sy=h/this.height;
    for (const item of this.snapshot.items) {
      const x=item.x*sx,y=item.y*sy;
      ctx.beginPath(); ctx.arc(x,y,item.radius+7,0,Math.PI*2); ctx.fillStyle='#e9bc5122';ctx.fill();
      ctx.beginPath(); ctx.arc(x,y,item.radius,0,Math.PI*2); ctx.fillStyle= item.tier === 'large' ? '#f59e70' : item.tier === 'medium' ? '#f2b957' : '#fce6a0'; ctx.fill();
    }
    for (const player of this.snapshot.players) {
      if (!player.alive) continue;
      const x=player.x*sx,y=player.y*sy;
      ctx.beginPath();ctx.arc(x,y,player.radius*sx,0,2*Math.PI);
      ctx.fillStyle=player.invisible ? '#ba9aff' : player.id===this.ownId?'#43dcb3':'#63a5f3';ctx.fill();
      ctx.lineWidth=3;ctx.strokeStyle=player.id===this.ownId?'#e3fff4':'#c4dcff';ctx.stroke();
      ctx.fillStyle='#101c28';ctx.beginPath();ctx.arc(x-5,y-2,2.5,0,2*Math.PI);ctx.arc(x+5,y-2,2.5,0,2*Math.PI);ctx.fill();
      ctx.font='600 13px system-ui';ctx.textAlign='center';ctx.fillStyle='#eaf2ff';ctx.fillText(player.name,x,y-27);ctx.textAlign='left';
    }
  }
}
