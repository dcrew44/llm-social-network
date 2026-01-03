"""KPI metrics: Gini coefficient and entropy calculations."""

import math
import sqlite3
from collections import Counter
from typing import Any


def gini_coefficient(values: list[float]) -> float:
    """
    Calculate the Gini coefficient for a list of values.

    Returns a value between 0 (perfect equality) and 1 (perfect inequality).
    """
    if not values or len(values) == 0:
        return 0.0

    n = len(values)
    if n == 1:
        return 0.0

    sorted_values = sorted(values)
    cumsum = 0.0
    for i, v in enumerate(sorted_values):
        cumsum += (2 * (i + 1) - n - 1) * v

    mean = sum(values) / n
    if mean == 0:
        return 0.0

    return cumsum / (n * n * mean)


def entropy(counts: list[int]) -> float:
    """
    Calculate Shannon entropy for a distribution.

    Returns entropy in bits.
    """
    if not counts:
        return 0.0

    total = sum(counts)
    if total == 0:
        return 0.0

    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)

    return h


def attention_gini(conn: sqlite3.Connection) -> float:
    """
    Calculate Gini coefficient for attention distribution.

    Attention is measured by total engagement (likes + comments) per post.
    """
    rows = conn.execute(
        """
        SELECT p.post_id,
               COALESCE(v.likes, 0) + COALESCE(c.comments, 0) as engagement
        FROM posts p
        LEFT JOIN (
            SELECT post_id, COUNT(*) as likes FROM votes WHERE vote_type = 'up'
            GROUP BY post_id
        ) v ON p.post_id = v.post_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) as comments FROM comments
            GROUP BY post_id
        ) c ON p.post_id = c.post_id
        """
    ).fetchall()

    if not rows:
        return 0.0

    engagements = [float(row["engagement"]) for row in rows]
    return gini_coefficient(engagements)


def author_attention_gini(conn: sqlite3.Connection) -> float:
    """
    Calculate Gini coefficient for attention per author.

    This measures how evenly attention is distributed across content creators.
    """
    rows = conn.execute(
        """
        SELECT p.author_id,
               SUM(COALESCE(v.likes, 0) + COALESCE(c.comments, 0)) as total_engagement
        FROM posts p
        LEFT JOIN (
            SELECT post_id, COUNT(*) as likes FROM votes WHERE vote_type = 'up'
            GROUP BY post_id
        ) v ON p.post_id = v.post_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) as comments FROM comments
            GROUP BY post_id
        ) c ON p.post_id = c.post_id
        GROUP BY p.author_id
        """
    ).fetchall()

    if not rows:
        return 0.0

    engagements = [float(row["total_engagement"]) for row in rows]
    return gini_coefficient(engagements)


def topic_entropy(conn: sqlite3.Connection) -> float:
    """
    Calculate entropy of topic distribution.

    Uses dummy topic extraction (first word of content) for now.
    """
    rows = conn.execute("SELECT content FROM posts").fetchall()

    if not rows:
        return 0.0

    # Dummy topic extraction: use first word
    topics: list[str] = []
    for row in rows:
        content = row["content"]
        if content:
            words = content.split()
            if words:
                topics.append(words[0].lower())

    if not topics:
        return 0.0

    topic_counts = Counter(topics)
    return entropy(list(topic_counts.values()))


def compute_kpis(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute all KPIs and return as a dictionary."""
    # Basic counts
    post_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    vote_count = conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
    comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    follow_count = conn.execute("SELECT COUNT(*) FROM follows").fetchone()[0]

    # Action status breakdown
    action_stats = conn.execute(
        """
        SELECT status, json_extract(payload_json, '$.reason') as reason, COUNT(*) as count
        FROM events
        WHERE event_type = 'action'
        GROUP BY status, json_extract(payload_json, '$.reason')
        ORDER BY count DESC
        """
    ).fetchall()

    action_breakdown = {
        "accepted": 0,
        "rejected": 0,
        "rejection_reasons": {},
    }

    for row in action_stats:
        status = row["status"]
        reason = row["reason"]
        count = row["count"]

        if status == "accepted":
            action_breakdown["accepted"] += count
        elif status == "rejected":
            action_breakdown["rejected"] += count
            action_breakdown["rejection_reasons"][reason or "unknown"] = count

    return {
        "counts": {
            "posts": post_count,
            "users": user_count,
            "votes": vote_count,
            "comments": comment_count,
            "follows": follow_count,
        },
        "actions": action_breakdown,
        "attention_gini": attention_gini(conn),
        "author_attention_gini": author_attention_gini(conn),
        "topic_entropy": topic_entropy(conn),
    }


def kpis_over_ticks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Compute KPIs at each tick for time-series analysis.

    Note: This is a simplified version that computes based on created_tick.
    """
    max_tick_row = conn.execute(
        "SELECT MAX(created_tick) as max_tick FROM posts"
    ).fetchone()

    if not max_tick_row or max_tick_row["max_tick"] is None:
        return []

    max_tick = max_tick_row["max_tick"]
    results = []

    for tick in range(max_tick + 1):
        # Get engagement up to this tick
        rows = conn.execute(
            """
            SELECT p.post_id,
                   COALESCE(v.likes, 0) + COALESCE(c.comments, 0) as engagement
            FROM posts p
            LEFT JOIN (
                SELECT post_id, COUNT(*) as likes FROM votes
                WHERE vote_type = 'up' AND created_tick <= ?
                GROUP BY post_id
            ) v ON p.post_id = v.post_id
            LEFT JOIN (
                SELECT post_id, COUNT(*) as comments FROM comments
                WHERE created_tick <= ?
                GROUP BY post_id
            ) c ON p.post_id = c.post_id
            WHERE p.created_tick <= ?
            """,
            (tick, tick, tick),
        ).fetchall()

        if rows:
            engagements = [float(row["engagement"]) for row in rows]
            gini = gini_coefficient(engagements)
        else:
            gini = 0.0

        results.append({
            "tick": tick,
            "attention_gini": gini,
            "post_count": len(rows),
        })

    return results
