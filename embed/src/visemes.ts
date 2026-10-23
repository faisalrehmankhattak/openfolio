/** Speech shapes mixed from ARKit blendshapes, for avatars without Oculus visemes. Native visemes win. */
export const ARKIT_VISEME_FALLBACKS: { key: string; mix: Record<string, number> }[] = [
  { key: "viseme_aa", mix: { jawOpen: 1 } },
  { key: "viseme_E", mix: { jawOpen: 0.35, mouthStretchLeft: 0.5, mouthStretchRight: 0.5 } },
  { key: "viseme_I", mix: { jawOpen: 0.2, mouthStretchLeft: 0.65, mouthStretchRight: 0.65 } },
  { key: "viseme_O", mix: { jawOpen: 0.5, mouthFunnel: 0.9 } },
  { key: "viseme_U", mix: { jawOpen: 0.15, mouthPucker: 0.9 } },
  { key: "viseme_PP", mix: { mouthPressLeft: 0.8, mouthPressRight: 0.8, mouthClose: 0.5 } },
  { key: "viseme_SS", mix: { jawOpen: 0.12, mouthStretchLeft: 0.3, mouthStretchRight: 0.3 } },
  { key: "viseme_TH", mix: { jawOpen: 0.2, tongueOut: 0.25 } },
  { key: "viseme_DD", mix: { jawOpen: 0.25 } },
  { key: "viseme_FF", mix: { jawOpen: 0.1, mouthRollLower: 0.5 } },
  { key: "viseme_kk", mix: { jawOpen: 0.4 } },
  { key: "viseme_nn", mix: { jawOpen: 0.2 } },
  { key: "viseme_RR", mix: { jawOpen: 0.3, mouthPucker: 0.4 } },
  { key: "viseme_CH", mix: { jawOpen: 0.2, mouthFunnel: 0.5 } },
  { key: "viseme_sil", mix: { mouthClose: 0.01 } },
];
