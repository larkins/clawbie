#!/usr/bin/env python3
"""Nightly reverie generation and retrieval.

Generates daily summaries from memories, stores in database, and emails to user.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "git" / "clawbie"))

from psycopg import connect


def get_connection():
    """Get database connection from environment."""
    # Load from clawbie .env if not already set
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        env_path = Path.home() / "git" / "clawbie" / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        db_url = line.split("=", 1)[1].strip().strip('"')
                        break
    if not db_url:
        raise ValueError("DATABASE_URL not found in environment or ~/git/clawbie/.env")
    return connect(db_url)


def get_unsummarized_memories(conn, target_date: date) -> list[dict]:
    """Fetch all unsummarized memories for a specific date."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, memory_text, reflection, created_at, source_type, session_id
        FROM user_memories
        WHERE DATE(created_at) = %s
        AND reverie_summarized = FALSE
        ORDER BY created_at ASC
    """, (target_date,))
    
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    return rows


def mark_memories_summarized(conn, memory_ids: list[int]) -> int:
    """Mark memories as summarized."""
    if not memory_ids:
        return 0
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_memories
        SET reverie_summarized = TRUE
        WHERE id = ANY(%s)
    """, (memory_ids,))
    count = cursor.rowcount
    conn.commit()
    cursor.close()
    return count


def get_latest_reverie(conn) -> dict | None:
    """Get the most recent reverie."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date, summary_md, reflections, next_day_ideas, memory_count, created_at
        FROM nightly_reverie
        ORDER BY date DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    cursor.close()
    if row:
        return {
            "id": row[0],
            "date": row[1],
            "summary_md": row[2],
            "reflections": row[3],
            "next_day_ideas": row[4],
            "memory_count": row[5],
            "created_at": row[6],
        }
    return None


def get_reverie_by_date(conn, target_date: date) -> dict | None:
    """Get reverie for a specific date."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date, summary_md, reflections, next_day_ideas, memory_count, created_at
        FROM nightly_reverie
        WHERE date = %s
    """, (target_date,))
    row = cursor.fetchone()
    cursor.close()
    if row:
        return {
            "id": row[0],
            "date": row[1],
            "summary_md": row[2],
            "reflections": row[3],
            "next_day_ideas": row[4],
            "memory_count": row[5],
            "created_at": row[6],
        }
    return None


def list_reveries(conn, limit: int = 10) -> list[dict]:
    """List recent reveries."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date, memory_count, created_at
        FROM nightly_reverie
        ORDER BY date DESC
        LIMIT %s
    """, (limit,))
    rows = cursor.fetchall()
    cursor.close()
    return [{"id": r[0], "date": r[1], "memory_count": r[2], "created_at": r[3]} for r in rows]


def save_reverie(conn, target_date: date, summary_md: str, reflections: str, 
                 next_day_ideas: str, memory_count: int) -> int:
    """Save reverie to database."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO nightly_reverie (date, summary_md, reflections, next_day_ideas, memory_count)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (date) DO UPDATE SET
            summary_md = EXCLUDED.summary_md,
            reflections = EXCLUDED.reflections,
            next_day_ideas = EXCLUDED.next_day_ideas,
            memory_count = EXCLUDED.memory_count
        RETURNING id
    """, (target_date, summary_md, reflections, next_day_ideas, memory_count))
    reverie_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    return reverie_id


def format_reverie_for_output(reverie: dict) -> str:
    """Format reverie for terminal output."""
    lines = [
        f"{'='*60}",
        f"Nightly Reverie - {reverie['date']}",
        f"{'='*60}",
        "",
        reverie["summary_md"],
        "",
        "--- Reflections ---",
        reverie.get("reflections", ""),
        "",
        "--- Next Day Ideas ---",
        reverie.get("next_day_ideas", ""),
        "",
        f"[{reverie['memory_count']} memories processed]",
    ]
    return "\n".join(lines)


def cmd_status(args):
    """Show status of unsummarized memories."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Count by date
    cursor.execute("""
        SELECT DATE(created_at) as day, COUNT(*) 
        FROM user_memories 
        WHERE reverie_summarized = FALSE 
        GROUP BY day 
        ORDER BY day DESC 
        LIMIT 10
    """)
    rows = cursor.fetchall()
    
    print("Unsummarized memories by date:")
    for day, count in rows:
        print(f"   {day}: {count} rows")
    
    # Latest reverie
    latest = get_latest_reverie(conn)
    if latest:
        print(f"\nLatest reverie: {latest['date']} ({latest['memory_count']} memories)")
    else:
        print("\nNo reveries yet.")
    
    cursor.close()
    conn.close()


def cmd_get_latest(args):
    """Get the latest reverie."""
    conn = get_connection()
    reverie = get_latest_reverie(conn)
    conn.close()
    
    if reverie:
        print(format_reverie_for_output(reverie))
    else:
        print("No reveries found.")


def cmd_get(args):
    """Get reverie by date."""
    conn = get_connection()
    reverie = get_reverie_by_date(conn, args.date)
    conn.close()
    
    if reverie:
        print(format_reverie_for_output(reverie))
    else:
        print(f"No reverie found for {args.date}.")


def cmd_list(args):
    """List recent reveries."""
    conn = get_connection()
    reveries = list_reveries(conn, args.limit)
    conn.close()
    
    if reveries:
        print("Recent reveries:")
        for r in reveries:
            print(f"   {r['date']}: {r['memory_count']} memories")
    else:
        print("No reveries found.")


def cmd_generate(args):
    """Generate reverie for a date (for manual testing)."""
    target_date = args.date if args.date else date.today() - timedelta(days=1)
    
    conn = get_connection()
    
    # Get unsummarized memories
    memories = get_unsummarized_memories(conn, target_date)
    
    if not memories:
        print(f"No unsummarized memories for {target_date}")
        conn.close()
        return
    
    print(f"Found {len(memories)} memories for {target_date}")
    
    # For now, just output raw - actual generation would call an LLM
    print("\nMemory texts:")
    for i, m in enumerate(memories[:5]):
        print(f"\n[{i+1}] {m['memory_text'][:200]}...")
    
    if len(memories) > 5:
        print(f"\n... and {len(memories) - 5} more")
    
    # Mark as summarized if --mark flag
    if args.mark:
        memory_ids = [m["id"] for m in memories]
        count = mark_memories_summarized(conn, memory_ids)
        print(f"\nMarked {count} memories as summarized")
    
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Nightly reverie management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # status
    subparsers.add_parser("status", help="Show status of unsummarized memories")
    
    # get-latest
    subparsers.add_parser("get-latest", help="Get latest reverie")
    
    # get
    get_parser = subparsers.add_parser("get", help="Get reverie by date")
    get_parser.add_argument("--date", type=date.fromisoformat, required=True, help="Date (YYYY-MM-DD)")
    
    # list
    list_parser = subparsers.add_parser("list", help="List recent reveries")
    list_parser.add_argument("--limit", type=int, default=10, help="Number to show")
    
    # generate
    gen_parser = subparsers.add_parser("generate", help="Generate reverie for a date")
    gen_parser.add_argument("--date", type=date.fromisoformat, help="Date (YYYY-MM-DD), defaults to yesterday")
    gen_parser.add_argument("--mark", action="store_true", help="Mark memories as summarized")
    
    args = parser.parse_args()
    
    commands = {
        "status": cmd_status,
        "get-latest": cmd_get_latest,
        "get": cmd_get,
        "list": cmd_list,
        "generate": cmd_generate,
    }
    
    commands[args.command](args)


if __name__ == "__main__":
    main()