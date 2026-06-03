"""Pure, testable helpers for the self-iterating memory system (P1).

No DB/IO, so these are unit-tested directly, mirroring
app.services.memory.cosine_similarity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.memory import cosine_similarity


def update_utility(old_utility: float, used: bool, alpha: float = 0.3) -> float:
    """EMA of a memory's usefulness; used=True → toward 1.0, else toward 0.0."""
    target = 1.0 if used else 0.0
    return (1.0 - alpha) * old_utility + alpha * target


def recency_decay(hours_since: float, half_life_hours: float = 168.0) -> float:
    """1.0 at 0h, 0.5 at half_life (default 7 days), asymptotes to 0."""
    if hours_since <= 0:
        return 1.0
    return 0.5 ** (hours_since / half_life_hours)


# weights: (cosine, importance, utility, recency)
HYBRID_WEIGHTS: tuple[float, float, float, float] = (0.5, 0.2, 0.2, 0.1)


def hybrid_score(
    cosine_sim: float,
    importance: float,
    utility: float,
    recency: float,
    weights: tuple[float, float, float, float] = HYBRID_WEIGHTS,
) -> float:
    """Weighted blend of semantic similarity + pragmatic signals."""
    w1, w2, w3, w4 = weights
    return w1 * cosine_sim + w2 * importance + w3 * utility + w4 * recency


@dataclass
class ForgetCandidate:
    consolidated_into: object  # uuid.UUID | None
    utility_score: float
    importance_score: float
    created_at: datetime
    archived: bool


def should_forget(
    m: ForgetCandidate,
    now: datetime,
    *,
    age_days: float = 30.0,
    util_floor: float = 0.1,
    importance_floor: float = 0.2,
) -> bool:
    """Safe-forget predicate. Never forgets recent/useful/important memories.

    Archive only when already absorbed by a consolidation, OR
    low utility AND low importance AND old (all three).
    """
    if m.archived:
        return False
    if m.consolidated_into is not None:
        return True
    age = (now - m.created_at).total_seconds() / 86400.0
    return (
        m.utility_score < util_floor
        and m.importance_score < importance_floor
        and age > age_days
    )


def rerank_candidates(candidates: list, query_embedding: list[float], now: datetime,
                      limit: int, weights: tuple[float, float, float, float] = HYBRID_WEIGHTS) -> list:
    """Re-rank already-fetched memory candidates by hybrid_score; return top `limit`.

    Each candidate needs: .embedding, .importance_score, .utility_score,
    .last_activated (or .created_at).
    """
    scored = []
    for m in candidates:
        if m.embedding is None:
            continue
        cos = cosine_similarity(query_embedding, m.embedding)
        last = getattr(m, "last_activated", None) or getattr(m, "created_at", None) or now
        hours = max(0.0, (now - last).total_seconds() / 3600.0)
        score = hybrid_score(
            cos,
            m.importance_score or 0.0,
            getattr(m, "utility_score", 0.0) or 0.0,
            recency_decay(hours),
            weights,
        )
        scored.append((m, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [m for m, _ in scored[:limit]]


LAYER_BOOST = {"principle": 0.25, "semantic": 0.1, "episodic": 0.0}


def allocate_layer_budget(principles: int = 2, semantic: int = 2, episodic: int = 2) -> dict:
    """Per-layer retrieval budget for prompt injection."""
    return {"principle": principles, "semantic": semantic, "episodic": episodic}


def apply_layer_boost(score: float, layer: str) -> float:
    """Constant retrieval boost by layer (principles are near-always-on)."""
    return score + LAYER_BOOST.get(layer or "episodic", 0.0)


def cluster_by_similarity(items: list, threshold: float = 0.92) -> list[list]:
    """Greedy single-pass clustering by cosine of each item's `.embedding`.

    Joins the first cluster whose representative (first member) is >= threshold,
    else starts a new cluster. Items without embedding become singletons.
    """
    clusters: list[list] = []
    for item in items:
        emb = getattr(item, "embedding", None)
        placed = False
        if emb is not None:
            for cluster in clusters:
                rep_emb = getattr(cluster[0], "embedding", None)
                if rep_emb is not None and cosine_similarity(rep_emb, emb) >= threshold:
                    cluster.append(item)
                    placed = True
                    break
        if not placed:
            clusters.append([item])
    return clusters
