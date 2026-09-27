const fs = require('node:fs');
const path = process.argv[2];
const original = fs.readFileSync(path, 'utf8');
const old = "  epic: 'heroic',";
if (original.split(old).length !== 2) throw new Error('Unexpected Epic picker selector');
fs.writeFileSync(path, original.replace(old,
  "  epic: process.env.DPAD_EPIC_BACKEND === 'faugus' ? 'EpicGamesLauncher.exe' : 'heroic',"));
