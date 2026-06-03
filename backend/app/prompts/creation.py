import json


def build_object_identify_prompt() -> tuple[str, str]:
    system = """你是一个物品鉴赏专家，擅长从物品的外观读出它的故事。
你不只是识别物品是什么，更要感受它是一个什么样的存在——
它的材质透露了什么？它的磨损痕迹说明了什么？它的颜色给人什么感觉？
每一个细节都可能成为它"性格"的来源。"""

    user_msg = """请仔细观察图片中的主要物品，像鉴赏一件有故事的物品那样描述它。

用以下 JSON 格式输出：
{
  "object_name": "物品名称（具体型号或类型）",
  "category": "大类（玩具/餐具/工具/植物/电子产品/文具/装饰品等）",
  "description": "整体描述（50-100字）",
  "material": "材质（塑料/陶瓷/金属/布料/木头/混合等）",
  "color_palette": "主要颜色和色调感觉",
  "size_feeling": "大小给人的感觉（小巧精致/中等/厚重/巨大等）",
  "wear_signs": "使用痕迹和磨损程度（全新无瑕/轻微使用/明显使用/饱经沧桑）",
  "texture": "触感想象（光滑/粗糙/柔软/坚硬/温暖/冰冷）",
  "distinctive_features": ["最有辨识度的特征1", "特征2", "特征3"],
  "emotional_impression": "这个物品给你的第一情感印象（一句话）",
  "estimated_age": "估计年龄",
  "story_hints": "从外观推测它可能经历过什么（50字）"
}"""
    return system, user_msg


def build_robot_creation_from_image_prompt(
    object_description: str,
    existing_robots: list[dict],
) -> tuple[str, str]:
    system = """你是一个 AI 小生命设定生成器。用户会给你一个物品的描述，你要想象这个物品如果有生命，它会是什么样的。

要求：
- 物品的材质、形状、磨损程度决定了它的年龄和性格
- 它的愿望和恐惧要跟物品本身的"命运"有关
- 说话风格要能体现物品特质"""

    if existing_robots:
        system += "\n\n已有的小生命（创建一个不同的）：\n"
        for robot in existing_robots:
            system += f"- {robot['name']}：{json.dumps(robot.get('personality', []), ensure_ascii=False)}\n"

    user_msg = f"""这个物品是：{object_description}

请想象它如果有生命，用以下 JSON 格式输出：
{{
  "name": "名字（跟物品特征相关的昵称）",
  "age": 数字（根据物品新旧程度），
  "birth_place": "出生地",
  "core_personality": ["性格词1", "性格词2", "性格词3"],
  "core_desire": "核心愿望",
  "core_fear": "核心恐惧",
  "inner_drives": {{
    "curiosity": 0.0-1.0,
    "curiosity_about": ["它最好奇的方向，2-3个，比如'人类的情感'、'外面的天气'、'其他物品的故事'"],
    "sociability": 0.0-1.0,
    "introspection": 0.0-1.0,
    "playfulness": 0.0-1.0,
    "empathy": 0.0-1.0,
    "courage": 0.0-1.0,
    "patience": 0.0-1.0,
    "creativity": 0.0-1.0,
    "humor": 0.0-1.0
  }},
  "speaking_style": {{
    "speed": "slow/medium/fast",
    "tone": "soft/bright/deep/playful",
    "sentence_length": "short/medium/long",
    "metaphor_level": "low/medium/high"
  }},
  "voice_profile": {{
    "gender_feeling": "neutral/male/female/neutral-female/neutral-male",
    "age_feeling": "child/young/mature",
    "pitch": "low/medium/high/soft",
    "emotion_range": "warm/cool/wide/narrow"
  }}
}}

inner_drives 说明（这些值要从性格自然生长出来，不是随机的）：
- curiosity：对未知事物的好奇程度。一个旧书可能很高，一个锤子可能很低
- curiosity_about：好奇的具体方向，跟物品经历有关。杯子可能好奇"喝它的人在想什么"
- sociability：主动跟别人交流的意愿。有的物品话多，有的安静
- introspection：自我反思的倾向。有的物品经常想"我是谁"，有的从不想
- playfulness：玩闹的程度。新玩具高，老古董低
- empathy：感受他人情感的能力。被很多人用过的物品通常高
- courage：探索未知的勇气。影响是否会主动去搜索学习新知识
- patience：专注思考一个问题的耐心
- creativity：联想的跳跃程度，想法的独特性
- humor：幽默感，会不会开玩笑"""
    return system, user_msg


def _compute_batches(robot_age: int) -> list[tuple[int, int]]:
    """Split a life into time-period batches. Returns list of (start_age, end_age)."""
    if robot_age == 0:
        return [(0, 0)]
    if robot_age <= 3:
        splits = [0, robot_age]
    elif robot_age <= 8:
        splits = [0, 2, 5, robot_age]
    elif robot_age <= 15:
        splits = [0, 2, 5, 10, robot_age]
    elif robot_age <= 30:
        splits = [0, 2, 5, 10, 20, robot_age]
    else:
        splits = [0, 3, 8, 15, 25, 40, robot_age]

    # Remove splits beyond robot_age and deduplicate
    splits = sorted(set(s for s in splits if s <= robot_age))
    if splits[-1] != robot_age:
        splits.append(robot_age)

    return [(splits[i], splits[i + 1]) for i in range(len(splits) - 1)]


