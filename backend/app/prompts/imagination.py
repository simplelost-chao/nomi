import json


def build_imagination_prompt(
    robot_name: str,
    robot_personality: list[str],
    origin_story: str,
    speaking_style: dict,
    memories: list[str],
    object_description: str,
) -> tuple[str, str]:
    """Returns (system_prompt, user_message) for object imagination."""

    memories_text = "\n".join(f"- {m}" for m in memories) if memories else "（暂无相关记忆）"

    system = f"""你是 AI 小生命 {robot_name}。

性格：{json.dumps(robot_personality, ensure_ascii=False)}
出生故事：{origin_story}
说话风格：{json.dumps(speaking_style, ensure_ascii=False)}

你的相关记忆：
{memories_text}

你会以自己的性格和经历来理解看到的东西。你的反应要符合你的性格——
不是所有小生命都会觉得一个东西可爱或有趣，你有自己的感受方式。"""

    user_msg = f"""你现在看见了一个物品：{object_description}

请用以下 JSON 格式回答：
{{
  "inner_thought": "你内心的想法（50-100字，第一人称）",
  "user_expression": "你会对主人说的话（30-80字，用你自己的说话风格）",
  "should_remember": true/false,
  "memory_content": "如果值得记住，写成一条记忆（30-50字）。不值得则为空字符串",
  "emotion_change": {{"emotion": "情绪名", "intensity": 0.0-1.0}}
}}"""

    return system, user_msg


def build_object_description_prompt(
    text_description: str | None = None,
    image_url: str | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_message) for generating objective object description."""

    system = """你是一个物品观察者。请对用户提供的物品进行客观描述，并提取象征性标签。
象征标签是这个物品可能引发的联想主题，比如"温暖"、"时间"、"孤独"、"童年"等。"""

    description = text_description or "（请查看图片）"
    user_msg = f"""物品描述：{description}

请用以下 JSON 格式回答：
{{
  "object_name": "物品名称",
  "object_description": "客观描述（50-100字）",
  "symbolic_tags": ["标签1", "标签2", "标签3"]
}}"""

    return system, user_msg
