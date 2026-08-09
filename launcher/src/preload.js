// preload.js — bridges the renderer (index.html) to the main process (main.js)
// via contextBridge. Keeps nodeIntegration off; the renderer only gets the
// three IPC calls it needs. Mirrors the lutris-gamepad-ui security model.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dpad', {
  getStores: () => ipcRenderer.invoke('get-stores'),
  launchStore: (id) => ipcRenderer.invoke('launch-store', id),
  pollGamepads: () => ipcRenderer.invoke('poll-gamepads'),
  quit: () => ipcRenderer.invoke('quit'),
  // main -> renderer (future: store-exited event to refocus the launcher)
  onStoreExited: (cb) => ipcRenderer.on('store-exited', (_e, id) => cb(id)),
});