import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { soundPlayer } from '../src/utils/soundPlayer.js';

let audios;
beforeEach(() => {
  soundPlayer.stop();
  audios = [];
  globalThis.Audio = class {
    constructor(url) { this.url = url; audios.push(this); }
    play() { return Promise.resolve(); }
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
