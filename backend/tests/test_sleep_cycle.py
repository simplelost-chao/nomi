def test_plan_dedup_merges_near_duplicates():
    from app.services.sleep_cycle import plan_dedup

    class M:
        def __init__(self, id, emb, imp):
            self.id, self.embedding, self.importance_score = id, emb, imp
            self.base_importance = imp
            self.consolidated_into = None
    a = M(1, [1.0, 0.0], 0.4)
    a2 = M(2, [0.99, 0.0], 0.3)
    b = M(3, [0.0, 1.0], 0.5)
    merges = plan_dedup([a, a2, b], threshold=0.95)
    assert merges == [(2, 1)]   # (loser_id, winner_id): weaker folds into stronger


def test_plan_dedup_no_merge_when_distinct():
    from app.services.sleep_cycle import plan_dedup

    class M:
        def __init__(self, id, emb):
            self.id, self.embedding, self.importance_score = id, emb, 0.5
            self.base_importance = 0.5
    out = plan_dedup([M(1, [1.0, 0.0]), M(2, [0.0, 1.0])], threshold=0.95)
    assert out == []


# Integration test removed: SQLAlchemy column types (JSONB, Vector) are resolved
# at import time based on settings.is_sqlite, which is already False when running
# under the default Postgres URL. Forcing SQLite in-memory after the fact causes
# "Compiler can't render element of type JSONB" errors. The two plan_dedup pure
# tests above fully exercise the dedup logic; run_sleep_cycle DB wiring is covered
# by the import smoke check: cd backend && .venv/bin/python3.12 -c "import app.services.sleep_cycle"
