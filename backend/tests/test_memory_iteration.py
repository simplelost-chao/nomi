import pytest


def test_update_utility_used_increases():
    from app.services.memory_iteration import update_utility
    assert update_utility(0.0, True, alpha=0.3) == pytest.approx(0.3)


def test_update_utility_unused_decreases():
    from app.services.memory_iteration import update_utility
    assert update_utility(1.0, False, alpha=0.3) == pytest.approx(0.7)


def test_update_utility_converges_toward_one():
    from app.services.memory_iteration import update_utility
    u = 0.0
    for _ in range(50):
        u = update_utility(u, True, alpha=0.3)
    assert u > 0.99


def test_recency_decay_now_is_one():
    from app.services.memory_iteration import recency_decay
    assert recency_decay(0.0) == pytest.approx(1.0)


def test_recency_decay_half_life():
    from app.services.memory_iteration import recency_decay
    assert recency_decay(168.0, half_life_hours=168.0) == pytest.approx(0.5)


def test_hybrid_score_weights_sum_applied():
    from app.services.memory_iteration import hybrid_score, HYBRID_WEIGHTS
    s = hybrid_score(1.0, 1.0, 1.0, 1.0)
    assert s == pytest.approx(sum(HYBRID_WEIGHTS))


def test_hybrid_score_prefers_higher_utility():
    from app.services.memory_iteration import hybrid_score
    low = hybrid_score(0.8, 0.5, 0.0, 0.5)
    high = hybrid_score(0.8, 0.5, 1.0, 0.5)
    assert high > low


def test_should_forget_consolidated_is_true():
    import uuid
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=uuid.uuid4(), utility_score=0.9,
                        importance_score=0.9, created_at=datetime(2026, 1, 1), archived=False)
    assert should_forget(m, datetime(2026, 6, 4)) is True


def test_should_forget_high_value_kept():
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=None, utility_score=0.8,
                        importance_score=0.8, created_at=datetime(2026, 1, 1), archived=False)
    assert should_forget(m, datetime(2026, 6, 4)) is False


def test_should_forget_low_value_old_is_true():
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=None, utility_score=0.0,
                        importance_score=0.1, created_at=datetime(2026, 1, 1), archived=False)
    assert should_forget(m, datetime(2026, 6, 4)) is True


def test_should_forget_already_archived_is_false():
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=None, utility_score=0.0,
                        importance_score=0.0, created_at=datetime(2026, 1, 1), archived=True)
    assert should_forget(m, datetime(2026, 6, 4)) is False


class _Item:
    def __init__(self, name, embedding):
        self.name = name
        self.embedding = embedding


def test_cluster_groups_near_duplicates():
    from app.services.memory_iteration import cluster_by_similarity
    items = [
        _Item("a", [1.0, 0.0, 0.0]),
        _Item("a2", [0.99, 0.01, 0.0]),
        _Item("b", [0.0, 1.0, 0.0]),
    ]
    clusters = cluster_by_similarity(items, threshold=0.95)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_cluster_singletons_when_all_different():
    from app.services.memory_iteration import cluster_by_similarity
    items = [_Item("a", [1.0, 0.0]), _Item("b", [0.0, 1.0])]
    clusters = cluster_by_similarity(items, threshold=0.95)
    assert len(clusters) == 2


class _Mem:
    def __init__(self, name, embedding, importance, utility, last_activated):
        self.name = name
        self.embedding = embedding
        self.importance_score = importance
        self.utility_score = utility
        self.last_activated = last_activated
        self.created_at = last_activated


def test_rerank_prefers_useful_over_pure_cosine():
    from datetime import datetime
    from app.services.memory_iteration import rerank_candidates
    now = datetime(2026, 6, 4)
    q = [1.0, 0.0]
    m_close = _Mem("close", [1.0, 0.0], importance=0.3, utility=0.0, last_activated=now)
    m_useful = _Mem("useful", [0.9, 0.1], importance=0.9, utility=0.9, last_activated=now)
    ranked = rerank_candidates([m_close, m_useful], q, now, limit=1)
    assert ranked[0].name == "useful"


def test_rerank_respects_limit():
    from datetime import datetime
    from app.services.memory_iteration import rerank_candidates
    now = datetime(2026, 6, 4)
    mems = [_Mem(str(i), [1.0, 0.0], 0.5, 0.5, now) for i in range(5)]
    assert len(rerank_candidates(mems, [1.0, 0.0], now, limit=3)) == 3
