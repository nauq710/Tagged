/** Browser scenario console with a shared Run ID and server tick barrier. */
import { ScenarioDataTransport, type ScenarioAction } from '../network/adapter';
import type { GameUI } from './game';
type Script = {version: 1; name: string; room: string; ticks: number; events: ScenarioAction[]};
type SimMessage = Record<string, unknown>;

export class BrowserSimulator {
  private socket: WebSocket | null = null;
  private script: Script | null = null;
  private actor = '';
  private runId = '';
  private registered = false;
  private finished = false;
  private fileInput: HTMLInputElement;
  private actorSelect: HTMLSelectElement;
  private runInput: HTMLInputElement;
  private status: HTMLElement;
  private output: HTMLElement;
  private readyButton: HTMLButtonElement;
  private resultLink: HTMLAnchorElement;
  private resultUrl: string | null = null;
  private ui: GameUI;
  private data: ScenarioDataTransport;
  private modeSelect: HTMLSelectElement;

  constructor(ui: GameUI, mount: HTMLElement) {
    this.ui = ui;
    this.data = new ScenarioDataTransport({
      onWelcome: (welcome) => {
        this.ui.setPlayerId(welcome.id);
        this.ui.setRoom(welcome.room);
        this.ui.setWorldSize(welcome.width, welcome.height);
      },
      onSnapshot: (snapshot) => this.ui.update(snapshot),
      onError: (error) => this.setStatus('Gameplay transport: ' + error),
    });
    const shell = mount.querySelector('.shell');
    if (!shell) throw new Error('Missing game shell');
    const panel = document.createElement('section');
    panel.className = 'panel simulator';
    panel.id = 'simulator-panel';
    panel.innerHTML = `
      <h2>Browser Scenario Mode</h2>
      <p>Upload the same JSON, choose distinct players and a shared Run ID. All browsers Ready together. Correctness mode waits for game-transport acknowledgements; real-time mode runs at fixed 20 Hz without waiting.</p>
      <div class="sim-grid">
        <label>Scenario JSON<input id="sim-file" type="file" accept=".json,application/json"></label>
        <label>Shared Run ID<input id="sim-run" value="class-test-01" maxlength="32"></label>
        <label>This browser controls<select id="sim-actor"><option value="">Load a scenario first</option></select></label>
        <label>Scenario name<div id="sim-name" class="stats">—</div></label>
        <label>Execution mode<select id="sim-mode"><option value="lockstep">Correctness — lockstep</option><option value="realtime">Networking — real time</option></select></label>
      </div>
      <div class="sim-controls">
        <button id="sim-connect">Connect to test lobby</button>
        <button id="sim-ready" class="secondary" disabled>Ready</button>
        <span id="sim-status" role="status">Upload a scenario to begin.</span>
        <a id="sim-download" hidden>Download result JSON</a>
      </div>
      <div class="sim-samples">Sample input:
        <a href="/samples/two_player_finish.input.json" download>Two-player finish</a>
        <a href="/samples/late_join_finish.input.json" download>Late join</a>
        <a href="/samples/duplicate_input_finish.input.json" download>Duplicate/stale actions</a>
        <a href="/samples/credit_cloak_finish.input.json" download>Credit + cloak</a>
      </div>
      <pre id="sim-output" class="sim-console" data-testid="sim-output" aria-live="polite">No test results yet.</pre>
    `;
    shell.append(panel);
    this.fileInput = panel.querySelector('#sim-file')!;
    this.actorSelect = panel.querySelector('#sim-actor')!;
    this.runInput = panel.querySelector('#sim-run')!;
    this.modeSelect = panel.querySelector('#sim-mode')!;
    this.status = panel.querySelector('#sim-status')!;
    this.output = panel.querySelector('#sim-output')!;
    this.readyButton = panel.querySelector('#sim-ready')!;
    this.resultLink = panel.querySelector('#sim-download')!;
    this.fileInput.addEventListener('change', () => void this.loadFile());
    panel.querySelector('#sim-connect')!.addEventListener('click', () => this.connect());
    this.readyButton.addEventListener('click', () => this.ready());
  }

  private async loadFile(): Promise<void> {
    try {
      const file = this.fileInput.files?.[0];
      if (!file) return;
      if (file.size > 120_000) throw new Error('Scenario too large (maximum 120 KB)');
      const object: unknown = JSON.parse(await file.text());
      if (!object || typeof object !== 'object') throw new Error('Invalid scenario object');
      const script = object as Script;
      if (script.version !== 1 || !Array.isArray(script.events) || !Number.isInteger(script.ticks)) {
        throw new Error('Scenario must include version=1, ticks and events[]');
      }
      const players = [...new Set(script.events.filter(e => e.op === 'join').map(e => e.player))];
      if (players.length < 2) throw new Error('Scenario requires at least two player slots');
      this.script = script;
      this.actorSelect.replaceChildren(...players.map(player => {
        const option = document.createElement('option');
        option.value = player; option.textContent = player; return option;
      }));
      (document.getElementById('sim-name')!).textContent = script.name;
      this.setStatus('Loaded. Use the same JSON and Run ID in all browsers.');
      this.output.textContent = JSON.stringify({
        scenario: script.name, players, ticks: script.ticks, actions: script.events.length,
      }, null, 2);
    } catch (err) {
      this.script = null;
      this.setStatus(err instanceof Error ? err.message : 'Unable to parse file');
    }
  }
  private setStatus(status: string): void { this.status.textContent = status; }

