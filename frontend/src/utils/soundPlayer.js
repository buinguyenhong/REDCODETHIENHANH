class SoundPlayer {
  constructor() {
    this.audioContext = null;
    this.currentAudio = null;
    this.isPlaying = false;
    this.isAudioReady = false;
    this.repeatTimer = null;
    this.generation = 0;
  }

  init() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx && !this.audioContext) {
        this.audioContext = new AudioCtx();
      }
    } catch (e) {
      console.warn('AudioContext init error:', e);
    }
  }

  async unlockAudio() {
    this.init();
    if (this.audioContext && this.audioContext.state === 'suspended') {
      try {
        await this.audioContext.resume();
      } catch (e) {
        console.warn('Failed to resume AudioContext:', e);
      }
    }

    // Audible test; production does not seed the demo WAV file.
    try {
      await this.playTestTone();
      this.isAudioReady = true;
      return true;
    } catch (err) {
      console.log('Audio autoplay still restricted by browser:', err);
      this.isAudioReady = false;
      return false;
    }
  }

  playAlarmSequence(audioUrls, repeatCount = 3, intervalMs = 1500, onStart = null, onComplete = null, onError = null) {
    this.stop();
    const generation = this.generation;
    if (!audioUrls || audioUrls.length === 0) {
      return;
    }

    this.isPlaying = true;
    let currentIteration = 0;
    let started = false;

    const playCycle = () => {
      if (!this.isPlaying || generation !== this.generation) return;

      let fileIdx = 0;
      const playNextFile = () => {
        if (!this.isPlaying || generation !== this.generation) return;
        if (fileIdx >= audioUrls.length) {
          currentIteration++;
          if (currentIteration < repeatCount) {
            this.repeatTimer = setTimeout(playCycle, intervalMs);
          } else {
            this.isPlaying = false;
            if (onComplete) onComplete();
          }
          return;
        }

        const url = audioUrls[fileIdx];
        fileIdx++;

        const audio = new Audio(url);
        this.currentAudio = audio;
        audio.onended = () => { if (generation === this.generation) playNextFile(); };
        const fail = (err) => {
          if (generation !== this.generation || !this.isPlaying) return;
          this.stop();
          this.isAudioReady = false;
          if (onError) onError(err);
        };
        audio.onerror = () => fail(new Error('Không tải được file âm thanh'));
        audio.play().then(() => {
          if (generation !== this.generation) { audio.pause(); return; }
          this.isAudioReady = true;
          if (!started) {
            started = true;
            if (onStart) onStart();
          }
        }).catch(fail);
      };

      playNextFile();
    };

    playCycle();
  }

  async playTestTone() {
    if (this.isPlaying) throw new Error('Đang phát cảnh báo; không thực hiện test');
    try {
      const ctx = this.audioContext || new (window.AudioContext || window.webkitAudioContext)();
      this.audioContext = ctx;
      if (ctx.state === 'suspended') await ctx.resume();
      if (ctx.state !== 'running') throw new Error('AudioContext chưa sẵn sàng');

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.4);

      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + 0.5);
      await new Promise((resolve) => { osc.onended = resolve; });
      this.isAudioReady = true;
      return true;
    } catch (e) {
      console.warn('Tone test error:', e);
      this.isAudioReady = false;
      throw e;
    }
  }

  stop() {
    this.generation++;
    this.isPlaying = false;
    if (this.repeatTimer) {
      clearTimeout(this.repeatTimer);
      this.repeatTimer = null;
    }
    if (this.currentAudio) {
      try {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
      } catch (_) {}
      this.currentAudio = null;
    }
  }
}

export const soundPlayer = new SoundPlayer();
