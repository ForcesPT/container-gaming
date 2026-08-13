// renderer.js — the launcher UI logic (runs in the renderer process).
//
// Builds the store cards from the main-provided store list, handles keyboard
// (arrows/Enter/Esc) AND gamepad (d-pad + A/B) navigation, and requests a
// launch via the dpad.launchStore IPC.
//
// Launch flow (fix #2): the overlay shows immediately on launch and stays
// until the main process sends 'store-visible' (the store window appeared in
// the sway tree). If the store fails to launch, 'store-launch-failed' dismisses
// the overlay + shows a toast. When the store exits, 'store-exited' refocuses
// the launcher.

const grid = document.getElementById('grid');
let cards = [];        // [{ el, store, index }]
let focusIndex = 0;
let launching = false; // true while the launch overlay is up
const overlay = document.getElementById('launchOverlay');
const launchLogo = document.getElementById('launchLogo');
const launchName = document.getElementById('launchName');

// dismiss the launch overlay — called when the main process confirms the
// store window is visible, or on explicit cancel (Esc/B).
function dismissOverlay() {
  if (!launching) return;
  launching = false;
  overlay.classList.remove('show');
}

function showOverlay(store) {
  launching = true;
  launchLogo.src = `logos/${store.id}.svg`;
  launchLogo.alt = store.name;
  launchName.textContent = `Launching ${store.name}…`;
  overlay.classList.add('show');
}

// --- main -> renderer events ---
window.dpad.onStoreVisible((_id) => {
  // The store window appeared — dismiss the overlay. The launcher will be
  // hidden to scratchpad by the main process; when the store exits, the
  // launcher is restored + refocused, and 'store-exited' fires.
  dismissOverlay();
});

window.dpad.onStoreExited((_id) => {
  // The store exited — the launcher is restored from scratchpad. Just make
  // sure the overlay is dismissed.
  dismissOverlay();
  // Re-render in case store availability changed (e.g. a store got installed)
  window.dpad.getStores().then(render);
});

window.dpad.onStoreLaunchFailed((_id, err) => {
  dismissOverlay();
  showToast(`Couldn't launch: ${err}`, true);
});

// --- toast ---
const toast = document.createElement('div');
toast.className = 'toast';
document.body.appendChild(toast);
let toastTimer = null;
function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.classList.toggle('error', isError);
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

function statusPill(store) {
  if (store.comingSoon) return { text: 'Coming soon', cls: 'soon' };
  if (store.available) return { text: 'Available', cls: 'available' };
  return { text: 'Not installed', cls: 'missing' };
}

function render(stores) {
  grid.innerHTML = '';
  cards = [];
  stores.forEach((store, index) => {
    const el = document.createElement('div');
    el.className = 'card';
    el.tabIndex = -1;
    el.style.setProperty('--brand', store.color);
    if (store.comingSoon || !store.available) el.classList.add('disabled');
    const pill = statusPill(store);
    el.innerHTML = `
      <div class="tile"><img class="logo" src="logos/${store.id}.svg" alt="${store.name}" /></div>
      <div class="body">
        <div class="name">${store.name}</div>
        <div class="subtitle">${store.subtitle || ''}</div>
        <div class="status ${pill.cls}">${pill.text}</div>
      </div>`;
    el.addEventListener('click', () => { focus(index); launch(); });
    grid.appendChild(el);
    cards.push({ el, store, index });
  });
  if (cards.length) focus(0);
}

