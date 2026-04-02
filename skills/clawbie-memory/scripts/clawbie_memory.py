#!/usr/bin/env python3
"""Clawbie Memory Engine — Query and manage memory tables.

Memory commands:
    python clawbie_memory.py recent --limit 10
    python clawbie_memory.py promise-scan --limit 20
    python clawbie_memory.py text-search --query "open source"

Project commands:
    python clawbie_memory.py project-get
    python clawbie_memory.py project-set --name "one_shot_email" --next-step "Get AWS keys"
    python clawbie_memory.py project-list
    python clawbie_memory.py project-update --next-step "..."
    python clawbie_memory.py project-complete

Intention commands:
    python clawbie_memory.py intention-add --text "Review PR #42"
    python clawbie_memory.py intention-pending
    python clawbie_memory.py intention-fulfil --id 5 --outcome success

Redirect commands:
    python clawbie_memory.py redirect-add --from-topic "chat" --to-topic "one_shot_email"
    python clawbie_memory.py redirect-recent --limit 10
    python clawbie_memory.py redirect-stats

Session state (for heartbeat):
    python clawbie_memory.py session-state
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
PROMISE_PATTERNS = [
    r"report back",
    r"i['\u2019]?ll update",
    r"i['\u2019]?ll let you know",
    r"i['\u2019]?ll confirm",
    r"when finished",
    r"follow up",
    r"check and report",
    r"i['\u2019]?ll tell you when it['\u2019]?s done",
    r"i['\u2019]?m checking",
    r"i['\u2019]?m pulling",
    r"i['\u2019]?ll send",
    r"i['\u2019]?ll message",
    r"i['\u2019]?ll come back with",
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


# ── Database helpers ──────────────────────────────────────────────────────────

def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if '=' not in line or line.strip().startswith('#'):
            continue
        key, _, value = line.partition('=')
        env[key] = value.strip().strip('"').strip("'")
    return env


def run_sql(sql: str, env_path: Path) -> list[dict[str, Any]]:
    env = load_env(env_path)
    psql_env = {'PGPASSWORD': env.get('DB_PASSWORD', '')}
    command = [
        'psql',
        '-h', env.get('POSTGRES_HOST', 'localhost'),
        '-p', env.get('POSTGRES_PORT', '5432'),
        '-U', env.get('DB_USER', 'postgres'),
        '-d', env.get('DB_NAME', 'clawbie'),
        '-A', '-t', '-P', 'pager=off', '-c', sql,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, env={**os.environ, **psql_env}
    )
    if result.returncode != 0:
        import sys
        print(f"PostgreSQL error: {result.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)
    output = result.stdout.strip()
    if not output:
        return []
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def run_sql_modify(sql: str, env_path: Path) -> None:
    env = load_env(env_path)
    psql_env = {'PGPASSWORD': env.get('DB_PASSWORD', '')}
    command = [
        'psql',
        '-h', env.get('POSTGRES_HOST', 'localhost'),
        '-p', env.get('POSTGRES_PORT', '5432'),
        '-U', env.get('DB_USER', 'postgres'),
        '-d', env.get('DB_NAME', 'clawbie'),
        '-A', '-t', '-P', 'pager=off', '-c', sql,
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, env={**os.environ, **psql_env}
    )
    if result.returncode != 0:
        import sys
        print(f"PostgreSQL error: {result.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)


def row_sql(sql: str, env_path: Path) -> dict[str, Any] | None:
    """Run SQL that returns a single row. Handles both JSON objects and primitives."""
    rows = run_sql(sql, env_path)
    if not rows:
        return None
    first = rows[0]
    # If it's a primitive (single column), wrap it
    if not isinstance(first, dict):
        return {'value': first}
    return first


def col_sql(sql: str, env_path: Path) -> list[dict[str, Any]]:
    """Run SQL that returns multiple rows."""
    return run_sql(sql, env_path)


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Memory queries ─────────────────────────────────────────────────────────────

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
    open_rows, close_rows = [], []
    for row in rows:
        text = f"{row.get('memory_text','')}\n{row.get('reflection','')}"
        matched_open = [p.pattern for p in compiled_open if p.search(text)]
        matched_close = [p.pattern for p in compiled_close if p.search(text)]
        target = open_rows if matched_open else close_rows
        target.append({
            'id': row.get('id'),
            'created_at': row.get('created_at'),
            'source_ref': row.get('source_ref'),
            'markers': matched_open or matched_close,
            'memory_text': row.get('memory_text'),
        })
    return {'open_candidates': open_rows, 'close_candidates': close_rows}


# ── Project commands ────────────────────────────────────────────────────────────

def cmd_project_get(args: argparse.Namespace, env_path: Path) -> None:
    r = row_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT id, project_name, description, status, started_at, updated_at, "
        "next_step, blocked_by, progress_note, priority "
        "FROM public.active_projects "
        "WHERE status = 'active' ORDER BY priority DESC, started_at DESC LIMIT 1"
        ") t;",
        env_path
    )
    print_json(r if r else {'active': None, 'message': 'No active project'})


def cmd_project_set(args: argparse.Namespace, env_path: Path) -> None:
    name = args.name.replace("'", "''")
    desc = (args.description or '').replace("'", "''")
    next_step = (args.next_step or '').replace("'", "''")
    priority = int(args.priority or 0)
    run_sql_modify(
        "UPDATE public.active_projects SET status = 'paused', "
        "updated_at = NOW() WHERE status = 'active';",
        env_path
    )
    run_sql_modify(
        f"INSERT INTO public.active_projects "
        f"(project_name, description, next_step, priority) "
        f"VALUES ('{name}', '{desc}', '{next_step}', {priority});",
        env_path
    )
    print_json({'ok': True, 'project': name, 'description': desc})


def cmd_project_list(args: argparse.Namespace, env_path: Path) -> None:
    print_json(col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT id, project_name, status, started_at, updated_at, "
        "next_step, blocked_by, priority "
        "FROM public.active_projects "
        "ORDER BY priority DESC, started_at DESC LIMIT 20"
        ") t;",
        env_path
    ))


def cmd_project_update(args: argparse.Namespace, env_path: Path) -> None:
    fields = []
    for field, key in [
        ('next_step', args.next_step),
        ('blocked_by', args.blocked_by),
        ('progress_note', args.progress_note),
        ('status', args.status),
        ('priority', str(args.priority)) if args.priority is not None else (None, None),
    ]:
        if key is not None:
            safe = key.replace("'", "''")
            fields.append(f"{field} = '{safe}'")
    if not fields:
        print_json({'ok': False, 'error': 'No fields to update'})
        return
    fields.append("updated_at = NOW()")
    run_sql_modify(
        f"UPDATE public.active_projects SET {', '.join(fields)} "
        "WHERE status = 'active' LIMIT 1;",
        env_path
    )
    print_json({'ok': True})


def cmd_project_complete(args: argparse.Namespace, env_path: Path) -> None:
    run_sql_modify(
        "UPDATE public.active_projects SET status = 'completed', "
        "completed_at = NOW(), updated_at = NOW() "
        "WHERE status = 'active' LIMIT 1;",
        env_path
    )
    print_json({'ok': True, 'status': 'completed'})


# ── Intention commands ─────────────────────────────────────────────────────────

def cmd_intention_add(args: argparse.Namespace, env_path: Path) -> None:
    session_id = args.session_id or 'main'
    text = args.text.replace("'", "''")
    desc = (args.description or '').replace("'", "''")
    urgency = args.urgency or 'normal'
    deadline_clause = f", deadline = '{args.deadline}'" if args.deadline else ""
    proj = row_sql(
        "SELECT id FROM public.active_projects WHERE status = 'active' LIMIT 1;",
        env_path
    )
    project_id = str(proj['value']) if proj else 'NULL'
    run_sql_modify(
        f"INSERT INTO public.session_intentions "
        f"(session_id, project_id, intention_text, description, urgency{deadline_clause}) "
        f"VALUES ('{session_id}', {project_id}, '{text}', '{desc}', '{urgency}');",
        env_path
    )
    print_json({'ok': True, 'intention': args.text})


def cmd_intention_pending(args: argparse.Namespace, env_path: Path) -> None:
    print_json(col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT id, session_id, intention_text, description, urgency, deadline, created_at "
        "FROM public.session_intentions "
        "WHERE status IN ('pending', 'in_progress') "
        "ORDER BY CASE urgency WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT 20"
        ") t;",
        env_path
    ))


def cmd_intention_fulfil(args: argparse.Namespace, env_path: Path) -> None:
    note = (args.note or '').replace("'", "''")
    outcome = args.outcome or 'success'
    run_sql_modify(
        f"UPDATE public.session_intentions SET status = 'fulfilled', "
        f"fulfilled_at = NOW(), updated_at = NOW(), "
        f"outcome = '{outcome}', fulfillment_note = '{note}' "
        f"WHERE id = {args.id};",
        env_path
    )
    print_json({'ok': True, 'id': args.id, 'outcome': outcome})


# ── Redirect commands ─────────────────────────────────────────────────────────

def cmd_redirect_add(args: argparse.Namespace, env_path: Path) -> None:
    session_id = args.session_id or 'main'
    from_txt = args.from_topic.replace("'", "''")
    to_txt = args.to_topic.replace("'", "''")
    reason = (args.reason or '').replace("'", "''")
    accepted = 'TRUE' if args.accepted else 'FALSE'
    run_sql_modify(
        f"INSERT INTO public.session_redirects "
        f"(session_id, redirected_from, redirected_to, reason, accepted) "
        f"VALUES ('{session_id}', '{from_txt}', '{to_txt}', '{reason}', {accepted});",
        env_path
    )
    print_json({'ok': True, 'from': args.from_topic, 'to': args.to_topic})


def cmd_redirect_recent(args: argparse.Namespace, env_path: Path) -> None:
    limit = int(args.limit)
    print_json(col_sql(
        f"SELECT row_to_json(t) FROM ("
        f"SELECT redirected_from, redirected_to, reason, accepted, created_at "
        f"FROM public.session_redirects "
        f"ORDER BY created_at DESC LIMIT {limit}"
        f") t;",
        env_path
    ))


def cmd_redirect_stats(args: argparse.Namespace, env_path: Path) -> None:
    print_json(col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT redirected_from, redirected_to, COUNT(*) as count, "
        "BOOL_AND(accepted) as accepted "
        "FROM public.session_redirects "
        "GROUP BY redirected_from, redirected_to "
        "ORDER BY count DESC LIMIT 20"
        ") t;",
        env_path
    ))


# ── Session state (for heartbeat) ────────────────────────────────────────────

def cmd_session_state(args: argparse.Namespace, env_path: Path) -> None:
    project = row_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT id, project_name, description, status, next_step, blocked_by, "
        "progress_note, priority, started_at, updated_at "
        "FROM public.active_projects WHERE status = 'active' LIMIT 1"
        ") t;",
        env_path
    )
    intentions = col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT id, intention_text, urgency, deadline, created_at "
        "FROM public.session_intentions "
        "WHERE status IN ('pending', 'in_progress') "
        "ORDER BY CASE urgency WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT 10"
        ") t;",
        env_path
    )
    overdue = col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT id, intention_text, deadline FROM public.session_intentions "
        "WHERE status IN ('pending', 'in_progress') AND deadline < NOW() "
        "ORDER BY deadline ASC LIMIT 10"
        ") t;",
        env_path
    )
    redirects = col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT redirected_from, redirected_to, reason, accepted, created_at "
        "FROM public.session_redirects ORDER BY created_at DESC LIMIT 5"
        ") t;",
        env_path
    )
    print_json({
        'project': project,
        'pending_intentions': intentions,
        'overdue_intentions': overdue,
        'recent_redirects': redirects,
    })


# ── Command dispatch ───────────────────────────────────────────────────────────

def cmd_recent(args: argparse.Namespace, env_path: Path) -> None:
    print_json(run_sql(sql_recent(args.limit), env_path))


def cmd_since_id(args: argparse.Namespace, env_path: Path) -> None:
    print_json(run_sql(sql_since_id(args.start_id, args.limit), env_path))


def cmd_text_search(args: argparse.Namespace, env_path: Path) -> None:
    print_json(run_sql(sql_text_search(args.query, args.limit), env_path))


def cmd_promise_scan(args: argparse.Namespace, env_path: Path) -> None:
    rows = run_sql(sql_recent(args.limit), env_path)
    print_json(classify_rows(rows))


def cmd_core_write(args: argparse.Namespace, env_path: Path) -> None:
    text = args.text.replace("'", "''")
    category = args.category.replace("'", "''")
    run_sql_modify(
        f"INSERT INTO public.core_memories (category, memory_text, source) "
        f"VALUES ('{category}', '{text}', '{args.source or 'conversation'}');",
        env_path
    )
    print_json({'ok': True, 'category': args.category, 'text': args.text})


def cmd_core_read(args: argparse.Namespace, env_path: Path) -> None:
    limit = int(args.limit)
    category_clause = f"WHERE active = TRUE AND category = '{args.category.replace(chr(39), chr(39)+chr(39))}'" if args.category else "WHERE active = TRUE"
    print_json(col_sql(
        f"SELECT row_to_json(t) FROM ("
        f"SELECT id, category, memory_text, source, created_at "
        f"FROM public.core_memories {category_clause} "
        f"ORDER BY created_at DESC LIMIT {limit}"
        f") t;",
        env_path
    ))


def cmd_core_update(args: argparse.Namespace, env_path: Path) -> None:
    text = args.text.replace("'", "''")
    run_sql_modify(
        f"UPDATE public.core_memories SET memory_text = '{text}', "
        f"updated_at = NOW() WHERE id = {args.id};",
        env_path
    )
    print_json({'ok': True, 'id': args.id})


def cmd_core_archive(args: argparse.Namespace, env_path: Path) -> None:
    run_sql_modify(
        f"UPDATE public.core_memories SET active = FALSE, updated_at = NOW() "
        f"WHERE id = {args.id};",
        env_path
    )
    print_json({'ok': True, 'id': args.id, 'active': False})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Clawbie Memory Engine — memories, projects, and temporal awareness'
    )
    parser.add_argument(
        '--env', default=str(DEFAULT_ENV_PATH),
        help='Path to clawbie .env'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # Memory queries
    p = sub.add_parser('recent', help='Recent memories')
    p.add_argument('--limit', type=int, default=10)
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser('since-id', help='Memories since a given ID')
    p.add_argument('start_id', type=int)
    p.add_argument('--limit', type=int, default=40)
    p.set_defaults(func=cmd_since_id)

    p = sub.add_parser('text-search', help='Full-text search memories')
    p.add_argument('--query', required=True)
    p.add_argument('--limit', type=int, default=20)
    p.set_defaults(func=cmd_text_search)

    p = sub.add_parser('promise-scan', help='Detect open/closed promises in recent memories')
    p.add_argument('--limit', type=int, default=20)
    p.set_defaults(func=cmd_promise_scan)

    # Project commands
    p = sub.add_parser('project-get', help='Get the current active project')
    p.set_defaults(func=cmd_project_get)

    p = sub.add_parser('project-set', help='Set a new active project (pauses current)')
    p.add_argument('--name', required=True, help='Project name')
    p.add_argument('--description', help='Project description')
    p.add_argument('--next-step', help='Next actionable step')
    p.add_argument('--priority', type=int, default=0)
    p.set_defaults(func=cmd_project_set)

    p = sub.add_parser('project-list', help='List all projects')
    p.set_defaults(func=cmd_project_list)

    p = sub.add_parser('project-update', help='Update active project fields')
    p.add_argument('--next-step')
    p.add_argument('--blocked-by')
    p.add_argument('--progress-note')
    p.add_argument('--status')
    p.add_argument('--priority', type=int)
    p.set_defaults(func=cmd_project_update)

    p = sub.add_parser('project-complete', help='Mark active project as completed')
    p.set_defaults(func=cmd_project_complete)

    # Intention commands
    p = sub.add_parser('intention-add', help='Add a new session intention')
    p.add_argument('--text', required=True, help='Intention text')
    p.add_argument('--description')
    p.add_argument('--urgency', default='normal',
                   choices=['low', 'normal', 'high', 'critical'])
    p.add_argument('--deadline', help='ISO datetime deadline')
    p.add_argument('--session-id', help='Session ID (default: main)')
    p.set_defaults(func=cmd_intention_add)

    p = sub.add_parser('intention-pending', help='List pending intentions')
    p.set_defaults(func=cmd_intention_pending)

    p = sub.add_parser('intention-fulfil', help='Mark an intention as fulfilled')
    p.add_argument('--id', required=True, type=int)
    p.add_argument('--outcome', default='success',
                   choices=['success', 'partial', 'failed', 'redirected'])
    p.add_argument('--note', help='Fulfillment note')
    p.set_defaults(func=cmd_intention_fulfil)

    # Redirect commands
    p = sub.add_parser('redirect-add', help='Log a conversation redirect')
    p.add_argument('--from-topic', required=True, help='What we redirected from')
    p.add_argument('--to-topic', required=True, help='What we redirected to')
    p.add_argument('--reason')
    p.add_argument('--accepted', type=lambda x: x.lower() == 'true', default=True)
    p.add_argument('--session-id', help='Session ID (default: main)')
    p.set_defaults(func=cmd_redirect_add)

    p = sub.add_parser('redirect-recent', help='Recent redirects')
    p.add_argument('--limit', type=int, default=10)
    p.set_defaults(func=cmd_redirect_recent)

    p = sub.add_parser('redirect-stats', help='Redirect pattern statistics')
    p.set_defaults(func=cmd_redirect_stats)

    # Core memory commands
    p = sub.add_parser('core-write', help='Write a new core memory')
    p.add_argument('--text', required=True, help='Memory text')
    p.add_argument('--category', required=True,
                   choices=['business', 'product', 'personality', 'architecture', 'values', 'relationships', 'goals'],
                   help='Category')
    p.add_argument('--source', default='conversation',
                   choices=['conversation', 'explicit', 'inferred'])
    p.set_defaults(func=cmd_core_write)

    p = sub.add_parser('core-read', help='Read core memories')
    p.add_argument('--category',
                   choices=['business', 'product', 'personality', 'architecture', 'values', 'relationships', 'goals'],
                   help='Filter by category')
    p.add_argument('--limit', type=int, default=20)
    p.set_defaults(func=cmd_core_read)

    p = sub.add_parser('core-list', help='List all core memory categories')
    p.set_defaults(func=lambda a, e: print_json(col_sql(
        "SELECT row_to_json(t) FROM ("
        "SELECT category, COUNT(*) as count FROM public.core_memories "
        "WHERE active = TRUE GROUP BY category ORDER BY count DESC"
        ") t;",
        e
    )))

    p = sub.add_parser('core-update', help='Update a core memory')
    p.add_argument('--id', required=True, type=int)
    p.add_argument('--text', required=True)
    p.set_defaults(func=cmd_core_update)

    p = sub.add_parser('core-archive', help='Archive a core memory (soft delete)')
    p.add_argument('--id', required=True, type=int)
    p.set_defaults(func=cmd_core_archive)

    # Heartbeat command
    p = sub.add_parser('session-state', help='Full state for heartbeat check')
    p.set_defaults(func=cmd_session_state)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    env_path = Path(args.env)
    if not env_path.exists():
        import sys
        print(f"Env file not found: {env_path}", file=sys.stderr)
        sys.exit(1)
    args.func(args, env_path)


if __name__ == '__main__':
    main()
