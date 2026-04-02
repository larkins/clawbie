#!/usr/bin/env python3
"""Generate a nightly reverie by synthesizing memories with an LLM."""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# Add clawbie path for imports
sys.path.insert(0, str(Path.home() / "git" / "clawbie"))

from psycopg import connect


def get_connection():
    """Get database connection."""
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
        raise ValueError("DATABASE_URL not found")
    return connect(db_url)


def fetch_memories(conn, target_date: date) -> list[dict]:
    """Fetch all unsummarized memories for a date."""
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


def synthesize_memories(memories: list[dict], target_date: date) -> dict:
    """Call LLM to synthesize memories into a reverie."""
    # Build the prompt with all memory texts
    memory_texts = []
    for i, m in enumerate(memories):
        text = m['memory_text']
        # Truncate very long memories to keep prompt manageable
        if len(text) > 2000:
            text = text[:2000] + "..."
        memory_texts.append(f"[{i+1}] {text}")
    
    full_text = "\n\n".join(memory_texts)
    
    prompt = f"""You are generating a nightly reverie - a daily summary for an AI assistant named Clawbie.

Date: {target_date}

The following are {len(memories)} memories from today. Each memory is an interaction, thought, or observation.
Synthesize these into a coherent summary that captures:
1. What happened today - key events, decisions, progress, blockers
2. Reflections - insights, patterns, things learned
3. Next day ideas - actionable items for continuity

Keep it concise but meaningful. Focus on what matters for continuity.

MEMORIES:
{full_text}

---

Generate the nightly reverie in this JSON format:
{{
  "summary_md": "## Summary\\n\\n[Bullet points of key events and progress]",
  "reflections": "## Reflections\\n\\n[Insights and patterns observed]",
  "next_day_ideas": "## Next Day Ideas\\n\\n[Actionable items for tomorrow]"
}}"""

    # Call the LLM via the inference host
    import requests
    
    inference_host = os.environ.get("INFERENCE_HOST", "")
    model = os.environ.get("INFERENCE_MODEL", "")
    if not inference_host or not model:
        raise ValueError("INFERENCE_HOST and INFERENCE_MODEL must be set in environment or .env")
    
    try:
        response = requests.post(
            f"{inference_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": 4096,
                    "temperature": 0.7
                }
            },
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        response_text = result.get("response", "")
    except Exception as e:
        print(f"LLM call failed: {e}")
        # Fallback to simple summary
        response_text = f'{{"summary_md": "## Summary\\n\\n- {len(memories)} memories processed\\n- Various interactions and tasks completed", "reflections": "## Reflections\\n\\n- Unable to synthesize due to LLM error", "next_day_ideas": "## Next Day Ideas\\n\\n- Review raw memories for context"}}'
    
    # Parse JSON from response
    try:
        # Find JSON in response
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start != -1 and end > start:
            json_str = response_text[start:end]
            data = json.loads(json_str)
            return {
                "summary_md": data.get("summary_md", ""),
                "reflections": data.get("reflections", ""),
                "next_day_ideas": data.get("next_day_ideas", "")
            }
    except json.JSONDecodeError:
        pass
    
    # Fallback if JSON parsing fails
    return {
        "summary_md": f"## Summary\n\n- Processed {len(memories)} memories for {target_date}\n- Day included various interactions and tasks",
        "reflections": "## Reflections\n\n- Various interactions throughout the day",
        "next_day_ideas": "## Next Day Ideas\n\n- Continue from previous context"
    }


def insert_reverie(conn, target_date: date, summary_md: str, reflections: str, next_day_ideas: str, memory_count: int) -> int:
    """Insert reverie into database."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO nightly_reverie (date, summary_md, reflections, next_day_ideas, memory_count, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (date) DO UPDATE SET
            summary_md = EXCLUDED.summary_md,
            reflections = EXCLUDED.reflections,
            next_day_ideas = EXCLUDED.next_day_ideas,
            memory_count = EXCLUDED.memory_count,
            created_at = EXCLUDED.created_at
        RETURNING id
    """, (target_date, summary_md, reflections, next_day_ideas, memory_count, datetime.now()))
    reverie_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    return reverie_id


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


