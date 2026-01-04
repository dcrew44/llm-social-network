"""LLM-powered agent with intelligent planning and composition."""

import sqlite3
from dataclasses import dataclass
from typing import Any

from src.agents.base import Agent, AgentConfig, Intent
from src.agents.llm import OllamaClient
from src.api.sim import Timeline


@dataclass
class LLMAgentConfig(AgentConfig):
    """Configuration for LLM-powered agent."""

    model: str = "llama3.2:3b"
    temperature: float = 0.7
    use_llm_for_plan: bool = True
    use_llm_for_compose: bool = True


class LLMAgent(Agent):
    """Agent with LLM-powered plan() and compose() methods."""

    def __init__(self, config: LLMAgentConfig):
        super().__init__(config)
        self.llm_config = config
        self.llm = OllamaClient(model=config.model)

    def plan(self, tl: Timeline) -> Intent:
        """
        Decide what to do based on timeline using LLM.

        Falls back to probability-based planning if LLM is disabled or errors.
        """
        if not self.llm_config.use_llm_for_plan:
            return super().plan(tl)

        if self.state.actions_this_tick >= self.config.max_actions_per_tick:
            return Intent.IDLE

        # Build timeline summary for LLM
        if not tl.items:
            timeline_summary = "Timeline is empty."
        else:
            timeline_summary = f"{len(tl.items)} posts in timeline:\n"
            for i, item in enumerate(tl.items[:5]):  # Only show top 5
                timeline_summary += (
                    f"  {i+1}. Post {item.post_id[:8]} "
                    f"(score: {item.score:.2f}, "
                    f"votes: {item.features.get('up_votes', 0):.0f}, "
                    f"comments: {item.features.get('comments', 0):.0f})\n"
                )

        system_prompt = f"""You are {self.config.username}, a user on a social network.
Based on the timeline, decide what action to take.

Available actions:
- idle: Do nothing this turn
- post: Create a new post
- like: Like a post from the timeline
- comment: Comment on a post from the timeline
- follow: Follow the author of a post

Consider:
- The content and engagement of posts in the timeline
- Your past behavior (you've made {self.state.total_posts} posts, {self.state.total_likes} likes, {self.state.total_comments} comments)
- Whether you want to engage with existing content or create your own"""

        user_prompt = f"""Timeline:
{timeline_summary}

What do you want to do? Respond with exactly one word: idle, post, like, comment, or follow."""

        try:
            response = self.llm.generate(
                prompt=user_prompt,
                system=system_prompt,
                temperature=self.llm_config.temperature,
                max_tokens=10,
            )

            # Parse response
            action = response.lower().strip()
            for intent in Intent:
                if intent.value in action:
                    return intent

            # Default to idle if unparseable
            return Intent.IDLE

        except Exception as e:
            print(f"LLM plan error for {self.agent_id}: {e}")
            # Fallback to probability-based
            return super().plan(tl)

    def compose(self, intent: Intent, context: dict[str, Any] | None = None) -> str:
        """
        Compose content using LLM.

        Falls back to template-based composition if LLM is disabled or errors.
        """
        if not self.llm_config.use_llm_for_compose:
            return super().compose(intent, context)

        if intent not in [Intent.POST, Intent.COMMENT]:
            return ""

        tick = context.get("tick", 0) if context else 0

        if intent == Intent.POST:
            system_prompt = f"""You are {self.config.username}, a user on a social network.
Write an engaging, original post. Be creative, conversational, and authentic.
Keep it under 280 characters."""

            user_prompt = f"""Write a social media post for tick {tick}.

This is post #{self.state.total_posts + 1} from you. Make it interesting and varied!

Post:"""

        else:  # COMMENT
            post_id = context.get("post_id", "unknown") if context else "unknown"
            system_prompt = f"""You are {self.config.username}, commenting on a social network.
Write a thoughtful, engaging comment. Be authentic and add value to the conversation.
Keep it under 280 characters."""

            user_prompt = f"""Write a comment on post {post_id[:8]}.

This is comment #{self.state.total_comments + 1} from you.

Comment:"""

        try:
            response = self.llm.generate(
                prompt=user_prompt,
                system=system_prompt,
                temperature=self.llm_config.temperature,
                max_tokens=100,
            )

            # Update counters
            if intent == Intent.POST:
                self.state.total_posts += 1
            elif intent == Intent.COMMENT:
                self.state.total_comments += 1

            return response

        except Exception as e:
            print(f"LLM compose error for {self.agent_id}: {e}")
            # Fallback to template-based
            return super().compose(intent, context)


def create_llm_agents(
    conn: sqlite3.Connection,
    num_agents: int,
    tick: int,
    base_seed: int = 42,
    model: str = "llama3.2:3b",
    use_llm_for_plan: bool = True,
    use_llm_for_compose: bool = True,
) -> list[LLMAgent]:
    """Create and register a list of LLM-powered agents."""
    from src.api.sim import create_user

    agents = []

    for i in range(num_agents):
        agent_id = f"agent_{i:04d}"
        username = f"user_{i:04d}"
        seed = base_seed + i

        # Create user in the system
        create_user(conn, agent_id, username, tick)

        # Create LLM agent instance
        config = LLMAgentConfig(
            agent_id=agent_id,
            username=username,
            seed=seed,
            model=model,
            use_llm_for_plan=use_llm_for_plan,
            use_llm_for_compose=use_llm_for_compose,
        )
        agents.append(LLMAgent(config))

    return agents
