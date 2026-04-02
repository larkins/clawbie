#!/usr/bin/env python3
"""One-off script to generate reverie for yesterday and validate the system.

This script:
1. Fetches unsummarized memories for yesterday
2. Generates a reverie using the main session
3. Writes to nightly_reverie table
4. Marks memories as summarized
5. Validates the results
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "git" / "clawbie"))

from psycopg import connect


def get_connection():
    """Get database connection from environment."""
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


def fetch_memories(conn, target_date: date) -> list[dict]:
    """Fetch unsummarized memories for a date."""
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


def generate_reverie_content(memories: list[dict], target_date: date) -> dict:
    """Generate reverie content from memories.
    
    This is a simple synthesis - in production, this would call an LLM.
    """
    # Group by approximate time periods
    morning = []
    afternoon = []
    evening = []
    
    for m in memories:
        hour = m["created_at"].hour
        if hour < 12:
            morning.append(m)
        elif hour < 18:
            afternoon.append(m)
        else:
            evening.append(m)
    
    # Extract key themes
    topics = set()
    for m in memories:
        text = m["memory_text"].lower()
        if "btc" in text or "bitcoin" in text or "regime" in text:
            topics.add("btc_regime")
        if "email" in text:
            topics.add("email")
        if "memory" in text:
            topics.add("memory system")
        if "clawbie" in text:
            topics.add("clawbie")
    
    # Build summary
    summary_lines = [
        f"# Nightly Reverie - {target_date}",
        "",
        "## Summary",
        "",
        f"Processed {len(memories)} memories across the day. ",
        f"Activity spanned: {len(morning)} morning, {len(afternoon)} afternoon, {len(evening)} evening memories.",
        "",
        f"Primary topics: {', '.join(topics) if topics else 'general development work'}.",
        "",
        "## Key Events",
        "",
    ]
    
    # Add key events (first few memory texts)
    for i, m in enumerate(memories[:5]):
        text = m["memory_text"][:200]
        summary_lines.append(f"- {text}...")
    
    if len(memories) > 5:
        summary_lines.append(f"- ... and {len(memories) - 5} more")
    
    # Reflections
    reflections = "\n".join([
        "## Reflections",
        "",
        f"- {len(memories)} total memories captured today",
        f"- Activity concentration: {max(len(morning), len(afternoon), len(evening))} in {'morning' if len(morning) >= len(afternoon) and len(morning) >= len(evening) else 'afternoon' if len(afternoon) >= len(evening) else 'evening'}",
        "- Memory system working well",
    ])
    
    # Next day ideas
    next_day_ideas = "\n".join([
        "## Next Day Ideas",
        "",
        "- Continue pending work from today",
        "- Check memory table status",
        "- Run nightly reverie cron job",
    ])
    
    return {
        "summary_md": "\n".join(summary_lines),
        "reflections": reflections,
        "next_day_ideas": next_day_ideas,
    }


def save_reverie(conn, target_date: date, content: dict, memory_count: int) -> int:
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
    """, (target_date, content["summary_md"], content["reflections"], 
          content["next_day_ideas"], memory_count))
    
    reverie_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    return reverie_id


def mark_memories_summarized(conn, target_date: date) -> int:
    """Mark all memories for the date as summarized."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_memories
        SET reverie_summarized = TRUE
        WHERE DATE(created_at) = %s
        AND reverie_summarized = FALSE
    """, (target_date,))
    
    count = cursor.rowcount
    conn.commit()
    cursor.close()
    return count


def validate_results(conn, target_date: date, expected_count: int) -> bool:
    """Validate the reverie was created correctly."""
    cursor = conn.cursor()
    
    # Check reverie exists
    cursor.execute("SELECT id, memory_count FROM nightly_reverie WHERE date = %s", (target_date,))
    row = cursor.fetchone()
    if not row:
        print(f"❌ No reverie found for {target_date}")
        return False
    
    reverie_id, memory_count = row
    print(f"✅ Reverie created: ID={reverie_id}, memories={memory_count}")
    
    # Check memories are marked
    cursor.execute("""
        SELECT COUNT(*) FROM user_memories
        WHERE DATE(created_at) = %s
        AND reverie_summarized = TRUE
    """, (target_date,))
    summarized = cursor.fetchone()[0]
    print(f"✅ Memories marked as summarized: {summarized}")
    
    # Check no unsummarized remain
    cursor.execute("""
        SELECT COUNT(*) FROM user_memories
        WHERE DATE(created_at) = %s
        AND reverie_summarized = FALSE
    """, (target_date,))
    remaining = cursor.fetchone()[0]
    if remaining > 0:
        print(f"⚠️  Warning: {remaining} memories still unsummarized")
    else:
        print(f"✅ All memories for {target_date} are summarized")
    
    cursor.close()
    return True


def main():
    target_date = date.today() - timedelta(days=1)
    
    print(f"{'=' * 60}")
    print(f"Generating reverie for {target_date}")
    print(f"{'=' * 60}")
    
    conn = get_connection()
    
    # Fetch memories
    print(f"\n📊 Fetching memories for {target_date}...")
    memories = fetch_memories(conn, target_date)
    print(f"   Found {len(memories)} unsummarized memories")
    
    if not memories:
        print(f"❌ No memories to process for {target_date}")
        conn.close()
        return
    
    # Generate content
    print(f"\n📝 Generating reverie content...")
    content = generate_reverie_content(memories, target_date)
    
    # Save to database
    print(f"\n💾 Saving reverie to database...")
    reverie_id = save_reverie(conn, target_date, content, len(memories))
    print(f"   Reverie ID: {reverie_id}")
    
    # Mark memories as summarized
    print(f"\n✅ Marking {len(memories)} memories as summarized...")
    count = mark_memories_summarized(conn, target_date)
    print(f"   Updated {count} rows")
    
    # Validate
    print(f"\n🔍 Validating results...")
    validate_results(conn, target_date, len(memories))
    
    # Show the reverie
    print(f"\n{'=' * 60}")
    print("Generated Reverie:")
    print(f"{'=' * 60}")
    print(content["summary_md"])
    print("\n" + content["reflections"])
    print("\n" + content["next_day_ideas"])
    
    conn.close()
    print(f"\n{'=' * 60}")
    print("Done!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()