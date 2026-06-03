import uuid

from app.schemas import ObjectObserveRequest, RobotCreate


def test_robot_create_defaults():
    req = RobotCreate()
    assert req.count == 3
    assert req.preferences is None


def test_robot_create_custom():
    req = RobotCreate(count=2, preferences="cute and playful")
    assert req.count == 2


def test_object_observe_request_text():
    req = ObjectObserveRequest(text_description="a red cup")
    assert req.text_description == "a red cup"
    assert req.image_url is None


def test_object_observe_request_image():
    req = ObjectObserveRequest(image_url="https://example.com/cup.jpg")
    assert req.image_url is not None
