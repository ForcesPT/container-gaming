const fs = require('node:fs');
const filename = process.argv[2];
let text = fs.readFileSync(filename, 'utf8');
const canonical = fs.readFileSync(process.argv[3], 'utf8').replace(/\r\n/g, '\n');
function replaceOnce(old, replacement) {
  if (text.split(old).length !== 2) throw new Error(`Pinned picker adapter mismatch: ${old.slice(0, 80)}`);
  text = text.replace(old, replacement);
}
replaceOnce("const { spawn, execSync } = require('child_process');",
  "const { spawn, execSync } = require('child_process');\nconst { reopenManagedEpic } = require('./epic_reopen.cjs');");
replaceOnce("ipcMain.handle('launch-store', (event, storeId) => {",
  "ipcMain.handle('launch-store', async (event, storeId) => {");
const start = canonical.indexOf("    if (storeId === 'epic' && process.env.DPAD_EPIC_BACKEND === 'faugus'\n");
const end = canonical.indexOf('    const resumed = resumeActiveStore({', start);
if (start < 0 || end < 0) throw new Error('Canonical Epic reopen block missing');
replaceOnce('    const existingChild = activeStoreChildren.get(storeId);',
  '    const existingChild = activeStoreChildren.get(storeId);\n' + canonical.slice(start, end));
replaceOnce('      if (visible) {', '      if (visible) {\n        child._dpadWindowSeen = true;');
fs.writeFileSync(filename, text);
