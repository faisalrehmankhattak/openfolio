declare module "@met4citizen/talkinghead" {
  export class TalkingHead {
    constructor(node: HTMLElement, options: Record<string, unknown>);
    audioCtx: AudioContext;
    audioAnalyzerNode: AudioNode;
    audioSpeechGainNode: GainNode;
    mtExtras: { key: string; mix: Record<string, number> }[];
    mtAvatar: Record<string, { newvalue: number; needsUpdate: boolean }>;
    opt: { update?: (dt: number) => void };
    showAvatar(avatar: Record<string, unknown>, onprogress?: (ev: ProgressEvent) => void): Promise<void>;
    lookAtCamera(ms: number): void;
    start(): void;
    stop(): void;
  }
}

declare module "@met4citizen/headaudio/dist/headaudio.min.mjs" {
  export class HeadAudio extends AudioWorkletNode {
    constructor(ctx: AudioContext);
    loadModel(url: string): Promise<void>;
    update(dt: number): void;
    start(): void;
    stop(): void;
    onvalue: ((key: string, value: number) => void) | null;
    onstarted: (() => void) | null;
    onended: (() => void) | null;
  }
}
