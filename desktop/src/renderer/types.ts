export interface Robot {
  id: string;
  name: string;
  age: number | null;
  current_emotion: { emotion: string; intensity: number } | null;
  current_status: string | null;
}

// Map robot names to character asset directories
export const CHARACTER_DIRS: Record<string, string> = {
  "フリーレン": "./characters/frieren",
  "冯宝宝": "./characters/fengbaobao",
  "Anya": "./characters/anya",
  "椿": "./characters/tsubaki",
  "Alexia": "./characters/alexia",
  "火火": "./characters/huohuo",
  "长离": "./characters/changli",
  "フリーレン（Replica）": "./characters/frieren_replica",
};

// Map robot names to voice config keys
export const ROBOT_VOICE_MAP: Record<string, string> = {
  "フリーレン": "frieren",
  "冯宝宝": "fengbaobao",
  "禰豆子": "nezuko",
  "Anya": "anya",
};

// Which robots speak which language for TTS
// japanese: TTS uses reply_ja field
// chinese: TTS uses reply (chinese) field directly
export const ROBOT_TTS_LANG: Record<string, "japanese" | "chinese"> = {
  "フリーレン": "japanese",
  "冯宝宝": "chinese",
  "禰豆子": "japanese",
  "Anya": "japanese",
};

// Map robot names to Live2D model paths (relative to public/)
// Only robots with a Live2D model path can use Live2D display mode
export const CHARACTER_LIVE2D: Record<string, string> = {
  "フリーレン": "./live2d/frieren/Frieren.model3.json",
  "フリーレン（Replica）": "./live2d/FrierenReplica/Frieren.model3.json",
  "Alexia": "./live2d/Alexia/Alexia.model3.json",
  "椿": "./live2d/11月椿/椿/椿.model3.json",
  "火火": "./live2d/huohuo/huohuo.model3.json",
  "长离": "./live2d/长离带水印/长离.model3.json",
  "Anya": "./live2d/ANIYA/ANIYA.model3.json",
};

export interface ChatMessage {
  id: string;
  sender_type: string | null;
  sender_id: string | null;
  sender_name: string | null;
  content: string | null;
  emotion: Record<string, unknown> | null;
  created_at: string;
  _japanese?: string;
  _emotion?: string;
  _isReaction?: boolean;
}

export interface Conversation {
  id: string;
  messages: ChatMessage[];
}
