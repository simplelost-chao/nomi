export interface Robot {
  id: string;
  name: string;
  age: number | null;
  birth_place: string | null;
  origin_story: string | null;
  core_desire: string | null;
  core_fear: string | null;
  personality: string[] | null;
  speaking_style: Record<string, string> | null;
  voice_profile: Record<string, string> | null;
  current_emotion: { emotion: string; intensity: number } | null;
  current_status: string | null;
  energy: number | null;
  generation_stats: Record<string, unknown> | null;
  relationships_snapshot: {
    name: string;
    role: string;
    status: string;
    memories: string[];
  }[] | null;
  created_at: string;
}

export interface YearlyMemory {
  id: string;
  age: number;
  memory_title: string | null;
  memory_content: string | null;
  emotional_impact: Record<string, unknown> | null;
  importance: number | null;
  memory_strength: number | null;
  symbolic_tags: string[] | null;
}

export interface RobotDetail extends Robot {
  yearly_memories: YearlyMemory[];
  portrait: Record<string, unknown> | null;
}

export interface RobotReaction {
  robot_id: string;
  robot_name: string;
  inner_thought: string;
  user_expression: string;
  should_remember: boolean;
  emotion_change: { emotion: string; intensity: number } | null;
}

export interface ObjectObservation {
  id: string;
  object_name: string | null;
  object_description: string | null;
  symbolic_tags: string[] | null;
  reactions: RobotReaction[];
}

export interface ChatMessage {
  id: string;
  sender_type: string | null;
  sender_id: string | null;
  sender_name: string | null;
  content: string | null;
  emotion: Record<string, unknown> | null;
  created_at: string;
  metadata?: { model?: string; llm_time_ms?: number } | null;
}

export interface Conversation {
  id: string;
  conversation_type: string | null;
  topic: string | null;
  created_at: string;
}