def send_email(summary_md: str, reflections: str, next_day_ideas: str, target_date: date):
    """Send reverie via email."""
    import requests
    
    email_server = os.environ.get("EMAIL_SERVER", "")
    email_address = os.environ.get("EMAIL_ADDRESS", "")
    email_password = os.environ.get("EMAIL_PASSWORD", "")
    email_to = os.environ.get("EMAIL_TO", email_address)

    if not email_server or not email_address or not email_password:
        raise ValueError("EMAIL_SERVER, EMAIL_ADDRESS, and EMAIL_PASSWORD must be set in environment or .env")
    
    subject = f"Nightly Reverie - {target_date}"
    
    # Build HTML body
    html_body = f"""<!DOCTYPE html>
<html>
<head><title>Nightly Reverie - {target_date}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
<h1 style="color: #2c3e50;">🌙 Nightly Reverie - {target_date}</h1>

<h2 style="color: #34495e;">Summary</h2>
<div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
{summary_md.replace('## Summary', '').strip()}
</div>

<h2 style="color: #34495e;">Reflections</h2>
<div style="background: #e8f5e9; padding: 15px; border-radius: 8px;">
{reflections.replace('## Reflections', '').strip()}
</div>

<h2 style="color: #34495e;">Next Day Ideas</h2>
<div style="background: #fff3e0; padding: 15px; border-radius: 8px;">
{next_day_ideas.replace('## Next Day Ideas', '').strip()}
</div>

<hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
<p style="color: #666; font-size: 12px;">Generated by Clawbie - Your AI Assistant</p>
</body>
</html>"""

    try:
        # First, login to get session
        login_resp = requests.post(
            f"{email_server}/api/login",
            json={"email": email_address, "password": email_password},
            timeout=30
        )
        login_resp.raise_for_status()
        session_id = login_resp.json().get("session_id")
        
        # Send the email
        send_resp = requests.post(
            f"{email_server}/api/send",
            headers={"X-Session-ID": session_id},
            json={
                "to": email_to,
                "subject": subject,
                "body_html": html_body
            },
            timeout=30
        )
        send_resp.raise_for_status()
        print(f"Email sent to {email_to}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate nightly reverie")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="Date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    print(f"Generating reverie for {args.date}")
    
    # Load environment from .env
    env_path = Path.home() / "git" / "clawbie" / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    value = value.strip().strip('"')
                    if key not in os.environ:
                        os.environ[key] = value
    
    conn = get_connection()
    
    # Fetch memories
    memories = fetch_memories(conn, args.date)
    print(f"Found {len(memories)} memories")
    
    if not memories:
        print("No memories to summarize")
        conn.close()
        return
    
    # Synthesize with LLM
    print("Synthesizing memories...")
    result = synthesize_memories(memories, args.date)
    
    # Insert into database
    print("Saving reverie to database...")
    reverie_id = insert_reverie(
        conn, 
        args.date,
        result["summary_md"],
        result["reflections"],
        result["next_day_ideas"],
        len(memories)
    )
    print(f"Reverie ID: {reverie_id}")
    
    # Mark memories as summarized
    memory_ids = [m["id"] for m in memories]
    count = mark_memories_summarized(conn, memory_ids)
    print(f"Marked {count} memories as summarized")
    
    conn.close()
    
    # Send email
    print("Sending email...")
    send_email(
        result["summary_md"],
        result["reflections"],
        result["next_day_ideas"],
        args.date
    )
    
    print(f"\nReverie for {args.date} complete!")
    print(f"\n--- Summary ---\n{result['summary_md']}")
    print(f"\n--- Reflections ---\n{result['reflections']}")
    print(f"\n--- Next Day Ideas ---\n{result['next_day_ideas']}")


if __name__ == "__main__":
    main()