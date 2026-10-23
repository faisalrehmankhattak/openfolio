/** Shapes shared between the widget and the Openfolio server. */

export type Mode = "bubble" | "inline";

export type MountOptions = {
  persona: string;
  server: string;
  assetBase: string;
  mode: Mode;
  onClose?: () => void;
};

export type PersonaInfo = {
  id: string;
  name: string;
  first_name: string;
  title: string;
  tagline: string;
  avatar: { kind: "mesh"; url: string; body: "M" | "F" };
  quick_questions: { label: string; question: string }[];
};

export type Project = { name: string; org?: string; period?: string; summary: string; metric?: string; url?: string };
export type Role = { company: string; title: string; period: string; summary: string };
export type Link = { label: string; url: string };

export type CardPayload =
  | { card: "projects"; data: { projects: Project[] } }
  | { card: "experience"; data: { roles: Role[]; education: string[] } }
  | { card: "skills"; data: { skills: Record<string, string[]> } }
  | { card: "contact"; data: { email: string | null; links: Link[]; booking_url: string | null } }
  | { card: "message_sent"; data: { name?: string } };

export type EndReason = "idle" | "turn_limit" | "voice_command";

export type ServerMessage = ({ type: "openfolio.card" } & CardPayload) | { type: "openfolio.ended"; reason: EndReason };

/** The parts of a TalkingHead instance this widget uses. */
export type Head = {
  audioCtx: AudioContext;
  audioAnalyzerNode: AudioNode;
  audioSpeechGainNode: GainNode;
  start(): void;
  stop(): void;
};
