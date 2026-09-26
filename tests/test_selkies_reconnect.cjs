const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = process.argv[2];
const timers = new Map();
let timerId = 0;
const sockets = [];
class Socket {
  static CONNECTING = 0; static OPEN = 1; static CLOSED = 3;
  constructor() { this.readyState = Socket.CONNECTING; this.handlers = {}; sockets.push(this); }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  emit(event, value) { this.handlers[event]?.(value); }
  send() {}
  close() { this.readyState = Socket.CLOSED; this.emit('close'); }
}
const context = {
  WebSocket: Socket, console, Map,
  webrtc: {input: {getWindowResolution: () => [1920,1080]}},
  window: {devicePixelRatio: 1, location: {replace() { assert.fail('retry must not navigate'); }}},
  btoa: value => Buffer.from(value).toString('base64'),
  setTimeout(fn, delay) { const id=++timerId; timers.set(id,{fn,delay}); return id; },
  clearTimeout(id) { timers.delete(id); },
};
vm.runInNewContext(fs.readFileSync(path.join(root,'signalling.js'),'utf8')+'\nthis.Signalling=WebRTCDemoSignalling;',context);
const signal = new context.Signalling('wss://fixture');
signal.ondisconnect = () => signal.connect();
signal.connect(); signal.connect();
assert.equal(sockets.length,1,'duplicate connect cannot create a second socket');
let first=sockets[0]; first.readyState=Socket.OPEN; first.emit('open');
first.emit('message',{data:'HELLO'});
first.close();
assert.equal(sockets.length,2,'closed registered socket reconnects immediately');
const second=sockets[1];
first.emit('error'); first.emit('close');
assert.equal(timers.size,0,'late events from the old socket cannot reset the new one');
const expected=[250,500,1000,2000,3000,3000,3000];
for(const delay of expected) {
  const socket=sockets.at(-1);
  socket.readyState=Socket.CLOSED;
  socket.emit('error'); socket.emit('close'); socket.emit('error');
  assert.equal(timers.size,1,'error and close share exactly one retry');
  const [id,timer]=timers.entries().next().value;
  assert.equal(timer.delay,delay);
  timers.delete(id);timer.fn();
}
let current=sockets.at(-1); current.readyState=Socket.OPEN; current.emit('open');
assert.ok(signal.retry_count>0,'opening without HELLO does not reset outage backoff');
current.emit('message',{data:'HELLO'});
assert.equal(signal.retry_count,0,'successful registration resets backoff');
current.close(); current=sockets.at(-1);current.readyState=Socket.CLOSED;current.emit('close');
assert.equal(timers.size,1,'close without an error event still retries');
assert.equal([...timers.values()][0].delay,250);

const appSource=fs.readFileSync(path.join(root,'app.js'),'utf8');
const resets={video:0,audio:0};
const appContext={app:{status:'connected'},videoElement:{style:{}},
  signalling:{disconnect(){assert.fail('audio must not close video');}},
  audio_signalling:{disconnect(){assert.fail('video must not close audio');}},
  webrtc:{reset(){resets.video++;}},audio_webrtc:{reset(){resets.audio++;}}};
for(const name of ['signalling','audio_signalling']) {
 const block=appSource.match(new RegExp('^'+name+'\\.ondisconnect = \\(\\) => \\{\\n[\\s\\S]*?^\\}','m'));
 assert.ok(block);vm.runInNewContext(block[0],appContext);
}
appContext.signalling.ondisconnect();appContext.audio_signalling.ondisconnect();
assert.deepEqual(resets,{video:1,audio:1});
const rtcSource=fs.readFileSync(path.join(root,'webrtc.js'),'utf8');
const reset=rtcSource.match(/^    reset\(\) \{\n[\s\S]*?^    \}/m);
assert.ok(reset);
const rtcContext={Map};
vm.runInNewContext('this.Rtc=class {\n'+reset[0]+'\n}',rtcContext);
const rtc=new rtcContext.Rtc();let connected=0,closed=0;
rtc._send_channel=null;rtc.peerConnection={signalingState:'have-local-offer',close(){closed++;}};
rtc.connect=()=>connected++;
rtc.reset();assert.equal(closed,1);assert.equal(connected,1,'unstable old negotiation adds no fixed reset delay');
rtc.peerConnection=null;rtc.reset();assert.equal(connected,2,'initial null peer is safe');
console.log('Selkies reconnect lifecycle: all checks passed');
