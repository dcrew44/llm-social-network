"""Tests for event logging and idempotency."""

import pytest

from src.core.events import (
    ActionStatus,
    Event,
    EventType,
    append_event,
    get_events,
    op_id_exists,
)


def test_append_event(db_conn):
    """Test basic event appending."""
    event = Event(
        event_type=EventType.ADVANCE_TICK,
        tick=1,
        payload={"from_tick": 0, "to_tick": 1},
    )

    seq = append_event(db_conn, event)
    assert seq > 0

    events = get_events(db_conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "advance_tick"
    assert events[0]["tick"] == 1


def test_event_ordering(db_conn):
    """Test that events are ordered by sequence."""
    for i in range(5):
        event = Event(
            event_type=EventType.ADVANCE_TICK,
            tick=i,
            payload={"tick": i},
        )
        append_event(db_conn, event)

    events = get_events(db_conn)
    assert len(events) == 5

    for i, event in enumerate(events):
        assert event["tick"] == i
        assert event["seq"] == i + 1  # seq starts at 1


def test_op_id_uniqueness(db_conn):
    """Test that duplicate op_ids are rejected."""
    event1 = Event(
        event_type=EventType.ACTION,
        tick=1,
        actor_id="agent_001",
        op_id="unique_op_123",
        status=ActionStatus.ACCEPTED,
        payload={"action": "test"},
    )
    append_event(db_conn, event1)

    assert op_id_exists(db_conn, "unique_op_123")
    assert not op_id_exists(db_conn, "other_op")

    # Attempting to insert duplicate op_id should fail
    event2 = Event(
        event_type=EventType.ACTION,
        tick=2,
        actor_id="agent_001",
        op_id="unique_op_123",
        status=ActionStatus.ACCEPTED,
        payload={"action": "duplicate"},
    )

    with pytest.raises(Exception):  # IntegrityError
        append_event(db_conn, event2)


def test_event_filtering_by_type(db_conn):
    """Test filtering events by type."""
    # Add various event types
    append_event(db_conn, Event(
        event_type=EventType.ADVANCE_TICK,
        tick=1,
        payload={},
    ))
    append_event(db_conn, Event(
        event_type=EventType.ACTION,
        tick=1,
        op_id="op_1",
        status=ActionStatus.ACCEPTED,
        payload={},
    ))
    append_event(db_conn, Event(
        event_type=EventType.ADVANCE_TICK,
        tick=2,
        payload={},
    ))

    all_events = get_events(db_conn)
    assert len(all_events) == 3

    tick_events = get_events(db_conn, event_type=EventType.ADVANCE_TICK)
    assert len(tick_events) == 2

    action_events = get_events(db_conn, event_type=EventType.ACTION)
    assert len(action_events) == 1
