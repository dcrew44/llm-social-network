"""API-shaped in-process functions for the simulation."""

import sqlite3

from pydantic import BaseModel, Field

from src.core.events import (
    ActionPayload,
    ActionStatus,
    ActionType,
    Event,
    EventType,
    TimelineItem,
    TimelineServedPayload,
    append_event,
    new_uuid,
    op_id_exists,
)
from src.core.projections import (
    apply_event,
    get_candidate_posts,
    post_exists,
    user_exists,
    user_follows,
    user_has_liked,
)
from src.core.ranking import RANKING_VERSION, compute_score, rank_posts


class Timeline(BaseModel):
    """Response from timeline() API."""

    timeline_id: str
    items: list[TimelineItem]
    tick: int
    k: int


class Action(BaseModel):
    """Request to act() API."""

    actor_id: str
    op_id: str
    timeline_id: str
    action_type: ActionType
    target_id: str | None = None
    position: int | None = None
    content: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None


class ActionResult(BaseModel):
    """Response from act() API."""

    status: ActionStatus
    reason: str | None = None
    event_id: str | None = None


class SimulationContext(BaseModel):
    """Context for a simulation run."""

    model_config = {"arbitrary_types_allowed": True}

    tick: int = 0
    seed: int = 42
    ranking_algorithm: str = "hot"
    default_k: int = 10

    # Track timeline exposures: timeline_id -> set of post_ids
    exposures: dict[str, set[str]] = Field(default_factory=dict)


# Global exposure tracking (in-memory for simplicity)
_timeline_exposures: dict[str, set[str]] = {}


def timeline(
    conn: sqlite3.Connection,
    agent_id: str,
    tick: int,
    k: int = 10,
    algorithm: str = "hot",
    seed: int = 42,
    model_id: str | None = None,
    prompt_version: str | None = None,
) -> Timeline:
    """
    Generate a ranked timeline for an agent.

    Computes candidate posts from projections, ranks them, emits a
    timeline_served event, and returns the timeline.
    """
    # Get candidate posts
    candidates = get_candidate_posts(conn, tick, limit=100)

    # Rank them deterministically
    ranked = rank_posts(candidates, algorithm, tick, seed)

    # Take top k
    top_k = ranked[:k]

    # Build timeline items with scores and features
    items = [
        TimelineItem(
            post_id=post["post_id"],
            position=i,
            score=compute_score(post, algorithm, tick),
            features={
                "up_votes": float(post["up_votes"]),
                "comments": float(post["comments"]),
                "age": float(tick - post["created_tick"]),
            },
        )
        for i, post in enumerate(top_k)
    ]

    # Generate timeline ID
    timeline_id = new_uuid()

    # Record exposures for validation
    _timeline_exposures[timeline_id] = {item.post_id for item in items}

    # Create and append timeline_served event
    event = Event(
        event_type=EventType.TIMELINE_SERVED,
        tick=tick,
        actor_id=agent_id,
        timeline_id=timeline_id,
        model_id=model_id,
        prompt_version=prompt_version,
        ranking_version=RANKING_VERSION,
        seed=seed,
        payload=TimelineServedPayload(
            items=items,
            k=k,
            algorithm=algorithm,
        ).model_dump(),
    )
    append_event(conn, event)

    return Timeline(
        timeline_id=timeline_id,
        items=items,
        tick=tick,
        k=k,
    )


