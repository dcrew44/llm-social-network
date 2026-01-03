"""Projection management: rebuild state from events."""

import json
import sqlite3
from typing import Any

from .db import drop_projections, recreate_projections
from .events import ActionStatus, ActionType, EventType, get_events


def apply_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    """Apply a single event to the projections."""
    event_type = event["event_type"]
    payload = event["payload"]

    if event_type == EventType.USER_CREATED.value:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (user_id, username, created_tick, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                event["actor_id"],
                payload.get("username", f"user_{event['actor_id'][:8]}"),
                event["tick"],
                event["created_at"],
            ),
        )

    elif event_type == EventType.ACTION.value and event["status"] == ActionStatus.ACCEPTED.value:
        action_type = payload.get("action_type")

        if action_type == ActionType.POST.value:
            conn.execute(
                """
                INSERT INTO posts (post_id, author_id, content, created_tick, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["target_id"],
                    event["actor_id"],
                    payload.get("content", ""),
                    event["tick"],
                    event["created_at"],
                ),
            )

        elif action_type == ActionType.COMMENT.value:
            conn.execute(
                """
                INSERT INTO comments
                (comment_id, post_id, author_id, content, created_tick, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("comment_id", event["event_id"]),
                    payload["target_id"],
                    event["actor_id"],
                    payload.get("content", ""),
                    event["tick"],
                    event["created_at"],
                ),
            )

        elif action_type == ActionType.LIKE.value:
            conn.execute(
                """
                INSERT OR IGNORE INTO votes
                (vote_id, post_id, user_id, vote_type, created_tick, created_at)
                VALUES (?, ?, ?, 'up', ?, ?)
                """,
                (
                    event["event_id"],
                    payload["target_id"],
                    event["actor_id"],
                    event["tick"],
                    event["created_at"],
                ),
            )

        elif action_type == ActionType.UNLIKE.value:
            conn.execute(
                "DELETE FROM votes WHERE post_id = ? AND user_id = ?",
                (payload["target_id"], event["actor_id"]),
            )

        elif action_type == ActionType.FOLLOW.value:
            conn.execute(
                """
                INSERT OR IGNORE INTO follows (follower_id, followee_id, created_tick, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event["actor_id"],
                    payload["target_id"],
                    event["tick"],
                    event["created_at"],
                ),
            )

        elif action_type == ActionType.UNFOLLOW.value:
            conn.execute(
                "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
                (event["actor_id"], payload["target_id"]),
            )


def replay_all(conn: sqlite3.Connection) -> int:
    """Drop and rebuild all projections from the event log. Returns event count."""
    drop_projections(conn)
    recreate_projections(conn)

    events = get_events(conn)
    for event in events:
        apply_event(conn, event)

    return len(events)


def get_projection_hash(conn: sqlite3.Connection) -> str:
    """Compute a deterministic hash of projection state for verification."""
    import hashlib

    h = hashlib.sha256()

    for table in ["users", "posts", "comments", "votes", "follows"]:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for row in rows:
            h.update(json.dumps(dict(row), sort_keys=True).encode())

    return h.hexdigest()


def get_post_stats(conn: sqlite3.Connection, post_id: str) -> dict[str, int]:
    """Get vote and comment counts for a post."""
    up_votes = conn.execute(
        "SELECT COUNT(*) FROM votes WHERE post_id = ? AND vote_type = 'up'",
        (post_id,),
    ).fetchone()[0]

    comments = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_id = ?",
        (post_id,),
    ).fetchone()[0]

    return {"up_votes": up_votes, "comments": comments}


def user_has_liked(conn: sqlite3.Connection, user_id: str, post_id: str) -> bool:
    """Check if a user has already liked a post."""
    row = conn.execute(
        "SELECT 1 FROM votes WHERE user_id = ? AND post_id = ? AND vote_type = 'up'",
        (user_id, post_id),
    ).fetchone()
    return row is not None


def user_follows(conn: sqlite3.Connection, follower_id: str, followee_id: str) -> bool:
    """Check if one user follows another."""
    row = conn.execute(
        "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
        (follower_id, followee_id),
    ).fetchone()
    return row is not None


def post_exists(conn: sqlite3.Connection, post_id: str) -> bool:
    """Check if a post exists."""
    row = conn.execute(
        "SELECT 1 FROM posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None


def user_exists(conn: sqlite3.Connection, user_id: str) -> bool:
    """Check if a user exists."""
    row = conn.execute(
        "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row is not None


def get_candidate_posts(
    conn: sqlite3.Connection, tick: int, limit: int = 100
) -> list[dict[str, Any]]:
    """Get candidate posts for timeline ranking."""
    rows = conn.execute(
        """
        SELECT p.post_id, p.author_id, p.content, p.created_tick, p.created_at,
               COALESCE(v.up_count, 0) as up_votes,
               COALESCE(c.comment_count, 0) as comments
        FROM posts p
        LEFT JOIN (
            SELECT post_id, COUNT(*) as up_count
            FROM votes WHERE vote_type = 'up'
            GROUP BY post_id
        ) v ON p.post_id = v.post_id
        LEFT JOIN (
            SELECT post_id, COUNT(*) as comment_count
            FROM comments
            GROUP BY post_id
        ) c ON p.post_id = c.post_id
        WHERE p.created_tick <= ?
        ORDER BY p.created_tick DESC
        LIMIT ?
        """,
        (tick, limit),
    ).fetchall()

    return [
        {
            "post_id": row["post_id"],
            "author_id": row["author_id"],
            "content": row["content"],
            "created_tick": row["created_tick"],
            "created_at": row["created_at"],
            "up_votes": row["up_votes"],
            "comments": row["comments"],
        }
        for row in rows
    ]
