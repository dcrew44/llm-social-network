"""Agent scaffold with simple policy and two-tier cognition placeholder."""

import random
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.api.sim import Action, ActionResult, Timeline, act, create_user
from src.core.events import ActionType, new_uuid


class Intent(str, Enum):
    """Possible agent intents."""

    IDLE = "idle"
    POST = "post"
    LIKE = "like"
    COMMENT = "comment"
    FOLLOW = "follow"


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    agent_id: str
    username: str
    post_probability: float = 0.1
    like_probability: float = 0.3
    comment_probability: float = 0.1
    follow_probability: float = 0.05
    max_actions_per_tick: int = 3
    seed: int = 42


@dataclass
class AgentState:
    """Mutable state for an agent."""

    actions_this_tick: int = 0
    total_posts: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_follows: int = 0
    rng: random.Random = field(default_factory=lambda: random.Random())

    def reset_tick(self) -> None:
        """Reset per-tick counters."""
        self.actions_this_tick = 0


class Agent:
    """Simple agent with budget-constrained behavior."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.state = AgentState()
        self.state.rng = random.Random(config.seed)

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    def plan(self, tl: Timeline) -> Intent:
        """
        Decide what to do based on the timeline.

        This is a cheap stub - no LLM call. Returns an intent based on
        configured probabilities.
        """
        if self.state.actions_this_tick >= self.config.max_actions_per_tick:
            return Intent.IDLE

        # Decide based on probabilities
        r = self.state.rng.random()

        if r < self.config.post_probability:
            return Intent.POST
        r -= self.config.post_probability

        if len(tl.items) > 0:
            if r < self.config.like_probability:
                return Intent.LIKE
            r -= self.config.like_probability

            if r < self.config.comment_probability:
                return Intent.COMMENT
            r -= self.config.comment_probability

            if r < self.config.follow_probability:
                return Intent.FOLLOW

        return Intent.IDLE

    def compose(self, intent: Intent, context: dict[str, Any] | None = None) -> str:
        """
        Compose content for post/comment.

        This is a stub - returns templated strings. In the future,
        this would call an LLM.
        """
        tick = context.get("tick", 0) if context else 0

        if intent == Intent.POST:
            self.state.total_posts += 1
            return f"Post #{self.state.total_posts} from {self.config.username} at tick {tick}"
        elif intent == Intent.COMMENT:
            self.state.total_comments += 1
            post_id = context.get("post_id", "unknown") if context else "unknown"
            username = self.config.username
            return f"Comment #{self.state.total_comments} on {post_id[:8]} by {username}"
        return ""

    def select_target(self, tl: Timeline, intent: Intent) -> dict[str, Any] | None:
        """Select a target item from the timeline based on intent."""
        if not tl.items:
            return None

        # Simple selection: pick randomly from top items
        idx = self.state.rng.randint(0, min(len(tl.items) - 1, 4))
        item = tl.items[idx]

        return {
            "post_id": item.post_id,
            "position": item.position,
        }

    def execute(
        self,
        conn: sqlite3.Connection,
        tl: Timeline,
        tick: int,
    ) -> list[ActionResult]:
        """
        Execute a full agent turn: plan, compose, and act.

        Returns list of action results.
        """
        results: list[ActionResult] = []

        while self.state.actions_this_tick < self.config.max_actions_per_tick:
            intent = self.plan(tl)

            if intent == Intent.IDLE:
                break

            result = self._execute_intent(conn, tl, tick, intent)
            if result:
                results.append(result)
                self.state.actions_this_tick += 1

        return results

    def _execute_intent(
        self,
        conn: sqlite3.Connection,
        tl: Timeline,
        tick: int,
        intent: Intent,
    ) -> ActionResult | None:
        """Execute a single intent."""
        op_id = new_uuid()

        if intent == Intent.POST:
            content = self.compose(Intent.POST, {"tick": tick})
            action = Action(
                actor_id=self.agent_id,
                op_id=op_id,
                timeline_id=tl.timeline_id,
                action_type=ActionType.POST,
                content=content,
            )
            return act(conn, action, tick)

        target = self.select_target(tl, intent)
        if not target:
            return None

        if intent == Intent.LIKE:
            action = Action(
                actor_id=self.agent_id,
                op_id=op_id,
                timeline_id=tl.timeline_id,
                action_type=ActionType.LIKE,
                target_id=target["post_id"],
                position=target["position"],
            )
            result = act(conn, action, tick)
            if result.status.value == "accepted":
                self.state.total_likes += 1
            return result

        elif intent == Intent.COMMENT:
            content = self.compose(Intent.COMMENT, {"tick": tick, "post_id": target["post_id"]})
            action = Action(
                actor_id=self.agent_id,
                op_id=op_id,
                timeline_id=tl.timeline_id,
                action_type=ActionType.COMMENT,
                target_id=target["post_id"],
                position=target["position"],
                content=content,
            )
            return act(conn, action, tick)

        elif intent == Intent.FOLLOW:
            # For follow, we'd need to get the author of the post
            # For now, skip as it requires additional lookup
            return None

        return None

    def on_tick_end(self) -> None:
        """Called at the end of each tick."""
        self.state.reset_tick()


def create_agents(
    conn: sqlite3.Connection,
    num_agents: int,
    tick: int,
    base_seed: int = 42,
) -> list[Agent]:
    """Create and register a list of agents."""
    agents = []

    for i in range(num_agents):
        agent_id = f"agent_{i:04d}"
        username = f"user_{i:04d}"
        seed = base_seed + i

        # Create user in the system
        create_user(conn, agent_id, username, tick)

        # Create agent instance
        config = AgentConfig(
            agent_id=agent_id,
            username=username,
            seed=seed,
        )
        agents.append(Agent(config))

    return agents
