/**
 * Microphone-only media manager for SmallWebRTCTransport.
 * The default manager loads Daily's SDK from a CDN; this one uses getUserMedia, so no third-party requests.
 */

type Callbacks = {
  onTrackStarted?: (track: MediaStreamTrack, participant?: unknown) => void;
  onDeviceError?: (error: unknown) => void;
};

export class LocalMediaManager {
  private _options: unknown = null;
  private _callbacks: Callbacks = {};
  private _micEnabled = true;
  private stream: MediaStream | null = null;
  private micTrack: MediaStreamTrack | null = null;
  /** Set by the app: puts a newly acquired mic track on the live connection. */
  onLocalTrack: ((track: MediaStreamTrack) => Promise<void> | void) | null = null;

  setUserAudioCallback(_cb: unknown) {}

  setClientOptions(options: { callbacks?: Callbacks; enableMic?: boolean }, override = false) {
    if (this._options && !override) return;
    this._options = options;
    this._callbacks = options.callbacks ?? {};
    this._micEnabled = options.enableMic ?? true;
  }

  get supportsScreenShare() {
    return false;
  }
  get mediaSupport() {
    return { screenShare: false };
  }

  private async acquire() {
    if (this.micTrack) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
    this.micTrack = this.stream.getAudioTracks()[0] ?? null;
    if (this.micTrack) {
      this.micTrack.enabled = this._micEnabled;
      this._callbacks.onTrackStarted?.(this.micTrack, { id: "local", name: "", local: true });
    }
  }

  async initialize() {
    await this.tryAcquire();
  }
  async connect() {
    await this.tryAcquire();
  }

  // The transport does not await device setup, so a thrown error would escape the connect flow.
  private async tryAcquire() {
    if (!this._micEnabled) return;
    try {
      await this.acquire();
    } catch (err) {
      this._micEnabled = false;
      this._callbacks.onDeviceError?.(err);
    }
  }
  async disconnect() {
    for (const t of this.stream?.getTracks() ?? []) t.stop();
    this.stream = null;
    this.micTrack = null;
  }

  async getAllMics() {
    return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  }
  async getAllCams() {
    return [];
  }
  async getAllSpeakers() {
    return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audiooutput");
  }
  updateMic(_id: string) {}
  updateCam(_id: string) {}
  updateSpeaker(_id: string) {}
  get selectedMic() {
    return {};
  }
  get selectedCam() {
    return {};
  }
  get selectedSpeaker() {
    return {};
  }

  enableMic(enable: boolean) {
    this._micEnabled = enable;
    if (this.micTrack) {
      this.micTrack.enabled = enable;
      return;
    }
    // A call started by typing has no mic yet: ask for it now.
    if (enable) {
      void this.acquire()
        .then(() => this.micTrack && this.onLocalTrack?.(this.micTrack))
        .catch((err) => {
          this._micEnabled = false;
          this._callbacks.onDeviceError?.(err);
        });
    }
  }
  enableCam(_enable: boolean) {}
  enableScreenShare(_enable: boolean) {}
  get isMicEnabled() {
    return this._micEnabled;
  }
  get isCamEnabled() {
    return false;
  }
  get isSharingScreen() {
    return false;
  }

  tracks() {
    return { local: { audio: this.micTrack ?? undefined, video: undefined } };
  }
}
