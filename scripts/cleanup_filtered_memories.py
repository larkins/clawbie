#!/usr/bin/env python3
"""Clean up filtered memories from user_memories table.

Removes rows where memory_text or reflection starts with heartbeat
system message prefixes that should have been filtered during ingestion.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from memory_engine.ingestion import FILTERED_PREFIXES


def get_connection():
    """Get database connection from environment. DATABASE_URL must be set."""
    from psycopg import connect
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is required")
    return connect(db_url)


def count_filtered_rows(conn, prefixes: list[str]) -> tuple[int, int]:
    """Count rows that match filter prefixes.
    
    Returns (memory_text_count, reflection_count)
    """
    cursor = conn.cursor()
    
    # Count by memory_text
    memory_text_count = 0
    for prefix in prefixes:
        cursor.execute(
            "SELECT COUNT(*) FROM user_memories WHERE memory_text LIKE %s",
            (prefix + "%",)
        )
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"  memory_text starts with '{prefix[:50]}...': {count} rows")
            memory_text_count += count
    
    # Count by reflection
    reflection_count = 0
    for prefix in prefixes:
        cursor.execute(
            "SELECT COUNT(*) FROM user_memories WHERE reflection LIKE %s",
            (prefix + "%",)
        )
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"  reflection starts with '{prefix[:50]}...': {count} rows")
            reflection_count += count
    
    # Dedupe (rows where both memory_text and reflection match)
    cursor.execute("""
        SELECT COUNT(*) FROM user_memories 
        WHERE memory_text LIKE %s OR reflection LIKE %s
    """, (prefixes[0] + "%", prefixes[0] + "%"))
    # For simplicity, we'll handle deduplication in the delete
    
    cursor.close()
    return memory_text_count, reflection_count


def delete_filtered_rows(conn, prefixes: list[str]) -> int:
    """Delete rows matching filter prefixes.
    
    Returns number of deleted rows.
    """
    cursor = conn.cursor()
    deleted_total = 0
    
    for prefix in prefixes:
        # Delete where memory_text starts with prefix
        cursor.execute(
            "DELETE FROM user_memories WHERE memory_text LIKE %s",
            (prefix + "%",)
        )
        deleted_total += cursor.rowcount
        
        # Delete where reflection starts with prefix (but memory_text doesn't, to avoid double-delete)
        cursor.execute(
            "DELETE FROM user_memories WHERE reflection LIKE %s AND memory_text NOT LIKE %s",
            (prefix + "%", prefix + "%")
        )
        deleted_total += cursor.rowcount
    
    conn.commit()
    cursor.close()
    return deleted_total


def main():
    print("=" * 60)
    print("Cleaning up filtered memories from user_memories table")
    print("=" * 60)
    
    print(f"\nFilter prefixes ({len(FILTERED_PREFIXES)}):")
    for prefix in FILTERED_PREFIXES:
        print(f"  - '{prefix}'")
    
    conn = get_connection()
    
    print("\n📊 Counting rows to delete...")
    memory_count, reflection_count = count_filtered_rows(conn, FILTERED_PREFIXES)
    print(f"\nTotal matching rows: {memory_count} (memory_text) + {reflection_count} (reflection)")
    
    # Get total before
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM user_memories")
    total_before = cursor.fetchone()[0]
    cursor.close()
    print(f"Total rows in table: {total_before}")
    
    # Ask for confirmation
    print("\n⚠️  This will delete these filtered rows permanently.")
    response = input("Proceed with deletion? [y/N]: ").strip().lower()
    if response != 'y':
        print("Aborted.")
        conn.close()
        return
    
    print("\n🗑️  Deleting filtered rows...")
    deleted = delete_filtered_rows(conn, FILTERED_PREFIXES)
    print(f"Deleted {deleted} rows")
    
    # Get total after
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM user_memories")
    total_after = cursor.fetchone()[0]
    cursor.close()
    
    print(f"\n✅ Cleaned up {deleted} rows")
    print(f"   Before: {total_before} rows")
    print(f"   After:  {total_after} rows")
    print(f"   Removed: {total_before - total_after} rows")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("Cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()