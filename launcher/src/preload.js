// preload.js — bridges the renderer (index.html) to the main process (main.js)
// via contextBridge. Keeps nodeIntegration off; the renderer only gets the
// IPC calls it needs.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dpad', {
  getStores: () => ipcRenderer.invoke('get-stores'),
  launchStore: (id) => ipcRenderer.invoke('launch-store', id),
  pollGamepads: () => ipcRenderer.invoke('poll-gamepads'),
  quit: () => ipcRenderer.invoke('quit'),
  getActiveStore: () => ipcRenderer.invoke('get-active-store'),
  killActiveStore: () => ipcRenderer.invoke('kill-active-store'),
  // main -> renderer events
  onStoreVisible: (cb) => ipcRenderer.on('store-visible', (_e, id) => cb(id)),
  onStoreExited: (cb) => ipcRenderer.on('store-exited', (_e, id) => cb(id)),
  onStoreLaunchFailed: (cb) => ipcRenderer.on('store-launch-failed', (_e, id, err) => cb(id, err)),
  onStoreInstalling: (cb) => ipcRenderer.on('store-installing', (_e, id) => cb(id)),
});