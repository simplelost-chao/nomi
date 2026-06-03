// desktop/src/renderer/lib/lip-sync.ts

/**
 * Analyzes audio amplitude in real-time for Live2D lip-sync.
 * Connects to an HTMLAudioElement via Web Audio API and provides
 * a smoothed amplitude value (0~1) for driving ParamMouthOpenY.
 */
export class LipSyncAnalyzer {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: MediaElementAudioSourceNode | null = null;
  private dataArray: Uint8Array<ArrayBuffer> | null = null;
  private animFrameId: number = 0;
  private _amplitude: number = 0;
  private smoothing: number = 0.6; // higher = smoother, 0~1

  /**
   * Connect to an audio element and start analyzing.
   * Must be called after the audio element has started playing.
   */
  start(audioElement: HTMLAudioElement): void {
    this.stop();

    this.audioContext = new AudioContext();
    // Resume in case autoplay policy suspended it
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.3;

    this.source = this.audioContext.createMediaElementSource(audioElement);
    this.source.connect(this.analyser);
    this.analyser.connect(this.audioContext.destination); // still play through speakers

    const bufferLength = this.analyser.frequencyBinCount;
    this.dataArray = new Uint8Array(bufferLength) as Uint8Array<ArrayBuffer>;

    this.update();
  }

  private update = (): void => {
    if (!this.analyser || !this.dataArray) return;

    this.analyser.getByteFrequencyData(this.dataArray);

    // Calculate average amplitude from frequency data
    let sum = 0;
    for (let i = 0; i < this.dataArray.length; i++) {
      sum += this.dataArray[i];
    }
    const rawAmplitude = sum / (this.dataArray.length * 255); // normalize to 0~1

    // Apply exponential smoothing to avoid jittery mouth
    this._amplitude =
      this.smoothing * this._amplitude + (1 - this.smoothing) * rawAmplitude;

    this.animFrameId = requestAnimationFrame(this.update);
  };

  /** Get current smoothed amplitude (0~1) */
  getAmplitude(): number {
    return this._amplitude;
  }

  /** Disconnect and stop analyzing */
  stop(): void {
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = 0;
    }
    this._amplitude = 0;

    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
    this.dataArray = null;
  }
}
