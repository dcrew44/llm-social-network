"""CLI for the LLM Social Network simulator."""

import json
from pathlib import Path

import click

from src.agents.base import create_agents
from src.api.sim import advance_tick, clear_exposures, emit_run_config, timeline
from src.core.db import DEFAULT_DB_PATH, get_connection, init_db
from src.core.projections import get_projection_hash, replay_all
from src.kpis.metrics import compute_kpis


@click.group()
def cli() -> None:
    """LLM Social Network Simulator CLI."""
    pass


@cli.command("init-db")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(DEFAULT_DB_PATH),
    help="Path to SQLite database file",
)
@click.option("--force", is_flag=True, help="Drop existing database if it exists")
def init_db_cmd(db_path: str, force: bool) -> None:
    """Initialize the database schema."""
    path = Path(db_path)

    if path.exists():
        if force:
            path.unlink()
            click.echo(f"Removed existing database: {path}")
        else:
            click.echo(f"Database already exists: {path}")
            click.echo("Use --force to recreate")
            return

    conn = init_db(path)
    conn.close()
    click.echo(f"Initialized database: {path}")


@cli.command("simulate")
@click.option("--ticks", default=10, help="Number of ticks to simulate")
@click.option("--agents", default=5, help="Number of agents")
@click.option("--k", default=10, help="Timeline size (max items)")
@click.option(
    "--ranking",
    type=click.Choice(["new", "top", "hot"]),
    default="hot",
    help="Ranking algorithm",
)
@click.option("--seed", default=42, help="Random seed for reproducibility")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(DEFAULT_DB_PATH),
    help="Path to SQLite database file",
)
def simulate(
    ticks: int,
    agents: int,
    k: int,
    ranking: str,
    seed: int,
    db_path: str,
) -> None:
    """Run a simulation."""
    path = Path(db_path)

    if not path.exists():
        click.echo(f"Database not found: {path}")
        click.echo("Run 'init-db' first")
        return

    conn = get_connection(path)
    clear_exposures()

    # Emit run configuration
    emit_run_config(conn, agents, ticks, k, ranking, seed)
    click.echo(f"Starting simulation: {agents} agents, {ticks} ticks, k={k}, ranking={ranking}")

    # Create agents at tick 0
    current_tick = 0
    agent_list = create_agents(conn, agents, current_tick, seed)
    click.echo(f"Created {len(agent_list)} agents")

    # Run simulation
    for _ in range(ticks):
        current_tick = advance_tick(conn, current_tick, seed)

        for agent in agent_list:
            # Get timeline for agent
            tl = timeline(
                conn,
                agent.agent_id,
                current_tick,
                k=k,
                algorithm=ranking,
                seed=seed + current_tick,
            )

            # Agent executes actions
            agent.execute(conn, tl, current_tick)

            # Reset agent for next tick
            agent.on_tick_end()

        if current_tick % 5 == 0 or current_tick == ticks:
            click.echo(f"  Tick {current_tick} complete")

    # Print summary
    kpis = compute_kpis(conn)
    click.echo("\nSimulation complete!")
    click.echo(f"  Posts: {kpis['counts']['posts']}")
    click.echo(f"  Votes: {kpis['counts']['votes']}")
    click.echo(f"  Comments: {kpis['counts']['comments']}")
    click.echo(f"  Attention Gini: {kpis['attention_gini']:.4f}")

    conn.close()


@cli.command("replay")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(DEFAULT_DB_PATH),
    help="Path to SQLite database file",
)
def replay(db_path: str) -> None:
    """Replay events to rebuild projections."""
    path = Path(db_path)

    if not path.exists():
        click.echo(f"Database not found: {path}")
        return

    conn = get_connection(path)

    # Get hash before replay
    hash_before = get_projection_hash(conn)

    # Replay all events
    event_count = replay_all(conn)

    # Get hash after replay
    hash_after = get_projection_hash(conn)

    click.echo(f"Replayed {event_count} events")
    click.echo(f"Hash before: {hash_before[:16]}...")
    click.echo(f"Hash after:  {hash_after[:16]}...")

    if hash_before == hash_after:
        click.echo("Projections unchanged (deterministic)")
    else:
        click.echo("Projections rebuilt")

    conn.close()


