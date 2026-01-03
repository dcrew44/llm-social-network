# LLM Social Network Simulator

An event-sourced, replayable simulation of a social network where agents read timelines and take actions (post, comment, like, follow).

## Design

### Event-First Architecture

All state changes originate from an append-only **event log** stored in SQLite. The event log is the single source of truth:

- `events` table stores every action, timeline served, tick advance, and run configuration
- Events are never mutated or deleted
- Each event has a sequence number (`seq`) providing total ordering

### Projections

**Projection tables** (`users`, `posts`, `comments`, `votes`, `follows`) are derived state rebuilt by replaying events:

- Projections can be dropped and rebuilt at any time via `replay`
- Given the same event log, replay produces bit-identical projection state
- This enables debugging, auditing, and "what-if" analysis

### Deterministic Replay

The simulation is fully deterministic:

- Tick-based discrete time (no wall-clock dependencies in logic)
- Ranking algorithms use a `seed` for tie-breaking
- Same events + same seed = identical outcomes

### Timeline-Action Exposure Tie

To simulate realistic user behavior:

- `timeline()` returns ranked posts and records which posts were "exposed" to the user
- `act()` validates that the target post was in the user's timeline exposure
- Actions on posts not seen by the user are rejected ("off-feed" prevention)

## What Gets Logged

### `timeline_served` Events

- `timeline_id`: Unique ID for this timeline request
- `items`: Ordered list of `{post_id, position, score, features}`
- `k`: Maximum items requested
- `algorithm`: Ranking algorithm used (`new`, `top`, `hot`)
- `ranking_version`: Version of ranking code
- `seed`: Random seed for determinism

### `action` Events

- `action_type`: `post`, `comment`, `like`, `unlike`, `follow`, `unfollow`
- `timeline_id`: Links action to the exposure that enabled it
- `position`: Position of item in timeline when acted upon
- `status`: `accepted` or `rejected`
- `reason`: Why rejected (if applicable)
- `op_id`: Idempotency key (prevents duplicate actions)

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Initialize database
python -m src.run_sim init-db

# Run simulation
python -m src.run_sim simulate --ticks 20 --agents 10 --k 10 --ranking hot

# View KPIs
python -m src.run_sim kpis

# Replay events (rebuild projections)
python -m src.run_sim replay

# View recent events
python -m src.run_sim events --limit 20

# Run tests
pytest
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `init-db [--force]` | Initialize SQLite database |
| `simulate --ticks N --agents M --k K --ranking ALG --seed S` | Run simulation |
| `replay` | Drop and rebuild projections from event log |
| `kpis [--json-output]` | Compute and display metrics |
| `events [--limit N] [--event-type TYPE]` | Show events from log |

## Project Structure

```
src/
  core/
    db.py           # SQLite connection, PRAGMAs, schema
    events.py       # Event models (Pydantic) and append helpers
    projections.py  # Replay logic and projection queries
    ranking.py      # Deterministic ranking algorithms
  api/
    sim.py          # timeline(), act(), advance_tick()
  agents/
    base.py         # Simple agent with probability-based policy
  kpis/
    metrics.py      # Gini coefficient, entropy calculations
  run_sim.py        # Click CLI
tests/
  test_events.py
  test_replay.py
  test_timeline_and_actions.py
```

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=src

# Single test file
pytest tests/test_replay.py

# Verbose output
pytest -v
```

## Ranking Algorithms

- **new**: Most recent posts first (by `created_tick`)
- **top**: Highest voted posts first (by `up_votes`)
- **hot**: Balances recency and engagement: `log10(max(ups,1)) - 0.1 * age`

All algorithms use a seed for deterministic tie-breaking.
