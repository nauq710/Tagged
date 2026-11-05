/** STUDENT-EDITABLE application entrypoint. Preserve game behavior. */
import type { Snapshot, Welcome } from './core/contracts';
import { ClientTransport } from './network/adapter';
import { GameUI } from './ui/game';
import { BrowserSimulator } from './ui/simulator';
import './ui/style.css';

const mount = document.getElementById('app')!;
const ui = new GameUI(mount);
new BrowserSimulator(ui, mount);
let playerId = '';
let seq = 0;
let connected = false;
let mostRecentTick = -1;

const network = new ClientTransport({
  onWelcome(message: Welcome) {
    playerId = message.id;
    seq = 0;
    mostRecentTick = -1;
    connected = true;
    ui.setWorldSize(message.width, message.height);
    ui.setPlayerId(playerId);
    ui.setRoom(message.room);
  },
  onSnapshot(snapshot: Snapshot) {
    if (snapshot.tick < mostRecentTick) return;
    mostRecentTick = snapshot.tick;
    ui.update(snapshot);
  },
  onPong(rttMs) { ui.setRtt(rttMs); },
  onStatus(status) {
    if (status.startsWith('Disconnected') || status === 'Connection error') {
      connected = false;
    }
    ui.setStatus(status);
  },
});

ui.onJoin((name, room) => { connected = false; network.connect({ name, room }); });
ui.onLeave(() => { network.disconnect(); connected = false; ui.setStatus('Left game'); });
ui.onRejoin(() => network.rejoin());

// Application generates player intent at a fixed rate; transport may decide
// how to encode, aggregate and transmit it. Do not change the game rules.
window.setInterval(() => {
  if (!connected) return;
  const { dx, dy, cloak } = ui.readInput();
  network.sendInput({ seq: ++seq, dx, dy, cloak });
}, 100);
ui.start();
