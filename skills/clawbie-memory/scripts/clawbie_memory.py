#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
PROMISE_PATTERNS = [
    r"report back",
    r"i['’]?ll update",
    r"i['’]?ll let you know",
    r"i['’]?ll confirm",
    r"when finished",
    r"follow up",
    r"check and report",
    r"i['’]?ll tell you when it['’]?s done",
    r"i['’]?m checking",
    r"i['’]?m pulling",
    r"i['’]?ll send",
    r"i['’]?ll message",
    r"i['’]?ll come back with",
]
CLOSE_PATTERNS = [
    r"\bdone:",
    r"\bfailed:",
    r"\bcompleted\b",
    r"\bsent\b",
    r"\bresolved\b",
    r"\bfixed\b",
    r"i sent",
    r"i updated",
]


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if '=' not in line or line.strip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        env[key] = value
    return env


def run_sql(sql: str, env_path: Path) -> list[dict[str, Any]]:
    env = load_env(env_path)
    psql_env = {
        'PGPASSWORD': env['DB_PASSWORD'],
    }
    command = [
        'psql',
        '-h', env['POSTGRES_HOST'],
        '-p', env['POSTGRES_PORT'],
        '-U', env['DB_USER'],
        '-d', env['DB_NAME'],
        '-A',
        '-t',
        '-P', 'pager=off',
        '-c', sql,
    ]
    result = subprocess.run(command, capture_output=True, text=True, env={**os.environ, **psql_env})
    if result.returncode != 0:
        # Verbose error for heartbeat debugging
        import sys
        error_msg = result.stderr.strip() or 'psql failed'
        print(f"\n=== PostgreSQL Connection Error ===", file=sys.stderr)
        print(f"Error: {error_msg}", file=sys.stderr)
        print(f"\nConnection details:", file=sys.stderr)
        print(f"  Host: {env.get('POSTGRES_HOST', 'NOT SET')}", file=sys.stderr)
        print(f"  Port: {env.get('POSTGRES_PORT', 'NOT SET')}", file=sys.stderr)
        print(f"  Database: {env.get('DB_NAME', 'NOT SET')}", file=sys.stderr)
        print(f"  User: {env.get('DB_USER', 'NOT SET')}", file=sys.stderr)
        print(f"  Password: {'*' * len(env.get('DB_PASSWORD', ''))} ({len(env.get('DB_PASSWORD', ''))} chars)", file=sys.stderr)
        print(f"  Env file: {env_path}", file=sys.stderr)
        print(f"\nTroubleshooting:", file=sys.stderr)
        print(f"  1. Check if PostgreSQL is running: systemctl status postgresql", file=sys.stderr)
        print(f"  2. Verify password in {env_path}", file=sys.stderr)
        print(f"  3. Test manually: PGPASSWORD=<password> psql -h localhost -U postgres -d clawbie -c 'SELECT 1'", file=sys.stderr)
        print(f"  4. Check postgresql logs: journalctl -u postgresql -n 50", file=sys.stderr)
        raise SystemExit(f"PostgreSQL connection failed: {error_msg}")
    output = result.stdout.strip()
    if not output:
        return []
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def sql_recent(limit: int) -> str:
    return f"""
SELECT json_build_object(
  'id', id,
  'created_at', created_at,
  'source_type', source_type,
  'source_ref', source_ref,
  'memory_text', LEFT(COALESCE(memory_text, ''), 240),
  'reflection', LEFT(COALESCE(reflection, ''), 240)
)
FROM public.user_memories
ORDER BY id DESC
LIMIT {int(limit)};
"""


def sql_since_id(start_id: int, limit: int) -> str:
    return f"""
SELECT json_build_object(
  'id', id,
  'created_at', created_at,
  'source_type', source_type,
  'source_ref', source_ref,
  'memory_text', LEFT(COALESCE(memory_text, ''), 240),
  'reflection', LEFT(COALESCE(reflection, ''), 240)
)
FROM public.user_memories
WHERE id >= {int(start_id)}
ORDER BY id ASC
LIMIT {int(limit)};
"""


def sql_text_search(query: str, limit: int) -> str:
    safe = query.replace("'", "''")
    return f"""
SELECT json_build_object(
  'id', id,
  'created_at', created_at,
  'source_type', source_type,
  'source_ref', source_ref,
  'memory_text', LEFT(COALESCE(memory_text, ''), 240),
  'reflection', LEFT(COALESCE(reflection, ''), 240)
)
FROM public.user_memories
WHERE COALESCE(memory_text, '') ILIKE '%{safe}%'
   OR COALESCE(reflection, '') ILIKE '%{safe}%'
   OR COALESCE(source_ref, '') ILIKE '%{safe}%'
ORDER BY id DESC
LIMIT {int(limit)};
"""


def classify_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compiled_open = [re.compile(p, re.I) for p in PROMISE_PATTERNS]
    compiled_close = [re.compile(p, re.I) for p in CLOSE_PATTERNS]
    open_rows = []
    close_rows = []
    for row in rows:
        text = f"{row.get('memory_text','')}\n{row.get('reflection','')}"
        matched_open = [p.pattern for p in compiled_open if p.search(text)]
        matched_close = [p.pattern for p in compiled_close if p.search(text)]
        if matched_open:
            open_rows.append({
                'id': row.get('id'),
                'created_at': row.get('created_at'),
                'source_ref': row.get('source_ref'),
                'open_markers': matched_open,
                'close_markers': matched_close,
                'memory_text': row.get('memory_text'),
            })
        elif matched_close:
            close_rows.append({
                'id': row.get('id'),
                'created_at': row.get('created_at'),
                'source_ref': row.get('source_ref'),
                'close_markers': matched_close,
                'memory_text': row.get('memory_text'),
            })
    return {'open_candidates': open_rows, 'close_candidates': close_rows}


def cmd_recent(args: argparse.Namespace) -> None:
    print_json(run_sql(sql_recent(args.limit), Path(args.env)))


def cmd_since_id(args: argparse.Namespace) -> None:
    print_json(run_sql(sql_since_id(args.start_id, args.limit), Path(args.env)))


def cmd_text_search(args: argparse.Namespace) -> None:
    print_json(run_sql(sql_text_search(args.query, args.limit), Path(args.env)))


def cmd_promise_scan(args: argparse.Namespace) -> None:
    rows = run_sql(sql_recent(args.limit), Path(args.env))
    print_json(classify_rows(rows))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Query Clawbie user_memories directly')
    parser.add_argument('--env', default=str(DEFAULT_ENV_PATH), help='Path to clawbie .env')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('recent')
    p.add_argument('--limit', type=int, default=10)
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser('since-id')
    p.add_argument('start_id', type=int)
    p.add_argument('--limit', type=int, default=40)
    p.set_defaults(func=cmd_since_id)

    p = sub.add_parser('text-search')
    p.add_argument('--query', required=True)
    p.add_argument('--limit', type=int, default=20)
    p.set_defaults(func=cmd_text_search)

    p = sub.add_parser('promise-scan')
    p.add_argument('--limit', type=int, default=20)
    p.set_defaults(func=cmd_promise_scan)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
