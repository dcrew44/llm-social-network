"""Event models and append helpers for the event log."""

import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events in the system."""

    TIMELINE_SERVED = "timeline_served"
    ACTION = "action"
    ADVANCE_TICK = "advance_tick"
    RUN_STARTED = "run_started"
    RUN_CONFIG = "run_config"
    USER_CREATED = "user_created"


class ActionType(str, Enum):
    """Types of actions an agent can take."""

    POST = "post"
    COMMENT = "comment"
    LIKE = "like"
    UNLIKE = "unlike"
    FOLLOW = "follow"
    UNFOLLOW = "unfollow"


class ActionStatus(str, Enum):
    """Status of an action."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


def utc_now() -> str:
    """Return current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def new_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid4())


class Event(BaseModel):
    """Base event model."""

    event_id: str = Field(default_factory=new_uuid)
    event_type: EventType
    tick: int
    actor_id: str | None = None
    op_id: str | None = None
    timeline_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    ranking_version: str | None = None
    status: ActionStatus | None = None
    created_at: str = Field(default_factory=utc_now)
    seed: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TimelineItem(BaseModel):
    """A single item in a timeline."""

    post_id: str
    position: int
    score: float
    features: dict[str, float] = Field(default_factory=dict)


class TimelineServedPayload(BaseModel):
    """Payload for timeline_served events."""

    items: list[TimelineItem]
    k: int
    algorithm: str


class ActionPayload(BaseModel):
    """Payload for action events."""

    action_type: ActionType
    target_id: str | None = None
    position: int | None = None
    content: str | None = None
    reason: str | None = None


class RunConfigPayload(BaseModel):
    """Payload for run_config events."""

    num_agents: int
    num_ticks: int
    k: int
    ranking_algorithm: str
    seed: int


def append_event(conn: sqlite3.Connection, event: Event) -> int:
    """Append an event to the event log. Returns the sequence number."""
    cursor = conn.execute(
        """
        INSERT INTO events (
            event_id, event_type, tick, actor_id, op_id, timeline_id,
            model_id, prompt_version, ranking_version, status, created_at,
            seed, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.event_type.value,
            event.tick,
            event.actor_id,
            event.op_id,
            event.timeline_id,
            event.model_id,
            event.prompt_version,
            event.ranking_version,
            event.status.value if event.status else None,
            event.created_at,
            event.seed,
            json.dumps(event.payload),
        ),
    )
    return cursor.lastrowid or 0


def get_events(
    conn: sqlite3.Connection,
    event_type: EventType | None = None,
    from_seq: int = 0,
) -> list[dict[str, Any]]:
    """Retrieve events from the log, optionally filtered by type."""
    query = "SELECT * FROM events WHERE seq > ?"
    params: list[Any] = [from_seq]

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type.value)

    query += " ORDER BY seq"
    rows = conn.execute(query, params).fetchall()

    return [
        {
            "seq": row["seq"],
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "tick": row["tick"],
            "actor_id": row["actor_id"],
            "op_id": row["op_id"],
            "timeline_id": row["timeline_id"],
            "model_id": row["model_id"],
            "prompt_version": row["prompt_version"],
            "ranking_version": row["ranking_version"],
            "status": row["status"],
            "created_at": row["created_at"],
            "seed": row["seed"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def op_id_exists(conn: sqlite3.Connection, op_id: str) -> bool:
    """Check if an operation ID already exists (for idempotency)."""
    row = conn.execute(
        "SELECT 1 FROM events WHERE op_id = ?", (op_id,)
    ).fetchone()
    return row is not None
