"""
SQLite-compatible column types that replace PostgreSQL-specific types.
When using PostgreSQL, the original types are used.
When using SQLite, these portable alternatives are used.
"""
import json
from sqlalchemy import JSON, Text, TypeDecorator


class PortableJSON(TypeDecorator):
    """Uses JSONB on PostgreSQL, JSON on SQLite."""
    impl = JSON
    cache_ok = True


class PortableArray(TypeDecorator):
    """Stores arrays as JSON on SQLite, uses ARRAY on PostgreSQL."""
    impl = Text
    cache_ok = True

    def __init__(self, item_type=None):
        super().__init__()
        self.item_type = item_type

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class PortableVector(TypeDecorator):
    """Stores embedding vectors as JSON text on SQLite."""
    impl = Text
    cache_ok = True

    def __init__(self, dimensions=None):
        super().__init__()
        self.dimensions = dimensions

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)
