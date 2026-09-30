// Extend the accepted Epic picker without replacing its reopen handler.
const fs = require('node:fs');
const filename = process.argv[2];
let text = fs.readFileSync(filename, 'utf8').replace(/\r\n/g, '\n');
const marker = 'function focusStoreWindow(storeId) {\n';
if (text.split(marker).length !== 2 || text.includes("process.env.DPAD_GOG_BACKEND === 'official'")) {
  throw new Error('Pinned official GOG picker adapter mismatch');
}
if (!text.includes("require('./epic_reopen.cjs')")) {
  throw new Error('Accepted Epic reopen handler is missing');
}
text = text.replace(marker, marker + `  if (storeId === 'gog' && process.env.DPAD_GOG_BACKEND === 'official') {
    return swaymsg('[title="GOG GALAXY"] focus') !== null;
  }
`);
fs.writeFileSync(filename, text);
