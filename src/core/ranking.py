"""Deterministic ranking algorithms for timeline generation."""

import math
import random
from typing import Any


def rank_new(posts: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Rank by newest first (created_tick descending)."""
    # Use seed for tie-breaking determinism
    rng = random.Random(seed)

    def sort_key(p: dict[str, Any]) -> tuple[int, float]:
        return (-p["created_tick"], rng.random())

    return sorted(posts, key=sort_key)


def rank_top(posts: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Rank by top score (up_votes descending)."""
    rng = random.Random(seed)

    def sort_key(p: dict[str, Any]) -> tuple[int, float]:
        return (-p["up_votes"], rng.random())

    return sorted(posts, key=sort_key)


def rank_hot(
    posts: list[dict[str, Any]], current_tick: int, seed: int
) -> list[dict[str, Any]]:
    """
    Rank by 'hot' algorithm.

    Score = log10(max(ups, 1)) + age_factor
    where age_factor = -0.1 * (current_tick - created_tick)

    This balances engagement with recency.
    """
    rng = random.Random(seed)

    def hot_score(p: dict[str, Any]) -> float:
        ups = max(p["up_votes"], 1)
        age = current_tick - p["created_tick"]
        return math.log10(ups) - 0.1 * age

    def sort_key(p: dict[str, Any]) -> tuple[float, float]:
        return (-hot_score(p), rng.random())

    return sorted(posts, key=sort_key)


def compute_score(
    post: dict[str, Any], algorithm: str, current_tick: int
) -> float:
    """Compute the ranking score for a single post."""
    if algorithm == "new":
        return float(post["created_tick"])
    elif algorithm == "top":
        return float(post["up_votes"])
    elif algorithm == "hot":
        ups = max(post["up_votes"], 1)
        age = current_tick - post["created_tick"]
        return math.log10(ups) - 0.1 * age
    else:
        raise ValueError(f"Unknown ranking algorithm: {algorithm}")


def rank_posts(
    posts: list[dict[str, Any]],
    algorithm: str,
    current_tick: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Rank posts using the specified algorithm."""
    if algorithm == "new":
        return rank_new(posts, seed)
    elif algorithm == "top":
        return rank_top(posts, seed)
    elif algorithm == "hot":
        return rank_hot(posts, current_tick, seed)
    else:
        raise ValueError(f"Unknown ranking algorithm: {algorithm}")


RANKING_VERSION = "v1.0"