def act(conn: sqlite3.Connection, action: Action, tick: int) -> ActionResult:
    """
    Process an agent action.

    Validates idempotency, exposure tie, and business rules.
    Emits an action event with accepted/rejected status.
    """
    # Check idempotency
    if op_id_exists(conn, action.op_id):
        return ActionResult(status=ActionStatus.REJECTED, reason="duplicate_op_id")

    status = ActionStatus.ACCEPTED
    reason: str | None = None

    # Validate exposure tie for actions that require it
    if action.action_type in [ActionType.LIKE, ActionType.UNLIKE, ActionType.COMMENT]:
        if action.timeline_id not in _timeline_exposures:
            status = ActionStatus.REJECTED
            reason = "invalid_timeline_id"
        elif action.target_id not in _timeline_exposures.get(action.timeline_id, set()):
            status = ActionStatus.REJECTED
            reason = "target_not_in_timeline"

    # Validate target exists
    if status == ActionStatus.ACCEPTED and action.target_id:
        if action.action_type in [ActionType.LIKE, ActionType.UNLIKE, ActionType.COMMENT]:
            if not post_exists(conn, action.target_id):
                status = ActionStatus.REJECTED
                reason = "post_not_found"
        elif action.action_type in [ActionType.FOLLOW, ActionType.UNFOLLOW]:
            if not user_exists(conn, action.target_id):
                status = ActionStatus.REJECTED
                reason = "user_not_found"

    # Business rule validation
    if status == ActionStatus.ACCEPTED:
        if action.action_type == ActionType.LIKE:
            if user_has_liked(conn, action.actor_id, action.target_id or ""):
                status = ActionStatus.REJECTED
                reason = "already_liked"
        elif action.action_type == ActionType.UNLIKE:
            if not user_has_liked(conn, action.actor_id, action.target_id or ""):
                status = ActionStatus.REJECTED
                reason = "not_liked"
        elif action.action_type == ActionType.FOLLOW:
            if action.actor_id == action.target_id:
                status = ActionStatus.REJECTED
                reason = "cannot_follow_self"
            elif user_follows(conn, action.actor_id, action.target_id or ""):
                status = ActionStatus.REJECTED
                reason = "already_following"
        elif action.action_type == ActionType.UNFOLLOW:
            if not user_follows(conn, action.actor_id, action.target_id or ""):
                status = ActionStatus.REJECTED
                reason = "not_following"

    # For posts, generate a post_id
    target_id = action.target_id
    if action.action_type == ActionType.POST and status == ActionStatus.ACCEPTED:
        target_id = new_uuid()

    # Create and append action event
    event = Event(
        event_type=EventType.ACTION,
        tick=tick,
        actor_id=action.actor_id,
        op_id=action.op_id,
        timeline_id=action.timeline_id,
        model_id=action.model_id,
        prompt_version=action.prompt_version,
        ranking_version=RANKING_VERSION,
        status=status,
        payload=ActionPayload(
            action_type=action.action_type,
            target_id=target_id,
            position=action.position,
            content=action.content,
            reason=reason,
        ).model_dump(),
    )
    seq = append_event(conn, event)

    # Apply to projections if accepted
    if status == ActionStatus.ACCEPTED:
        event_dict = {
            "seq": seq,
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "tick": tick,
            "actor_id": action.actor_id,
            "op_id": action.op_id,
            "timeline_id": action.timeline_id,
            "model_id": action.model_id,
            "prompt_version": action.prompt_version,
            "ranking_version": RANKING_VERSION,
            "status": status.value,
            "created_at": event.created_at,
            "seed": event.seed,
            "payload": event.payload,
        }
        apply_event(conn, event_dict)

    return ActionResult(
        status=status,
        reason=reason,
        event_id=event.event_id if status == ActionStatus.ACCEPTED else None,
    )


def advance_tick(conn: sqlite3.Connection, from_tick: int, seed: int = 42) -> int:
    """Advance the simulation tick and emit an event."""
    new_tick = from_tick + 1

    event = Event(
        event_type=EventType.ADVANCE_TICK,
        tick=new_tick,
        seed=seed,
        payload={"from_tick": from_tick, "to_tick": new_tick},
    )
    append_event(conn, event)

    return new_tick


def create_user(
    conn: sqlite3.Connection,
    user_id: str,
    username: str,
    tick: int,
) -> None:
    """Create a new user and emit an event."""
    event = Event(
        event_type=EventType.USER_CREATED,
        tick=tick,
        actor_id=user_id,
        payload={"username": username},
    )
    seq = append_event(conn, event)

    # Apply to projections
    event_dict = {
        "seq": seq,
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "tick": tick,
        "actor_id": user_id,
        "op_id": event.op_id,
        "timeline_id": event.timeline_id,
        "model_id": event.model_id,
        "prompt_version": event.prompt_version,
        "ranking_version": event.ranking_version,
        "status": None,
        "created_at": event.created_at,
        "seed": event.seed,
        "payload": event.payload,
    }
    apply_event(conn, event_dict)


def emit_run_config(
    conn: sqlite3.Connection,
    num_agents: int,
    num_ticks: int,
    k: int,
    ranking_algorithm: str,
    seed: int,
) -> None:
    """Emit run configuration events for auditability."""
    # Run started event
    start_event = Event(
        event_type=EventType.RUN_STARTED,
        tick=0,
        seed=seed,
        payload={"message": "Simulation run started"},
    )
    append_event(conn, start_event)

    # Run config event
    from src.core.events import RunConfigPayload

    config_event = Event(
        event_type=EventType.RUN_CONFIG,
        tick=0,
        seed=seed,
        payload=RunConfigPayload(
            num_agents=num_agents,
            num_ticks=num_ticks,
            k=k,
            ranking_algorithm=ranking_algorithm,
            seed=seed,
        ).model_dump(),
    )
    append_event(conn, config_event)


def clear_exposures() -> None:
    """Clear the in-memory exposure tracking (for testing)."""
    _timeline_exposures.clear()


def get_exposures(timeline_id: str) -> set[str]:
    """Get exposed post IDs for a timeline (for testing)."""
    return _timeline_exposures.get(timeline_id, set())
