"""SQLite database connection and schema management."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DEFAULT_DB_PATH = Path("sim.db")

EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    tick INTEGER NOT NULL,
    actor_id TEXT,
    op_id TEXT UNIQUE,
    timeline_id TEXT,
    model_id TEXT,
    prompt_version TEXT,
    ranking_version TEXT,
    status TEXT,
    created_at TEXT NOT NULL,
    seed INTEGER,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_tick ON events(tick);
CREATE INDEX IF NOT EXISTS idx_events_timeline_id ON events(timeline_id);
CREATE INDEX IF NOT EXISTS idx_events_type_tick ON events(event_type, tick);
"""

PROJECTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_tick INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    author_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_tick INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (author_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_tick INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts(post_id),
    FOREIGN KEY (author_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS votes (
    vote_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    vote_type TEXT NOT NULL CHECK (vote_type IN ('up', 'down')),
    created_tick INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(post_id, user_id),
    FOREIGN KEY (post_id) REFERENCES posts(post_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS follows (
    follower_id TEXT NOT NULL,
    followee_id TEXT NOT NULL,
    created_tick INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (follower_id, followee_id),
    FOREIGN KEY (follower_id) REFERENCES users(user_id),
    FOREIGN KEY (followee_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_posts_tick ON posts(created_tick);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_votes_post ON votes(post_id);
CREATE INDEX IF NOT EXISTS idx_follows_followee ON follows(followee_id);
"""


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create a new connection with optimized PRAGMAs."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """Context manager for explicit transactions."""
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    try:
        yield cursor
        cursor.execute("COMMIT")
    except Exception:
        cursor.execute("ROLLBACK")
        raise
    finally:
        cursor.close()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Initialize database with all schemas."""
    conn = get_connection(db_path)
    conn.executescript(EVENTS_SCHEMA)
    conn.executescript(PROJECTIONS_SCHEMA)
    return conn


def drop_projections(conn: sqlite3.Connection) -> None:
    """Drop all projection tables (preserves events)."""
    tables = ["follows", "votes", "comments", "posts", "users"]
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def recreate_projections(conn: sqlite3.Connection) -> None:
    """Recreate projection table schemas."""
    conn.executescript(PROJECTIONS_SCHEMA)