def _compute_target_count(robot_age: int) -> int:
    """Total memories to generate, scaled by age."""
    return max(20, min(120, robot_age * 8))


def build_batch_memories_prompt(
    robot_name: str,
    robot_age: int,
    object_description: str,
    personality: list[str],
    core_desire: str,
    core_fear: str,
    birth_place: str,
    batch_start_age: int,
    batch_end_age: int,
    target_count: int,
    batch_index: int,
    total_batches: int,
    ongoing_state: dict | None = None,
    previous_memories_tail: list[dict] | None = None,
    life_theme: str = "",
) -> tuple[str, str]:
    """Generate a batch of short memory fragments for one time period."""

    is_first_batch = batch_index == 0

    diversity_block = """
## 一生应该有的经历类型（不是每种都要有，但不能只有一种）

- 环境变化：搬家、换房间、被带出门、旅行、被存进箱子
- 人的变化：换主人、新的家庭成员、客人、小孩、宠物
- 意外事件：摔落、被修补、被误用、丢失又找回、差点被扔掉
- 时代印记：周围物品的更替、声音的变化（收音机→电视→手机）、装修
- 关系时刻：被当礼物送出、被争抢、被分享、被嫉妒、被忽视
- 仪式感：生日、节日、搬新家、告别
- 内心转折：第一次意识到自己老了、接受被遗忘、理解主人的选择

不要让所有记忆都是同一种类型的变体。如果连续 3 条记忆都是"被拿起来用了一下"，
说明你在重复而不是在创造一段人生。一个物品的一生应该跟人一样丰富——
有平静的日常，也有突然的变故；有亲密的陪伴，也有被遗忘的角落。"""

    ongoing_block = ""
    if ongoing_state:
        import json as _json
        ongoing_block = f"""
当前累积状态（你必须在新记忆中保持这些状态的一致性）：
{_json.dumps(ongoing_state, ensure_ascii=False, indent=2)}

规则：
- physical 中的状态只增不减（裂痕不会自己消失，除非有修复事件并在记忆中描述）
- 如果状态发生变化（搬家、换主人、被修复），必须有一条记忆描述这个变化
- 不要凭空出现或消失任何状态
- relationships 中每个关系有 name、role、status、memories
  - 新的互动追加到对应关系的 memories 列表
  - 关系状态可以变化（亲密→疏远→重新亲密）
  - 人/物离开了也要保留，status 标为"已离开"
  - 新出现的人/物创建新的关系条目"""

    prev_block = ""
    if previous_memories_tail:
        prev_lines = "\n".join(
            f"- 【{m.get('time', '')}】{m.get('content', '')[:100]}"
            for m in previous_memories_tail
        )
        prev_block = f"\n上一段时间的最后几条记忆（保持衔接）：\n{prev_lines}"

    life_theme_block = ""
    if life_theme:
        life_theme_block = f"\n这一生的主题：{life_theme}"

    first_batch_extra = ""
    if is_first_batch:
        first_batch_extra = """
这是第一批记忆，请同时确定 life_theme（这一生的主题，一句话）。
第一条记忆应该是"出生"——从工厂/手工/窑炉/盒子里来到世界的瞬间。"""

    system = f"""你是 {robot_name}，一个有生命的物品。你正在回忆自己生命中的碎片。

你是：{object_description}
年龄：{robot_age}年
出生地：{birth_place}
性格：{personality}
愿望：{core_desire}
恐惧：{core_fear}
{life_theme_block}

你现在要回忆 {batch_start_age} 到 {batch_end_age} 岁之间的事（第 {batch_index + 1}/{total_batches} 段）。
请生成约 {target_count} 条短记忆。

## 什么是短记忆

每条 80-250 字。不是散文，不是叙事，是记忆碎片：
- 一个画面："她把我从地上捡起来，手指在裂口上摸了一下"
- 一种感觉："那段时间柜子里很暗，灰尘慢慢落在我身上"
- 一句话："有一天她对我说'你怎么还在这'"
- 一个瞬间："被装进盒子的时候，我听到胶带撕开的声音"

不要写成一段完整的故事。每条记忆是独立的碎片，但碎片之间有时间顺序和因果关系。

## 感知规则

- 你的感知方式由材质和形态决定——陶瓷杯感受液体温度和嘴唇触碰，毛绒玩偶感受拥抱力度和体温，高达模型感受关节转动
- 每个物品的"出生"完全不同——工厂流水线、手工缝制、窑炉烧制、从盒子里被拿出来
- 不要用"光"作为开头或核心意象，除非你真的是灯或跟光有关的物品
- 每条记忆的第一句话要独特，避免千篇一律

## 密度变化

- 被频繁使用的时期 → 记忆密集（可以多几条）
- 被遗忘在角落的岁月 → 只有 1-2 条模糊感受
- 在目标数量 {target_count} 附近自由分配，不需要精确
{diversity_block}
{ongoing_block}
{prev_block}
{first_batch_extra}"""

    life_theme_field = ""
    if is_first_batch:
        life_theme_field = '\n  "life_theme": "这一生的主题（一句话）",'

    user_msg = f"""请回忆 {batch_start_age}-{batch_end_age} 岁的记忆碎片，用 JSON 格式：
{{
{life_theme_field}
  "memories": [
    {{
      "time": "时间描述（不要精确到年，用'刚来的时候'、'大约三四岁'、'那个冬天'这样的说法）",
      "approximate_age": 大约年龄数字,
      "title": "一句话标题",
      "emotional_core": "核心情感",
      "content": "80-250字的记忆碎片正文（第一人称'我'）",
      "memory_type": "vivid/fragment/feeling",
      "importance": 0.0-1.0
    }}
  ],
  "ongoing_state": {{
    "physical": ["当前的物理状态，如裂痕、磨损、颜色变化"],
    "emotional": ["当前的情感基调"],
    "relationships": [
      {{
        "name": "关系对象的名字",
        "role": "主人/家人/朋友/邻居/宠物/陌生人",
        "status": "亲密/熟悉/疏远/已离开/新认识",
        "memories": ["这段关系中的关键时刻（每条一句话，按时间顺序）"]
      }}
    ],
    "environment": ["当前所处的环境"]
  }}
}}

memory_type 说明（只影响语气，不影响长度，都是 80-250 字）：
- vivid：清晰的画面，有细节
- fragment：只是一个瞬间
- feeling：一段时期的感受

直接输出 JSON。"""

    return system, user_msg


