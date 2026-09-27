const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('/opt/dpadcloud/launcher/resources/app.asar/src/main.js', 'utf8');
const block = source.match(/const STORE_WINDOW_CLASSES = (\{[\s\S]*?\n\});/);
assert.ok(block, 'packaged picker selectors missing');
for (const [backend, expected] of [['faugus', 'heroic'], ['heroic', 'heroic'], ['', 'heroic']]) {
  const selectors = vm.runInNewContext(`(${block[1]})`, {process: {env: {DPAD_EPIC_BACKEND: backend}}});
  assert.equal(selectors.epic, expected);
  assert.equal(selectors.gog, 'heroic');
}
assert.ok(source.includes("return swaymsg('[title=\"Epic Games Launcher\"] focus') !== null"));
const lifecycle = require('/opt/dpadcloud/launcher/resources/app.asar/src/store_lifecycle.cjs');
assert.equal(lifecycle.detectStoreIdFromTitles(['Epic Games Launcher']), 'epic');
require('/opt/dpadcloud/launcher/resources/app.asar/node_modules/koffi');
console.log('Packaged Epic selectors, title detection and native koffi import passed.');