@cli.command("kpis")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(DEFAULT_DB_PATH),
    help="Path to SQLite database file",
)
@click.option("--json-output", is_flag=True, help="Output as JSON")
def kpis(db_path: str, json_output: bool) -> None:
    """Compute and display KPIs."""
    path = Path(db_path)

    if not path.exists():
        click.echo(f"Database not found: {path}")
        return

    conn = get_connection(path)
    metrics = compute_kpis(conn)

    if json_output:
        click.echo(json.dumps(metrics, indent=2))
    else:
        click.echo("KPIs:")
        click.echo(f"  Posts: {metrics['counts']['posts']}")
        click.echo(f"  Users: {metrics['counts']['users']}")
        click.echo(f"  Votes: {metrics['counts']['votes']}")
        click.echo(f"  Comments: {metrics['counts']['comments']}")
        click.echo(f"  Follows: {metrics['counts']['follows']}")
        click.echo()
        click.echo("Actions:")
        total = metrics['actions']['accepted'] + metrics['actions']['rejected']
        if total > 0:
            acc_pct = 100 * metrics['actions']['accepted'] / total
            click.echo(f"  Accepted: {metrics['actions']['accepted']} ({acc_pct:.1f}%)")
            click.echo(f"  Rejected: {metrics['actions']['rejected']} ({100-acc_pct:.1f}%)")
            if metrics['actions']['rejection_reasons']:
                click.echo("  Rejection reasons:")
                for reason, count in metrics['actions']['rejection_reasons'].items():
                    click.echo(f"    {reason}: {count}")
        else:
            click.echo("  No actions recorded")
        click.echo()
        click.echo(f"Attention Gini: {metrics['attention_gini']:.4f}")
        click.echo(f"Author Attention Gini: {metrics['author_attention_gini']:.4f}")
        click.echo(f"Topic Entropy: {metrics['topic_entropy']:.4f} bits")

    conn.close()


@cli.command("events")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(DEFAULT_DB_PATH),
    help="Path to SQLite database file",
)
@click.option("--limit", default=20, help="Number of events to show")
@click.option("--event-type", type=str, help="Filter by event type")
def events(db_path: str, limit: int, event_type: str | None) -> None:
    """Show recent events from the log."""
    path = Path(db_path)

    if not path.exists():
        click.echo(f"Database not found: {path}")
        return

    conn = get_connection(path)

    query = "SELECT seq, event_type, tick, actor_id, status, payload_json FROM events"
    params: list = []

    if event_type:
        query += " WHERE event_type = ?"
        params.append(event_type)

    query += " ORDER BY seq DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()

    click.echo(
        f"{'Seq':>6} {'Type':<20} {'Tick':>5} "
        f"{'Actor':<12} {'Status':<10} {'Details':<40}"
    )
    click.echo("-" * 100)

    for row in reversed(rows):
        actor_id = row["actor_id"]
        actor = actor_id[:10] + ".." if actor_id and len(actor_id) > 12 else (actor_id or "-")
        status = row["status"] or "-"

        # Extract details based on event type
        details = ""
        if row["event_type"] == "action" and row["payload_json"]:
            try:
                payload = json.loads(row["payload_json"])
                action_type = payload.get("action_type", "?")
                target_id = payload.get("target_id", "")
                target = target_id[:8] if target_id else "-"
                reason = payload.get("reason")

                details = f"{action_type}"
                if target_id:
                    details += f" → {target}"
                if reason:
                    details += f" ({reason})"
            except (json.JSONDecodeError, KeyError):
                details = "-"
        elif row["event_type"] == "timeline_served" and row["payload_json"]:
            try:
                payload = json.loads(row["payload_json"])
                algo = payload.get("algorithm", "?")
                k = payload.get("k", "?")
                items = payload.get("items", [])
                details = f"{algo} k={k} items={len(items)}"
            except (json.JSONDecodeError, KeyError):
                details = "-"

        click.echo(
            f"{row['seq']:>6} {row['event_type']:<20} {row['tick']:>5} "
            f"{actor:<12} {status:<10} {details:<40}"
        )

    conn.close()


if __name__ == "__main__":
    cli()
