import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { soundPlayer } from '../src/utils/soundPlayer.js';

let audios;
beforeEach(() => {
  soundPlayer.stop();
  audios = [];
  globalThis.Audio = class {
    constructor(url) { this.url = url; audios.push(this); }
    play() {
      // Clip thử (data: URI) tự phát hết rồi bắn 'ended' như trình duyệt thật.
      // Chỉ clip thử mới tự kết thúc: các tệp còi thật trong test do từng bài tự
      // điều khiển onended, nên không được bắn hộ.
      if (typeof this.url === 'string' && this.url.startsWith('data:')) {
        setTimeout(() => { if (this.onended) this.onended(); }, 0);
      }
      return Promise.resolve();
    }
    pause() { this.paused = true; }
  };
});

test('play rejection emits failure without successful start or completion', async () => {
  globalThis.Audio.prototype.play = () => Promise.reject(new Error('autoplay blocked'));
  let started = 0, completed = 0, failed = 0;
  soundPlayer.playAlarmSequence(['/assets/audio/test.wav'], 1, 0, () => started++, () => completed++, () => failed++);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(failed, 1);
  assert.equal(started, 0);
  assert.equal(completed, 0);
  assert.equal(soundPlayer.isAudioReady, false);
});

test('callbacks from stopped playback cannot advance or complete new playback', async () => {
  let completed = 0;
  soundPlayer.playAlarmSequence(['/assets/audio/a.wav', '/assets/audio/b.wav'], 1, 0, null, () => completed++);
  await Promise.resolve();
  const old = audios[0];
  soundPlayer.stop();
  soundPlayer.playAlarmSequence(['/assets/audio/c.wav'], 1, 0);
  old.onended();
  assert.equal(audios.length, 2);
  assert.equal(completed, 0);
  soundPlayer.stop();
});

test('remote audio test cannot interrupt active alarm', async () => {
  soundPlayer.playAlarmSequence(['/assets/audio/a.wav'], 1, 0);
  await assert.rejects(soundPlayer.playTestTone(), /Đang phát cảnh báo/);
  assert.equal(soundPlayer.isPlaying, true);
  soundPlayer.stop();
});

test('start waits for play resolve; completion waits for last file ended', async () => {
  let resolvePlay, started = 0, completed = 0;
  globalThis.Audio.prototype.play = () => new Promise(resolve => { resolvePlay = resolve; });
  soundPlayer.playAlarmSequence(['/assets/audio/a.wav', '/assets/audio/b.wav'], 1, 0, () => started++, () => completed++);
  assert.equal(started, 0);
  resolvePlay();
  await Promise.resolve();
  assert.equal(started, 1);
  assert.equal(completed, 0);
  audios[0].onended();
  resolvePlay();
  await Promise.resolve();
  assert.equal(started, 1);
  audios[1].onended();
  assert.equal(completed, 1);
});

test('late ended or repeated errors after failure cannot complete audio', async () => {
  let completed = 0, failed = 0;
  globalThis.Audio.prototype.play = () => Promise.reject(new Error('blocked'));
  soundPlayer.playAlarmSequence(['/assets/audio/a.wav'], 1, 0, null, () => completed++, () => failed++);
  await new Promise(resolve => setTimeout(resolve, 0));
  audios[0].onended();
  audios[0].onerror();
  assert.equal(completed, 0);
  assert.equal(failed, 1);
});

// --- Hồi quy: cờ "sẵn sàng âm thanh" ---
// Báo động thật phát qua new Audio(url) (HTMLAudioElement), còn phép thử cũ chỉ
// chạy OscillatorNode của WebAudio. Hai đường ống có chính sách autoplay riêng,
// nên một tiếng bíp WebAudio thành công không chứng minh được báo động sẽ hú.

test('verifyPlayback proves readiness through the same <audio> pipeline real alarms use', async () => {
  soundPlayer.isAudioReady = false;
  assert.equal(await soundPlayer.verifyPlayback(), true);
  assert.equal(soundPlayer.isAudioReady, true);
  assert.equal(audios.length, 1);
  assert.match(audios[0].url, /^data:audio\/wav;base64,/);
  assert.equal(audios[0].paused, true, 'phải dừng ngay sau khi thử để không phát thừa');
});

test('verifyPlayback refuses to claim readiness when the browser blocks playback', async () => {
  soundPlayer.isAudioReady = false;
  globalThis.Audio.prototype.play = () => Promise.reject(new Error('NotAllowedError'));
  await assert.rejects(soundPlayer.verifyPlayback(), /NotAllowedError/);
  assert.equal(soundPlayer.isAudioReady, false);
});

// --- Hồi quy: tiếng thử phải NGHE ĐƯỢC ---
// play() của HTMLAudioElement resolve lúc audio BẮT ĐẦU phát, không phải lúc phát
// xong. Dừng ngay sau khi play() resolve là cắt tiếng sau vài mili giây: cờ sẵn
// sàng vẫn đúng, nhưng người bấm TEST LOA không nghe thấy gì và tưởng loa hỏng.

test('verifyPlayback lets the probe tone play out instead of cutting it after a few milliseconds', async () => {
  const events = [];
  globalThis.Audio = class {
    constructor(url) { this.url = url; audios.push(this); }
    play() {
      events.push('play-started');
      setTimeout(() => { events.push('ended'); if (this.onended) this.onended(); }, 0);
      return Promise.resolve();
    }
    pause() { events.push('pause'); this.paused = true; }
  };
  soundPlayer.isAudioReady = false;
  assert.equal(await soundPlayer.verifyPlayback(), true);
  assert.deepEqual(
    events,
    ['play-started', 'ended', 'pause'],
    'phải để tiếng thử phát hết rồi mới dừng; dừng ngay sau play() thì loa gần như không kêu'
  );
  assert.equal(soundPlayer.isAudioReady, true);
});

test('verifyPlayback still finishes when the probe never reports it ended', async () => {
  globalThis.Audio = class {
    constructor(url) { this.url = url; audios.push(this); }
    play() { return Promise.resolve(); }
    pause() { this.paused = true; }
  };
  soundPlayer.isAudioReady = false;
  const started = Date.now();
  assert.equal(await soundPlayer.verifyPlayback(), true);
  assert.equal(soundPlayer.isAudioReady, true, 'quyền autoplay đã được chứng minh khi play() trả về');
  assert.ok(
    Date.now() - started < 5000,
    'không được treo vô hạn khi trình duyệt không bắn sự kiện ended'
  );
  assert.equal(audios[0].paused, true, 'vẫn phải dừng clip thử sau khi chờ');
});

test('a WebAudio test tone cannot by itself mark the station audio-ready', async () => {
  soundPlayer.isAudioReady = false;
  soundPlayer.audioContext = {
    state: 'running',
    currentTime: 0,
    destination: {},
    resume: () => Promise.resolve(),
    createOscillator: () => ({
      frequency: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
      connect() {}, start() {}, stop() {},
      set onended(fn) { setTimeout(fn, 0); },
    }),
    createGain: () => ({ gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }),
  };
  await soundPlayer.playTestTone();
  assert.equal(soundPlayer.isAudioReady, false, 'tiếng bíp WebAudio không phải bằng chứng phát được báo động');
  soundPlayer.audioContext = null;
});

test('audio verification cannot interrupt an active alarm', async () => {
  soundPlayer.playAlarmSequence(['/assets/audio/a.wav'], 1, 0);
  await assert.rejects(soundPlayer.verifyPlayback(), /Đang phát cảnh báo/);
  assert.equal(soundPlayer.isPlaying, true);
  soundPlayer.stop();
});
