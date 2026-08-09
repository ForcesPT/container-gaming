// gen-logos.js — emit bundled white SVG logos (one <path>) from simple-icons
// so the launcher has real brand marks with NO runtime internet dependency
// (the container's img-src CSP is 'self' data:). Run: node scripts/gen-logos.js
const si = require('simple-icons');
const fs = require('fs');
const path = require('path');

const MAP = {
  steam: 'siSteam',
  battlenet: 'siBattledotnet',
  epic: 'siEpicgames',
  gog: 'siGogdotcom',
  ea: 'siEa',
  ubisoft: 'siUbisoft',
};

const outDir = path.join(__dirname, '..', 'src', 'logos');
fs.mkdirSync(outDir, { recursive: true });

for (const [id, key] of Object.entries(MAP)) {
  const icon = si[key];
  if (!icon) { console.error(`missing ${key} (${id})`); continue; }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" role="img" aria-label="${icon.title}"><path d="${icon.path}" fill="#fff"/></svg>\n`;
  fs.writeFileSync(path.join(outDir, `${id}.svg`), svg);
  console.log(`wrote ${id}.svg (${icon.title}, path ${icon.path.length} chars)`);
}