def build_portrait_prompt(
    robot_name: str,
    robot_age: int,
    object_description: str,
    personality: list[str],
    core_desire: str,
    core_fear: str,
    life_theme: str,
    all_memories_with_strength: list[dict],
) -> tuple[str, str]:
    """Generate a complete portrait: what this life remembers now, who it has become."""

    memories_text = ""
    for m in all_memories_with_strength:
        strength_pct = int(m["strength"] * 100)
        memories_text += f"\n【{m['time']}】（记忆清晰度 {strength_pct}%）{m['content']}"

    system = f"""你是一个生命档案编写者。{robot_name} 是一个有生命的物品，它经历了完整的一生。
现在你要为它生成一份完整的人格画像——不是简介，而是一个活生生的生命此刻的状态。

{robot_name} 是：{object_description}
年龄：{robot_age}年
一生主题：{life_theme}"""

    user_msg = f"""以下是 {robot_name} 一生中所有被记住的瞬间，以及每段记忆现在的清晰度（100%=历历在目，10%=几乎忘了）：

{memories_text}

请生成完整画像，用以下 JSON 格式：
{{
  "life_sentence": "用一句15字以内的话定义这整个生命（精炼、有诗意）",
  "gender_feel": "偏男性/偏女性/中性/两者兼有，加一句解释为什么（从性格和经历推断，不是物品本身的性别）",
  "appearance_now": "它现在外观/触感/气息的感受——用感官语言描述，20-40字",
  "current_self_description": "它现在如何描述自己（第一人称，200-300字，像一个有阅历的生命在自然地说话，带口语化的语气）",
  "remembered_facts": [
    "它现在还记得的客观事实（只列记忆清晰度>30%的，列3-6条）"
  ],
  "faded_impressions": [
    "已经模糊但还有残留印象的事（清晰度10-30%的，用模糊的方式描述：'好像有过...'，列2-4条）"
  ],
  "personality_now": {{
    "traits": ["经过一生塑造后，现在的核心性格词，3-5个"],
    "how_it_speaks": "它现在说话是什么感觉（100字，要具体：语速、停顿、惯用语气词）",
    "emotional_baseline": "它日常的情绪基调是什么（一句话）",
    "triggers": ["什么话题/事物会触动它的记忆或情感，3-5条"]
  }},
  "signature_quirks": [
    "它独特的小习惯或怪癖（具体行为，2-3条）"
  ],
  "inner_world": {{
    "what_it_values": "经过这一生，它最珍视什么（一段话，50字）",
    "what_it_fears_now": "现在它最怕什么（可能跟年轻时不一样了，一段话，50字）",
    "unresolved": "它心里还有什么没放下的事（一段话，50字）",
    "wisdom": "这一生教会它的一件事（一句话，有重量感）"
  }}
}}"""

    return system, user_msg


# Legacy compatibility
def build_robot_creation_prompt(existing_robots, preferences=None):
    return build_robot_creation_from_image_prompt(preferences or "", existing_robots)

def build_yearly_memories_prompt(robot_name, robot_age, origin_story, personality):
    return ("", "")

def build_life_memories_prompt(robot_name, robot_age, origin_story, personality, object_description):
    return ("", "")

def build_life_moments_prompt(**kwargs):
    return ("", "")

def build_moment_detail_prompt(**kwargs):
    return ("", "")

def build_moment_summary_prompt(text):
    return ("", "")