  private connect(): void {
    if (!this.script) { this.setStatus('Load a scenario first.'); return; }
    const runId = this.runInput.value.trim();
    if (!/^[A-Za-z0-9_-]{3,32}$/.test(runId)) {
      this.setStatus('Run ID must contain 3–32 letters, digits, _ or -.'); return;
    }
    const actor = this.actorSelect.value;
    if (!actor) { this.setStatus('Choose a player slot.'); return; }
    this.socket?.close();
    this.data.close();
    this.finished = false; this.registered = false;
    this.actor = actor; this.runId = runId;
    this.readyButton.disabled = true; this.resultLink.hidden = true;
    if (this.resultUrl) URL.revokeObjectURL(this.resultUrl);
    this.resultUrl = null;
    this.ui.setPlayerId(actor);
    this.ui.setRoom(this.script.room);
    this.ui.setWorldSize(960, 600);
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(scheme + '//' + location.host + '/sim/ws');
    this.socket = ws;
    this.setStatus('Connecting to synchronized test lobby...');
    ws.addEventListener('open', () => ws.send(JSON.stringify({
      type: 'sim_register', run_id: runId, player: actor, scenario: this.script,
      mode: this.modeSelect.value,
    })));
    ws.addEventListener('message', (event: MessageEvent<string>) => {
      try { this.handle(JSON.parse(event.data) as SimMessage); }
      catch (error) { this.setStatus('Invalid simulator response: ' + String(error)); }
    });
    ws.addEventListener('close', () => {
      this.readyButton.disabled = true;
      if (!this.finished && this.socket === ws) this.setStatus('Simulator connection closed.');
    });
    ws.addEventListener('error', () => this.setStatus('Simulator connection error.'));
  }

  private ready(): void {
    if (!this.registered || this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'sim_ready' }));
    this.readyButton.disabled = true;
    this.setStatus('Ready. Waiting for every scripted player.');
  }
  private handle(message: SimMessage): void {
    const kind = message.type;
    if (kind === 'sim_registered') {
      this.registered = true;
      this.readyButton.disabled = false;
      this.setStatus('Registered. Click Ready.');
    } else if (kind === 'sim_lobby') {
      const total = Array.isArray(message.players) ? message.players.length : '?';
      const ready = Array.isArray(message.ready) ? message.ready.length : '?';
      this.setStatus('Lobby: ' + String(ready) + '/' + String(total) + ' ready.');
    } else if (kind === 'sim_started') {
      this.readyButton.disabled = true;
      this.setStatus('All ready. Server-led simulation starting.');
    } else if (kind === 'sim_tick') {
      const tick = message.tick;
      if (typeof tick !== 'number' || !Number.isInteger(tick) || !this.script) return;
      const actions = this.script.events.filter(e => e.tick === tick && e.player === this.actor);
      void this.data.sendBatch(this.runId, this.actor, this.script.room, tick, actions)
        .then(() => this.socket?.send(JSON.stringify({
          type: 'sim_actions', tick, count: actions.length, run_id: this.runId,
        })))
        .catch((error) => this.setStatus('Data-plane action failed: ' + String(error)));
      this.setStatus('Executing tick ' + String(tick) + ' via game transport');
    } else if (kind === 'sim_result') {
      this.finished = true;
      this.data.close();
      const report = message.report;
      this.output.textContent = JSON.stringify(report, null, 2);
      const verdict = (report as {verdict?: string} | null)?.verdict;
      this.setStatus(verdict === 'PASS'
        ? 'PASS — final outcome matches the oracle.'
        : 'FAIL — inspect the final result and differences.');
      if (this.resultUrl) URL.revokeObjectURL(this.resultUrl);
      this.resultUrl = URL.createObjectURL(new Blob([
        JSON.stringify(report, null, 2) + '\n',
      ], {type: 'application/json'}));
      this.resultLink.href = this.resultUrl;
      this.resultLink.download = this.runId + '.result.json';
      this.resultLink.hidden = false;
      this.readyButton.disabled = true;
    } else if (kind === 'sim_error') {
      this.setStatus('Simulator error: ' + String(message.message));
      this.output.textContent = String(message.message);
    }
  }
}
