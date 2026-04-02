#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memory_engine.config import load_config
from memory_engine.db import open_connection
from memory_engine.status_commentary import is_status_commentary_text


@dataclass(frozen=True)
class BackfillCounts:
    total_rows: int
    classified_commentary_rows: int
    classified_with_status_true: int
    classified_with_raw_embedding: int
    classified_with_reflection: int
    classified_with_reflection_embedding: int
    classified_with_reason_status_commentary: int


def _content_column(conn: Any) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'user_memories'
              AND column_name IN ('content', 'memory_text')
            """
        )
        columns = {row["column_name"] for row in cur.fetchall()}
    if "content" in columns:
        return "content"
    if "memory_text" in columns:
        return "memory_text"
    raise RuntimeError("user_memories must include either 'content' or 'memory_text'")


def _has_status_commentary_column(conn: Any) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'user_memories'
              AND column_name = 'status_commentary'
            LIMIT 1
            """
        )
        return cur.fetchone() is not None


def _row_is_status_commentary(*, content: str, metadata: dict[str, Any]) -> bool:
    role = metadata.get("role")
    channel = metadata.get("channel")
    return is_status_commentary_text(
        text=content,
        role=role if isinstance(role, str) else None,
        channel=channel if isinstance(channel, str) else None,
    )


def _load_candidates(conn: Any, *, content_column: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, {content_column} AS content, metadata,
                   status_commentary, raw_embedding, reflection, reflection_embedding
            FROM public.user_memories
            """
        )
        return list(cur.fetchall())


def _count_classified(rows: list[dict[str, Any]], *, classified_ids: set[Any]) -> BackfillCounts:
    classified_rows = [row for row in rows if row["id"] in classified_ids]
    return BackfillCounts(
        total_rows=len(rows),
        classified_commentary_rows=len(classified_rows),
        classified_with_status_true=sum(1 for row in classified_rows if bool(row.get("status_commentary"))),
        classified_with_raw_embedding=sum(1 for row in classified_rows if row.get("raw_embedding") is not None),
        classified_with_reflection=sum(1 for row in classified_rows if row.get("reflection") is not None),
        classified_with_reflection_embedding=sum(
            1 for row in classified_rows if row.get("reflection_embedding") is not None
        ),
        classified_with_reason_status_commentary=sum(
            1
            for row in classified_rows
            if isinstance(row.get("metadata"), dict)
            and row["metadata"].get("embedding_skipped_reason") == "status_commentary"
        ),
    )


def _format_counts(title: str, counts: BackfillCounts) -> str:
    return "\n".join(
        [
            title,
            f"  total_rows={counts.total_rows}",
            f"  classified_commentary_rows={counts.classified_commentary_rows}",
            f"  classified_with_status_true={counts.classified_with_status_true}",
            f"  classified_with_raw_embedding={counts.classified_with_raw_embedding}",
            f"  classified_with_reflection={counts.classified_with_reflection}",
            f"  classified_with_reflection_embedding={counts.classified_with_reflection_embedding}",
            f"  classified_with_reason_status_commentary={counts.classified_with_reason_status_commentary}",
        ]
    )


def run_backfill(*, config_path: Path, dry_run: bool) -> int:
    cfg = load_config(config_path)
    with open_connection(cfg.database_dsn) as conn:
        if not _has_status_commentary_column(conn):
            raise RuntimeError("status_commentary column is missing; run migration 003 first")

        content_column = _content_column(conn)
        before_rows = _load_candidates(conn, content_column=content_column)
        classified_ids = {
            row["id"]
            for row in before_rows
            if _row_is_status_commentary(
                content=(row.get("content") or ""),
                metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
            )
        }
        before = _count_classified(before_rows, classified_ids=classified_ids)
        print(_format_counts("BEFORE", before))

        before_by_id = {row["id"]: row for row in before_rows}
        to_update_ids: list[Any] = []
        for row_id in classified_ids:
            row = before_by_id[row_id]
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            is_already_clean = (
                bool(row.get("status_commentary"))
                and row.get("raw_embedding") is None
                and row.get("reflection") is None
                and row.get("reflection_embedding") is None
                and metadata.get("embedding_skipped_reason") == "status_commentary"
            )
            if not is_already_clean:
                to_update_ids.append(row_id)

        updated_count = 0
        if to_update_ids and not dry_run:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE public.user_memories
                    SET
                        status_commentary = TRUE,
                        raw_embedding = NULL,
                        reflection = NULL,
                        reflection_embedding = NULL,
                        metadata = jsonb_set(
                            COALESCE(metadata, '{}'::jsonb),
                            '{embedding_skipped_reason}',
                            '"status_commentary"',
                            true
                        )
                    WHERE id = ANY(%s)
                    RETURNING id
                    """,
                    (to_update_ids,),
                )
                updated_count = len(cur.fetchall())
            conn.commit()

        after_rows = _load_candidates(conn, content_column=content_column)
        after = _count_classified(after_rows, classified_ids=classified_ids)
        print(_format_counts("AFTER", after))
        print(f"UPDATED_ROWS={updated_count}")
        if dry_run:
            print(f"WOULD_UPDATE_ROWS={len(to_update_ids)}")
        return updated_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retroactively mark status commentary rows and clear semantic payload fields."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report counts; do not update rows.",
    )
    args = parser.parse_args()
    run_backfill(config_path=Path(args.config), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
