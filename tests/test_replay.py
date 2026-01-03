"""Tests for deterministic replay."""


from src.api.sim import (
    Action,
    act,
    clear_exposures,
    create_user,
    timeline,
)
from src.core.events import ActionType
from src.core.projections import get_projection_hash, replay_all


def test_replay_determinism(db_conn):
    """Test that replay produces identical state."""
    # Setup: create users and posts
    clear_exposures()
    create_user(db_conn, "user_1", "alice", tick=0)
    create_user(db_conn, "user_2", "bob", tick=0)

    # Create some posts
    for i in range(3):
        tl = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
        act(db_conn, Action(
            actor_id="user_1",
            op_id=f"post_{i}",
            timeline_id=tl.timeline_id,
            action_type=ActionType.POST,
            content=f"Post {i} content",
        ), tick=1)

    # Get another timeline and like a post
    tl = timeline(db_conn, "user_2", tick=2, k=10, seed=42)
    if tl.items:
        act(db_conn, Action(
            actor_id="user_2",
            op_id="like_1",
            timeline_id=tl.timeline_id,
            action_type=ActionType.LIKE,
            target_id=tl.items[0].post_id,
            position=0,
        ), tick=2)

    # Get hash before replay
    hash_before = get_projection_hash(db_conn)

    # Replay all events
    clear_exposures()
    event_count = replay_all(db_conn)
    assert event_count > 0

    # Get hash after replay
    hash_after = get_projection_hash(db_conn)

    # Hashes should match
    assert hash_before == hash_after, "Replay should produce identical state"


def test_replay_from_empty(db_conn):
    """Test replay starting from empty projections."""
    clear_exposures()

    # Create some data
    create_user(db_conn, "user_1", "alice", tick=0)
    tl = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
    act(db_conn, Action(
        actor_id="user_1",
        op_id="post_1",
        timeline_id=tl.timeline_id,
        action_type=ActionType.POST,
        content="Hello world",
    ), tick=1)

    # Verify data exists
    row = db_conn.execute("SELECT COUNT(*) FROM posts").fetchone()
    assert row[0] == 1

    # Replay
    clear_exposures()
    replay_all(db_conn)

    # Data should still exist
    row = db_conn.execute("SELECT COUNT(*) FROM posts").fetchone()
    assert row[0] == 1


def test_multiple_replays_consistent(db_conn):
    """Test that multiple replays produce the same result."""
    clear_exposures()

    create_user(db_conn, "user_1", "alice", tick=0)
    create_user(db_conn, "user_2", "bob", tick=0)

    # Create posts and interactions
    tl = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
    act(db_conn, Action(
        actor_id="user_1",
        op_id="post_1",
        timeline_id=tl.timeline_id,
        action_type=ActionType.POST,
        content="First post",
    ), tick=1)

    tl = timeline(db_conn, "user_2", tick=2, k=10, seed=42)
    if tl.items:
        act(db_conn, Action(
            actor_id="user_2",
            op_id="like_1",
            timeline_id=tl.timeline_id,
            action_type=ActionType.LIKE,
            target_id=tl.items[0].post_id,
            position=0,
        ), tick=2)

    # Do multiple replays and check consistency
    hashes = []
    for _ in range(3):
        clear_exposures()
        replay_all(db_conn)
        hashes.append(get_projection_hash(db_conn))

    assert len(set(hashes)) == 1, "All replays should produce identical hashes"
