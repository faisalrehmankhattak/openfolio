/**
 * A minimal media manager for SmallWebRTCTransport.
 *
 * The transport's default manager is built on Daily's call object, which loads
 * a script from Daily's CDN at runtime. Openfolio must work self-hosted and
 * without third-party calls, so this one uses getUserMedia directly. It only
 * handles the microphone; Openfolio never sends video.
 */

type Callbacks = { onTrackStarted?: (track: MediaStreamTrack, participant?: unknown) => void };

export class LocalMediaManager {
  private _options: unknown = null;
  private _callbacks: Callbacks = {};
  private _micEnabled = true;
  private stream: MediaStream | null = null;
  private micTrack: MediaStreamTrack | null = null;

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
    if (this._micEnabled) await this.acquire();
  }
  async connect() {
    if (this._micEnabled) await this.acquire();
  }
  async disconnect() {
    this.stream?.getTracks().forEach((t) => t.stop());
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
    if (this.micTrack) this.micTrack.enabled = enable;
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
