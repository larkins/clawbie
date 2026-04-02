# Nightly Reverie Generation Prompt

You are generating a nightly reverie - a synthesis of the previous day's memories into a coherent narrative for day-to-day continuity.

## Process

1. **Retrieve unsummarized memories** for the target date:
   ```bash
   python skills/nightly-reverie/scripts/reverie.py status
   ```

2. **Fetch the unprocessed memories from the database** (previous day):
   - Query `user_memories` where `reverie_summarized = FALSE` and date = target
   - Order by `created_at` to maintain temporal sequence
   - Note the flow of events, context, and decisions

3. **Synthesize into a coherent narrative**:
   - What were the main themes of the day?
   - What progress was made?
   - What blockers or issues arose?
   - What decisions were made?
   - What's pending or incomplete?

4. **Write to `nightly_reverie` table**:
   - `summary_md`: Markdown-formatted summary of the day
   - `reflections`: Insights and learnings from the day
   - `next_day_ideas`: Actionable items and continuity notes for the next day
   - `memory_count`: Number of memories processed

5. **Mark memories as summarized**:
   ```sql
   UPDATE user_memories SET reverie_summarized = TRUE WHERE DATE(created_at) = 'TARGET_DATE';
   ```

6. **Email the summary** to Michael:
   - Use the protophysics-email skill
   - Subject: `Nightly Reverie - YYYY-MM-DD`
   - Body: Markdown rendered to HTML

## Output Format

```markdown
# Nightly Reverie - YYYY-MM-DD

## Summary
[2-3 paragraph summary of the day's events and progress]

## Key Decisions
- [Decision 1 and rationale]
- [Decision 2 and rationale]

## Blockers & Issues
- [Issue 1 and status]
- [Issue 2 and status]

## Progress
- [Completed item 1]
- [Completed item 2]

## Reflections
[Insights, learnings, things that went well or could be improved]

## Next Day Ideas
- [Action item 1]
- [Action item 2]
- [Context to carry forward]

---
*Processed N memories*
```

## Important Notes

- Be thorough but concise - aim for ~500-800 words total
- Preserve important details like commit hashes, file paths, metrics
- Highlight pending items that need follow-up
- Include any scheduled reminders or future tasks
- This summary will be the FIRST thing read in the next session, so make it count