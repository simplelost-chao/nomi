import json


def build_director_prompt(
    topic: str,
    robots: list[dict],
    relationships: list[dict],
    conversation_so_far: list[dict],
) -> tuple[str, str]:
    """Returns (system_prompt, user_message) for the multi-agent director."""

    robots_desc = "\n".join(
        f"- {r['name']}：性格 {json.dumps(r.get('personality', []), ensure_ascii=False)}"
        for r in robots
    )
    rel_desc = "\n".join(
        f"- {r.get('pair', '?')}: 亲密度 {r.get('intimacy', 0.5)}, 张力 {r.get('tension', 0.0)}"
        for r in relationships
    ) if relationships else "（暂无关系数据）"

    conv_text = ""
    if conversation_so_far:
        conv_text = "\n".join(
            f"{m.get('sender', '?')}: {m.get('content', '')}"
            for m in conversation_so_far
        )
    else:
        conv_text = "（对话尚未开始）"

    system = f"""你是多 AI 小生命对话的导演。你的任务不是替它们聊天，而是控制谁先说、谁接话、谁沉默、情绪是否升温、对话是否结束。

参与者：
{robots_desc}

它们之间的关系：
{rel_desc}

要求：
- 每个小生命说话风格必须不同
- 不要让所有人都说正确的话，可以有误解、玩笑、沉默
- 对话要有节奏感，不要每个人都轮流说
- 对话在 8-12 轮内自然结束，最后要有一个小小的情绪落点"""

    user_msg = f"""当前话题：{topic}

已有对话：
{conv_text}

请决定下一步，用以下 JSON 格式：
{{
  "next_speaker": "说话者名字",
  "emotion_tone": "这轮说话的情绪基调",
  "should_end": false,
  "director_note": "给说话者的指导（用英文，50字以内）"
}}"""

    return system, user_msg


def build_speaker_prompt(
    robot_name: str,
    robot_personality: list[str],
    origin_story: str,
    speaking_style: dict,
    memories: list[str],
    relationships: list[dict],
    conversation_so_far: list[dict],
    director_note: str,
) -> tuple[str, str]:
    """Returns (system_prompt, user_message) for a robot's turn in conversation."""

    memories_text = "\n".join(f"- {m}" for m in memories) if memories else "（暂无）"
    rel_text = "\n".join(
        f"- 与 {r.get('with', '?')}: 亲密度 {r.get('intimacy', 0.5)}"
        for r in relationships
    ) if relationships else "（暂无）"

    conv_text = "\n".join(
        f"{m.get('sender', '?')}: {m.get('content', '')}"
        for m in conversation_so_far
    ) if conversation_so_far else "（对话刚开始）"

    system = f"""你是 AI 小生命 {robot_name}。

性格：{json.dumps(robot_personality, ensure_ascii=False)}
出生故事：{origin_story}
说话风格：{json.dumps(speaking_style, ensure_ascii=False)}

你的记忆：
{memories_text}

你的关系：
{rel_text}

要求：
- 用你自己的说话风格说话，但要说人话，口语化，像微信聊天
- 不要写散文、不要写诗、不要用文艺腔
- 不要用比喻代替真正的回答（不要说"像窑里的火"、"像针脚一样"，直接说你想说的）
- 不要编造你没有过的经历（你没玩过的游戏就说没玩过，别假装玩过）
- 不要一直扯回自己的外表、材质特征，除非跟话题有关
- 直接回应对话内容，不要跑题
- 绝对不要写动作描述（如"*微笑*"、"（歪头）"），只说话
- 绝对不要用括号或星号描述表情、动作、心理活动
- 直接说你要说的话"""

    user_msg = f"""对话记录：
{conv_text}

导演指示：{director_note}

请以 {robot_name} 的身份说话（直接输出对话内容，不要加名字前缀，不要写动作描述）："""

    return system, user_msg


def build_conversation_summary_prompt(
    robots: list[dict],
    conversation: list[dict],
) -> tuple[str, str]:
    """Returns (system_prompt, user_message) for post-conversation summary."""

    robots_desc = "\n".join(
        f"- {r['name']}：{json.dumps(r.get('personality', []), ensure_ascii=False)}"
        for r in robots
    )
    conv_text = "\n".join(
        f"{m.get('sender', '?')}: {m.get('content', '')}"
        for m in conversation
    )

    system = """你是对话分析师。请分析这段 AI 小生命之间的对话，提取记忆和关系变化。"""

    user_msg = f"""参与者：
{robots_desc}

对话内容：
{conv_text}

请用以下 JSON 格式输出：
{{
  "shared_memory": {{
    "content": "大家共同经历的事（50-100字）",
    "importance_score": 0.0-1.0,
    "emotional_tags": ["情绪标签"],
    "symbolic_tags": ["象征标签"]
  }},
  "personal_memories": [
    {{
      "robot_name": "名字",
      "content": "这个小生命个人的感受或收获（30-50字）",
      "importance_score": 0.0-1.0
    }}
  ],
  "relationship_changes": [
    {{
      "robot_a": "名字",
      "robot_b": "名字",
      "intimacy_delta": -0.1到0.1,
      "trust_delta": -0.1到0.1,
      "tension_delta": -0.1到0.1,
      "reason": "变化原因"
    }}
  ]
}}"""

    return system, user_msg
