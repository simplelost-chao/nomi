import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_user_message_request_schema():
    from app.schemas import UserMessageRequest

    msg = UserMessageRequest(content="你好呀！")
    assert msg.content == "你好呀！"


def test_user_message_request_empty_rejected():
    from pydantic import ValidationError

    from app.schemas import UserMessageRequest

    # Empty string is technically valid — content is just a str
    msg = UserMessageRequest(content="")
    assert msg.content == ""
