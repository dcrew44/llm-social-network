"""Tests for timeline generation and action validation."""


from src.api.sim import (
    Action,
    act,
    clear_exposures,
    create_user,
    get_exposures,
    timeline,
)
from src.core.events import ActionStatus, ActionType


class TestTimeline:
    """Tests for timeline generation."""

    def test_timeline_empty(self, db_conn):
        """Test timeline with no posts."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)

        tl = timeline(db_conn, "user_1", tick=1, k=10, seed=42)

        assert tl.items == []
        assert tl.tick == 1
        assert tl.k == 10

    def test_timeline_with_posts(self, db_conn):
        """Test timeline returns posts."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)

        # Create a post first
        tl = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
        result = act(db_conn, Action(
            actor_id="user_1",
            op_id="post_1",
            timeline_id=tl.timeline_id,
            action_type=ActionType.POST,
            content="Test post",
        ), tick=1)
        assert result.status == ActionStatus.ACCEPTED

        # Now get timeline - should include the post
        tl2 = timeline(db_conn, "user_1", tick=2, k=10, seed=42)
        assert len(tl2.items) == 1

    def test_timeline_records_exposures(self, db_conn):
        """Test that timeline records exposures for validation."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)

        # Create a post
        tl1 = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
        act(db_conn, Action(
            actor_id="user_1",
            op_id="post_1",
            timeline_id=tl1.timeline_id,
            action_type=ActionType.POST,
            content="Test",
        ), tick=1)

        # Get timeline and check exposures
        tl2 = timeline(db_conn, "user_1", tick=2, k=10, seed=42)
        exposures = get_exposures(tl2.timeline_id)

        assert len(exposures) == 1
        assert tl2.items[0].post_id in exposures


class TestActions:
    """Tests for action validation and processing."""

    def test_idempotency_duplicate_rejected(self, db_conn):
        """Test that duplicate op_ids are rejected."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)

        tl = timeline(db_conn, "user_1", tick=1, k=10, seed=42)

        # First action
        result1 = act(db_conn, Action(
            actor_id="user_1",
            op_id="same_op_id",
            timeline_id=tl.timeline_id,
            action_type=ActionType.POST,
            content="First",
        ), tick=1)
        assert result1.status == ActionStatus.ACCEPTED

        # Second action with same op_id
        result2 = act(db_conn, Action(
            actor_id="user_1",
            op_id="same_op_id",
            timeline_id=tl.timeline_id,
            action_type=ActionType.POST,
            content="Second",
        ), tick=1)
        assert result2.status == ActionStatus.REJECTED
        assert result2.reason == "duplicate_op_id"

        # Verify only one post was created
        count = db_conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        assert count == 1

    def test_exposure_tie_required(self, db_conn):
        """Test that likes require item to be in timeline exposures."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)
        create_user(db_conn, "user_2", "bob", tick=0)

        # User 1 creates a post
        tl1 = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
        act(db_conn, Action(
            actor_id="user_1",
            op_id="post_1",
            timeline_id=tl1.timeline_id,
            action_type=ActionType.POST,
            content="Test",
        ), tick=1)

        # User 2 gets timeline (sees the post)
        tl2 = timeline(db_conn, "user_2", tick=2, k=10, seed=42)
        post_id = tl2.items[0].post_id

        # Try to like with wrong timeline_id
        result = act(db_conn, Action(
            actor_id="user_2",
            op_id="like_wrong",
            timeline_id="fake_timeline_id",
            action_type=ActionType.LIKE,
            target_id=post_id,
            position=0,
        ), tick=2)
        assert result.status == ActionStatus.REJECTED
        assert result.reason == "invalid_timeline_id"

        # Like with correct timeline_id should work
        result = act(db_conn, Action(
            actor_id="user_2",
            op_id="like_correct",
            timeline_id=tl2.timeline_id,
            action_type=ActionType.LIKE,
            target_id=post_id,
            position=0,
        ), tick=2)
        assert result.status == ActionStatus.ACCEPTED

    def test_cannot_like_twice(self, db_conn):
        """Test that a user cannot like the same post twice."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)
        create_user(db_conn, "user_2", "bob", tick=0)

        # Create a post
        tl1 = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
        act(db_conn, Action(
            actor_id="user_1",
            op_id="post_1",
            timeline_id=tl1.timeline_id,
            action_type=ActionType.POST,
            content="Test",
        ), tick=1)

        # Get timeline
        tl2 = timeline(db_conn, "user_2", tick=2, k=10, seed=42)
        post_id = tl2.items[0].post_id

        # First like
        result1 = act(db_conn, Action(
            actor_id="user_2",
            op_id="like_1",
            timeline_id=tl2.timeline_id,
            action_type=ActionType.LIKE,
            target_id=post_id,
            position=0,
        ), tick=2)
        assert result1.status == ActionStatus.ACCEPTED

        # Get new timeline for second attempt
        tl3 = timeline(db_conn, "user_2", tick=3, k=10, seed=42)

        # Second like attempt
        result2 = act(db_conn, Action(
            actor_id="user_2",
            op_id="like_2",
            timeline_id=tl3.timeline_id,
            action_type=ActionType.LIKE,
            target_id=post_id,
            position=0,
        ), tick=3)
        assert result2.status == ActionStatus.REJECTED
        assert result2.reason == "already_liked"

    def test_off_feed_action_rejected(self, db_conn):
        """Test that actions on posts not in feed are rejected."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)
        create_user(db_conn, "user_2", "bob", tick=0)

        # User 1 creates a post
        tl1 = timeline(db_conn, "user_1", tick=1, k=10, seed=42)
        act(db_conn, Action(
            actor_id="user_1",
            op_id="post_1",
            timeline_id=tl1.timeline_id,
            action_type=ActionType.POST,
            content="Test",
        ), tick=1)

        # User 2 gets timeline
        tl2 = timeline(db_conn, "user_2", tick=2, k=10, seed=42)
        _ = tl2.items[0].post_id  # Verify post exists

        # Try to like a non-existent post via valid timeline
        result = act(db_conn, Action(
            actor_id="user_2",
            op_id="like_fake",
            timeline_id=tl2.timeline_id,
            action_type=ActionType.LIKE,
            target_id="fake_post_id",
            position=0,
        ), tick=2)
        assert result.status == ActionStatus.REJECTED
        assert result.reason == "target_not_in_timeline"


class TestRanking:
    """Tests for ranking algorithms."""

    def test_ranking_deterministic(self, db_conn):
        """Test that ranking is deterministic with same seed."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)

        # Create multiple posts
        for i in range(5):
            tl = timeline(db_conn, "user_1", tick=i + 1, k=10, seed=42)
            act(db_conn, Action(
                actor_id="user_1",
                op_id=f"post_{i}",
                timeline_id=tl.timeline_id,
                action_type=ActionType.POST,
                content=f"Post {i}",
            ), tick=i + 1)

        # Get timeline twice with same seed
        clear_exposures()
        tl1 = timeline(db_conn, "user_1", tick=10, k=10, algorithm="hot", seed=123)
        clear_exposures()
        tl2 = timeline(db_conn, "user_1", tick=10, k=10, algorithm="hot", seed=123)

        # Order should be identical
        ids1 = [item.post_id for item in tl1.items]
        ids2 = [item.post_id for item in tl2.items]
        assert ids1 == ids2

    def test_different_algorithms_different_orders(self, db_conn):
        """Test that different algorithms produce different orders."""
        clear_exposures()
        create_user(db_conn, "user_1", "alice", tick=0)
        create_user(db_conn, "user_2", "bob", tick=0)

        # Create posts at different times
        for i in range(3):
            tl = timeline(db_conn, "user_1", tick=i + 1, k=10, seed=42)
            act(db_conn, Action(
                actor_id="user_1",
                op_id=f"post_{i}",
                timeline_id=tl.timeline_id,
                action_type=ActionType.POST,
                content=f"Post {i}",
            ), tick=i + 1)

        # Like the first (oldest) post
        tl = timeline(db_conn, "user_2", tick=5, k=10, seed=42, algorithm="new")
        oldest_post = tl.items[-1].post_id  # newest first, so oldest is last
        act(db_conn, Action(
            actor_id="user_2",
            op_id="like_old",
            timeline_id=tl.timeline_id,
            action_type=ActionType.LIKE,
            target_id=oldest_post,
            position=len(tl.items) - 1,
        ), tick=5)

        # Get with different algorithms
        clear_exposures()
        tl_new = timeline(db_conn, "user_1", tick=10, k=10, algorithm="new", seed=42)
        clear_exposures()
        tl_top = timeline(db_conn, "user_1", tick=10, k=10, algorithm="top", seed=42)

        ids_new = [item.post_id for item in tl_new.items]
        ids_top = [item.post_id for item in tl_top.items]

        # Orders should differ (top should favor the liked post)
        assert ids_new != ids_top or len(ids_new) < 2  # Allow equality if only 1 item
