/** Approximate speech shapes for ARKit-only avatars; native visemes take priority.
 * TalkingHead.addMixedMorphTarget skips a name already present on the mesh.
 */
export const ARKIT_VISEME_FALLBACKS = [
  { key: "viseme_aa", mix: { jawOpen: 1 } },
  { key: "viseme_E", mix: { jawOpen: .35, mouthStretchLeft: .5, mouthStretchRight: .5 } },
  { key: "viseme_I", mix: { jawOpen: .2, mouthStretchLeft: .65, mouthStretchRight: .65 } },
  { key: "viseme_O", mix: { jawOpen: .5, mouthFunnel: .9 } },
  { key: "viseme_U", mix: { jawOpen: .15, mouthPucker: .9 } },
  { key: "viseme_PP", mix: { mouthPressLeft: .8, mouthPressRight: .8, mouthClose: .5 } },
  { key: "viseme_SS", mix: { jawOpen: .12, mouthStretchLeft: .3, mouthStretchRight: .3 } },
  { key: "viseme_TH", mix: { jawOpen: .2, tongueOut: .25 } },
  { key: "viseme_DD", mix: { jawOpen: .25 } },
  { key: "viseme_FF", mix: { jawOpen: .1, mouthRollLower: .5 } },
  { key: "viseme_kk", mix: { jawOpen: .4 } },
  { key: "viseme_nn", mix: { jawOpen: .2 } },
  { key: "viseme_RR", mix: { jawOpen: .3, mouthPucker: .4 } },
  { key: "viseme_CH", mix: { jawOpen: .2, mouthFunnel: .5 } },
  { key: "viseme_sil", mix: { mouthClose: .01 } },
];
