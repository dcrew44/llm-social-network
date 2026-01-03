# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Event-sourced LLM Twitter simulator with deterministic replay. Agents read timelines and take actions (post/comment/like/follow). All state derives from an append-only SQLite event log.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run tests
pytest -v

# Single test
pytest tests/test_replay.py -v

# Lint
ruff check src tests

# Initialize DB and run simulation
python -m src.run_sim init-db --force
python -m src.run_sim simulate --ticks 20 --agents 10

# Replay projections from events
python -m src.run_sim replay

# View KPIs
python -m src.run_sim kpis
```

Or use `just`:
```bash
just test      # run tests
just run       # init + simulate
just replay    # rebuild projections
just lint      # check code
```

## Architecture

### Event Sourcing Pattern
- **Source of truth**: `events` table (append-only, never mutate/delete)
- **Projections**: `users`, `posts`, `comments`, `votes`, `follows` - rebuilt by replaying events
- **Determinism**: Same events + seed = identical state

### Key Modules
- `src/core/db.py` - SQLite connection with WAL mode, foreign keys
- `src/core/events.py` - Pydantic event models, `append_event()`, `op_id_exists()`
- `src/core/projections.py` - `replay_all()`, `apply_event()`, projection queries
- `src/core/ranking.py` - `rank_posts()` with new/top/hot algorithms
- `src/api/sim.py` - `timeline()`, `act()`, `advance_tick()` - main API functions
- `src/agents/base.py` - Agent scaffold with `plan()` and `compose()` stubs

### Exposure Tie Enforcement
Actions (like, comment) must reference a `timeline_id` that exposed the target post. This prevents "off-feed" actions and enables audit of what users saw before acting.

### Event Types
- `timeline_served` - Records exposed posts with scores/features
- `action` - User actions with status (accepted/rejected) and idempotency key (`op_id`)
- `advance_tick` - Tick progression
- `run_started`, `run_config` - Simulation configuration for auditability

## Testing

Tests use temporary SQLite databases (see `tests/conftest.py`). Key test scenarios:
- Idempotency via `op_id`
- Exposure tie validation
- Deterministic replay producing identical hashes
- Ranking algorithm consistency
