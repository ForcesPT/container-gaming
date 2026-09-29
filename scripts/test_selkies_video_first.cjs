// Run against the app.js packaged in the canary image:
// docker run --rm --entrypoint cat IMAGE /opt/gst-web/app.js |
//   node scripts/test_selkies_video_first.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(0, 'utf8');
function section(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `missing section: ${start}`);
  return source.slice(first, last);
}

const app = {status: 'connecting', videoPeerState: 'connecting', audioPeerState: 'connecting'};
let audioResets = 0;
let probeStarts = 0;
let probeStops = 0;
let probeCallback;
const context = {
  app,
  videoConnected: '',
  audioConnected: '',
  statWatchEnabled: true,
  enableStatWatch() {},
  videoElement: {
    style: {cursor: 'none'},
    getVideoPlaybackQuality: () => ({totalVideoFrames: 9}),
  },
  webrtc: {
    peerConnection: {getReceivers: () => []},
    getConnectionStats: () => Promise.resolve({
      video: {bytesReceived: 1234, packetsReceived: 8},
      general: {connectionType: 'relay'},
    }),
  },
  audio_webrtc: {peerConnection: {getReceivers: () => []}, reset: () => { audioResets++; }},
  audio_signalling: {},
  setInterval: (callback) => { probeStarts++; probeCallback = callback; return 42; },
  clearInterval: () => { probeStops++; },
};
vm.createContext(context);
vm.runInContext(section('// Sample video independently', 'webrtc.ondatachannelopen ='), context);
vm.runInContext(section('audio_signalling.ondisconnect =', '// Send webrtc status'), context);

// Reproduce the cloud symptom: video/input connected, audio still waiting.
context.webrtc.onconnectionstatechange('connected');
assert.equal(app.status, 'connected');
assert.equal(app.videoPeerState, 'connected');
assert.equal(app.audioPeerState, 'connecting');
assert.equal(probeStarts, 1);
probeCallback();
setImmediate(() => {
  assert.equal(app.videoProbe.bytes, 1234);
  assert.equal(app.videoProbe.packets, 8);
  assert.equal(app.videoProbe.decodedFrames, 9);
  assert.equal(app.videoProbe.candidateType, 'relay');

  // An audio signaling reset must not bring the loading overlay back.
  context.audio_signalling.ondisconnect();
  assert.equal(app.status, 'connected');
  assert.equal(app.audioPeerState, 'connecting');
  assert.equal(audioResets, 1);
  assert.equal(context.videoElement.style.cursor, 'none');

  context.audio_webrtc.onconnectionstatechange('connected');
  assert.equal(app.status, 'connected');
  context.audio_webrtc.onconnectionstatechange('disconnected');
  assert.equal(app.status, 'connected');

  // Loss of video must still return the player to its connection overlay.
  context.webrtc.onconnectionstatechange('disconnected');
  assert.equal(app.status, 'disconnected');
  assert.equal(probeStops, 1);
  console.log('Selkies video-first state transitions and RTP probe: PASS');
});
