const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const names = ['sendDataChannelMessage', 'reset'];
const methods = names.map(name => {
  const match = source.match(new RegExp('^    '+name+'\\([^)]*\\) \\{\\n[\\s\\S]*?^    \\}', 'm'));
  assert.ok(match, name);
  return match[0];
});
const scope = {Map};
vm.runInNewContext('this.Rtc = class {\n'+methods.join('\n')+'\n}', scope);
const rtc = new scope.Rtc();
const sent = [];
rtc._setError = () => assert.fail('expected transient recovery must not show an input error');
rtc._connected = false;
for (const state of [null, 'connecting', 'closing', 'closed', 'open']) {
  rtc._send_channel = state === null ? null : {readyState:state, send:x=>sent.push(x)};
  rtc.sendDataChannelMessage('kd,65');
}
assert.deepEqual(sent, []);
rtc._connected = true;
for (const state of ['connecting', 'closing', 'closed']) {
  rtc._send_channel = {readyState:state, send:x=>sent.push(x)};
  rtc.sendDataChannelMessage('kd,65');
}
assert.deepEqual(sent, []);
let closed = 0;
rtc._send_channel = {readyState:'open', send:x=>sent.push(x), close:()=>closed++};
rtc.sendDataChannelMessage('ku,65');
assert.deepEqual(sent, ['ku,65'], 'only current connected input is delivered');
rtc.peerConnection = {close:()=>closed++};
rtc.connect = () => {
  assert.equal(rtc._connected, false);
  assert.equal(rtc._send_channel, null);
  rtc.sendDataChannelMessage('kd,66');
};
rtc.reset();
assert.equal(closed, 2);
assert.deepEqual(sent, ['ku,65'], 'discarded input is never queued or replayed');
console.log('Recovery input lifecycle checks passed');
