from app.prompts.creation import build_robot_creation_prompt
from app.prompts.director import build_director_prompt, build_speaker_prompt
from app.prompts.imagination import build_imagination_prompt


def test_creation_prompt_contains_existing_robots():
    existing = [{"name": "Momo", "personality": ["温柔", "敏感"]}]
    system, user_msg = build_robot_creation_prompt(
        existing_robots=existing, preferences="cute"
    )
    assert "Momo" in system
    assert "cute" in user_msg


def test_creation_prompt_empty_existing():
    system, user_msg = build_robot_creation_prompt(existing_robots=[])
    assert "Momo" not in system


def test_imagination_prompt_includes_robot_context():
    system, user_msg = build_imagination_prompt(
        robot_name="Momo",
        robot_personality=["温柔", "敏感"],
        origin_story="出生在钟表店",
        speaking_style={"speed": "slow"},
        memories=["记得一只蝴蝶"],
        object_description="一个红色杯子",
    )
    assert "Momo" in system
    assert "红色杯子" in user_msg


def test_director_prompt_includes_participants():
    system, user_msg = build_director_prompt(
        topic="讨论一个红色杯子",
        robots=[
            {"name": "Momo", "personality": ["温柔"]},
            {"name": "Kiki", "personality": ["活泼"]},
        ],
        relationships=[{"pair": "Momo-Kiki", "intimacy": 0.7}],
        conversation_so_far=[],
    )
    assert "Momo" in system
    assert "Kiki" in system


def test_speaker_prompt_includes_director_note():
    system, user_msg = build_speaker_prompt(
        robot_name="Momo",
        robot_personality=["温柔"],
        origin_story="出生在钟表店",
        speaking_style={"speed": "slow"},
        memories=["记得一只蝴蝶"],
        relationships=[{"with": "Kiki", "intimacy": 0.7}],
        conversation_so_far=[{"sender": "Kiki", "content": "你看这个杯子!"}],
        director_note="Momo should respond gently, connecting to a childhood memory",
    )
    assert "Momo" in system
    assert "childhood memory" in user_msg
