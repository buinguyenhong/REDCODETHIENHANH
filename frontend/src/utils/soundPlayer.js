// Trần chờ tiếng thử phát xong, tính bằng ms. Clip thử dài 0,35 giây; trần này chỉ
// để một trình duyệt không bắn sự kiện 'ended' (clip treo, tab bị ẩn) không giữ
// promise treo mãi và chặn unlockAudio.
export const PROBE_MAX_WAIT_MS = 1500;

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

    // Xác minh bằng ĐÚNG đường ống mà báo động thật dùng, không phải WebAudio.
    try {
      await this.verifyPlayback();
      return true;
    } catch (err) {
      console.log('Audio autoplay still restricted by browser:', err);
      return false;
    }
  }

  /**
   * Sinh một tệp WAV ngắn ngay trong trình duyệt để thử phát.
   *
   * Không phụ thuộc tệp còi thật: production không seed sẵn file demo, mà phép
   * thử này chỉ cần một nguồn audio hợp lệ để trình duyệt quyết định cho phát hay không.
   */
  buildProbeWavDataUri(durationSeconds = 0.35, frequency = 880) {
    const sampleRate = 8000;
    const samples = Math.floor(sampleRate * durationSeconds);
    const buffer = new ArrayBuffer(44 + samples * 2);
    const view = new DataView(buffer);
    const writeAscii = (offset, text) => {
      for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
    };
    writeAscii(0, 'RIFF');
    view.setUint32(4, 36 + samples * 2, true);
    writeAscii(8, 'WAVE');
    writeAscii(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);                 // PCM
    view.setUint16(22, 1, true);                 // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);    // byte rate
    view.setUint16(32, 2, true);                 // block align
    view.setUint16(34, 16, true);                // bits per sample
    writeAscii(36, 'data');
    view.setUint32(40, samples * 2, true);
    for (let i = 0; i < samples; i++) {
      const fade = Math.min(1, i / 200, (samples - i) / 200);
      view.setInt16(44 + i * 2, Math.sin((2 * Math.PI * frequency * i) / sampleRate) * 0.3 * fade * 32767, true);
    }
    let binary = '';
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return `data:audio/wav;base64,${btoa(binary)}`;
  }

  /**
   * Chứng minh thiết bị THẬT SỰ phát được âm thanh báo động.
   *
   * Báo động thật phát qua ``new Audio(url)`` (HTMLAudioElement), còn phép thử cũ
   * chỉ dùng OscillatorNode của WebAudio. Hai đường ống này có chính sách autoplay
   * riêng: WebAudio chạy được sau một cú chạm KHÔNG bảo đảm thẻ <audio> phát được.
   * Vì vậy cờ sẵn sàng chỉ được bật khi chính đường ống <audio> đã phát thành công.
   */
  async verifyPlayback() {
    if (this.isPlaying) throw new Error('Đang phát cảnh báo; không thực hiện test');
    try {
      const probe = new Audio(this.buildProbeWavDataUri());
      await probe.play();
      // Đợi tiếng thử phát XONG rồi mới dừng. Trước đây pause() được gọi ngay sau
      // khi play() trả về, mà play() chỉ resolve lúc audio BẮT ĐẦU phát — nên phép
      // thử cắt tiếng sau vài mili giây và người bấm TEST LOA gần như không nghe
      // thấy gì, dù kết luận sẵn sàng/không sẵn sàng vẫn đúng. Chờ hết clip vừa cho
      // phản hồi nghe được, vừa giữ nguyên thời điểm đặt cờ.
      //
      // Chờ có trần: nếu trình duyệt không bắn 'ended' (clip bị treo, tab bị ẩn),
      // không được để promise này treo mãi và chặn unlockAudio.
      await new Promise((resolve) => {
        let settled = false;
        const done = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          probe.onended = null;
          probe.onerror = null;
          resolve();
        };
        const timer = setTimeout(done, PROBE_MAX_WAIT_MS);
        probe.onended = done;
        // Lỗi tải clip không phải lý do để chờ hết trần: quyền autoplay đã được
        // chứng minh ngay khi play() ở trên trả về.
        probe.onerror = done;
      });
      probe.pause();
      this.isAudioReady = true;
      return true;
    } catch (e) {
      this.isAudioReady = false;
      throw e;
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
      // KHÔNG đặt isAudioReady = true ở đây: tiếng bíp WebAudio chỉ chứng minh
      // AudioContext chạy được, không chứng minh thẻ <audio> mà báo động thật dùng
      // phát được. Muốn bật cờ sẵn sàng phải dùng verifyPlayback().
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
