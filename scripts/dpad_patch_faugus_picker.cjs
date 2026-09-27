const fs = require('node:fs');
const path = process.argv[2];
const original = fs.readFileSync(path, 'utf8');
const old = "  epic: 'heroic',";
if (original.split(old).length !== 2) throw new Error('Unexpected Epic picker selector');
if (original.split('function focusStoreWindow(storeId) {').length !== 2) throw new Error('Unexpected focus handler');
fs.writeFileSync(path, original.replace(
  'function focusStoreWindow(storeId) {',
  `function focusStoreWindow(storeId) {
  if (storeId === 'epic' && process.env.DPAD_EPIC_BACKEND === 'faugus') {
    return swaymsg('[title="Epic Games Launcher"] focus') !== null;
  }`));
