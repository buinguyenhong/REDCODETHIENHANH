class SoundPlayer {
  constructor() {
    this.audioContext = null;
    this.currentAudio = null;
    this.isPlaying = false;
    this.isAudioReady = false;
    this.repeatTimer = null;
  }

  init() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx && !this.audioContext) {
        this.audioContext = new AudioCtx();
        if (this.audioContext.state === 'running') {
          this.isAudioReady = true;
        }
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

    // Play a brief silent HTML Audio to unlock browser autoplay policy
    try {
      const silentAudio = new Audio('data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA');
      await silentAudio.play();
      this.isAudioReady = true;
      return true;
    } catch (err) {
      console.log('Audio autoplay still restricted by browser:', err);
      this.isAudioReady = false;
      return false;
    }
  }

  playAlarmSequence(audioUrls, repeatCount = 3, intervalMs = 1500, onStart = null, onComplete = null) {
    this.stop();
    if (!audioUrls || audioUrls.length === 0) {
      if (onComplete) onComplete();
      return;
    }

    this.isPlaying = true;
    let currentIteration = 0;
    let started = false;

    const playCycle = () => {
      if (!this.isPlaying) return;

      let fileIdx = 0;
      const playNextFile = () => {
        if (!this.isPlaying) return;
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

        this.currentAudio = new Audio(url);
        this.currentAudio.play().then(() => {
          this.isAudioReady = true;
          if (!started) {
            started = true;
            if (onStart) onStart();
          }
          this.currentAudio.onended = () => {
            playNextFile();
          };
        }).catch((err) => {
          console.warn('Browser blocked sound playback:', err);
          this.isAudioReady = false;
          if (!started) {
            started = true;
            if (onStart) onStart();
          }
          // Continue to next sequence anyway
          this.repeatTimer = setTimeout(playNextFile, 500);
        });
      };

      playNextFile();
    };

    playCycle();
  }

  playTestTone() {
    this.stop();
    try {
      const ctx = this.audioContext || new (window.AudioContext || window.webkitAudioContext)();
      this.audioContext = ctx;
      if (ctx.state === 'suspended') ctx.resume();

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
      this.isAudioReady = true;
    } catch (e) {
      console.warn('Tone test error:', e);
    }
  }

  stop() {
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