function focus(index) {
  if (!cards.length) return;
  if (index < 0) index = cards.length - 1;
  if (index >= cards.length) index = 0;
  focusIndex = index;
  cards.forEach((c, i) => c.el.classList.toggle('focused', i === index));
  const el = cards[index].el;
  el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function move(dx, dy) {
  const first = cards[0]?.el.getBoundingClientRect();
  const second = cards[1]?.el.getBoundingClientRect();
  const cols = second && Math.abs(second.left - first.left) > 10
    ? cards.filter((c) => Math.abs(c.el.getBoundingClientRect().top - first.top) < first.height / 2).length
    : 1;
  const rows = Math.ceil(cards.length / cols);
  let r = Math.floor(focusIndex / cols);
  let c = focusIndex % cols;
  if (dx) c = (c + dx + cols) % cols;
  if (dy) r = (r + dy + rows) % rows;
  let next = r * cols + c;
  if (next >= cards.length) next = next % cards.length;
  focus(next);
}

async function launch() {
  if (launching) { dismissOverlay(); return; }
  const { store } = cards[focusIndex];
  if (store.comingSoon) { showToast(`${store.name} — coming soon`); return; }
  if (!store.available) { showToast(`${store.name} not installed`, true); return; }
  showOverlay(store);
  const res = await window.dpad.launchStore(store.id);
  if (!res.ok) {
    dismissOverlay();
    showToast(`Couldn't launch ${store.name}: ${res.error}`, true);
  }
  // If ok, the overlay stays until 'store-visible' event from main process.
}

// ---- keyboard ----
window.addEventListener('keydown', (e) => {
  if (launching) {
    if (e.key === 'Escape') dismissOverlay();
    e.preventDefault();
    return;
  }
  switch (e.key) {
    case 'ArrowRight': move(1, 0); e.preventDefault(); break;
    case 'ArrowLeft':  move(-1, 0); e.preventDefault(); break;
    case 'ArrowDown':  move(0, 1); e.preventDefault(); break;
    case 'ArrowUp':    move(0, -1); e.preventDefault(); break;
    case 'Enter':      launch(); e.preventDefault(); break;
    case 'Escape':     window.dpad.quit(); break;
  }
});

// ---- gamepad ----
let lastBtn = {};
async function pollGamepad() {
  let pads = [];
  try { pads = await window.dpad.pollGamepads(); } catch (_) {}
  if (launching) {
    for (const gp of pads) {
      if (!gp) continue;
      const id = gp.index;
      const b = !!gp.buttons[1]?.pressed;
      if (b && !lastBtn[id + 'lb1']) dismissOverlay();
      lastBtn[id + 'lb1'] = b;
    }
    setTimeout(pollGamepad, 50);
    return;
  }
  for (const gp of pads) {
    if (!gp) continue;
    const ax = gp.axes[0] || 0, ay = gp.axes[1] || 0;
    const TH = 0.6;
    const dpadUp = gp.buttons[12]?.pressed, dpadDown = gp.buttons[13]?.pressed;
    const dpadLeft = gp.buttons[14]?.pressed, dpadRight = gp.buttons[15]?.pressed;
    let dx = 0, dy = 0;
    if (Math.abs(ax) > TH) dx = ax > 0 ? 1 : -1;
    if (Math.abs(ay) > TH) dy = ay > 0 ? 1 : -1;
    if (dpadRight) dx = 1; else if (dpadLeft) dx = -1;
    if (dpadDown) dy = 1; else if (dpadUp) dy = -1;
    const id = gp.index;
    const repeat = (axis, key) => {
      if (axis !== 0 && !lastBtn[id + key]) { move(key === 'x' ? axis : 0, key === 'y' ? axis : 0); }
      lastBtn[id + key] = axis !== 0;
    };
    repeat(dx, 'x');
    repeat(dy, 'y');
    if (gp.buttons[0]?.pressed && !lastBtn[id + 'a']) launch();
    if (gp.buttons[1]?.pressed && !lastBtn[id + 'b']) window.dpad.quit();
    lastBtn[id + 'a'] = gp.buttons[0]?.pressed;
    lastBtn[id + 'b'] = gp.buttons[1]?.pressed;
  }
  setTimeout(pollGamepad, 50);
}
pollGamepad();

// ---- boot ----
(async () => {
  const stores = await window.dpad.getStores();
  render(stores);
  window.addEventListener('focus', async () => render(await window.dpad.getStores()));
})();