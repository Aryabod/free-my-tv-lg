// Checks the weather scene mapping in web/home.js: every WMO code → scene, and rain/snow level.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');   // Git on Windows checks out CRLF
function grab(name, oneLine) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('missing ' + name);
  const end = oneLine ? src.indexOf('\n', start) : src.indexOf('\n  }\n', start) + 4;
  return src.slice(start, end) + '\n';
}
const {wxKind, wxLevel} = new Function(grab('wxKind') + grab('wxLevel') +
  'return {wxKind: wxKind, wxLevel: wxLevel};')();

const want = {0: 'clear', 1: 'clear', 2: 'partly', 3: 'cloudy', 45: 'fog', 48: 'fog', 51: 'rain', 53: 'rain', 55: 'rain',
  56: 'rain', 57: 'rain', 61: 'rain', 63: 'rain', 65: 'rain', 66: 'rain', 67: 'rain', 71: 'snow', 73: 'snow', 75: 'snow',
  77: 'snow', 80: 'rain', 81: 'rain', 82: 'rain', 85: 'snow', 86: 'snow', 95: 'storm', 96: 'storm', 99: 'storm'};
const lvl = {51: 'light', 53: 'light', 55: 'light', 61: 'light', 63: '', 65: 'heavy', 71: 'light', 73: '', 75: 'heavy',
  80: 'light', 81: '', 82: 'heavy', 86: 'heavy'};
let bad = 0, n = 0;
for (const c in want) { n++; const k = wxKind(+c); if (k !== want[c]) { bad++; console.log('KIND', c, k, 'want', want[c]); } }
for (const c in lvl) { n++; const l = wxLevel(+c); if (l !== lvl[c]) { bad++; console.log('LEVEL', c, l, 'want', lvl[c]); } }
for (const v of [undefined, null, NaN]) { n++; if (wxKind(v) !== '') { bad++; console.log('EMPTY', v); } }
console.log(bad ? bad + ' FAILURES of ' + n : 'all ' + n + ' checks pass');
process.exit(bad ? 1 : 0);
