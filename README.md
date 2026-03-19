# Family Conflict Agent (Showcase)

Tiny, generic example of an **agentic family-scheduling workflow**.

This project shows when a normal script is not enough: the system must
plan, ask a follow-up question when decisions are ambiguous, and replan.

Companion write-up: `article.md`.

## What It Demonstrates

- Detects blocking conflicts (time overlap + travel/buffer constraints).
- Generates multiple repair plans (move incoming event vs. move existing).
- Requests human input when plans are equally good.
- Re-runs with the answer and outputs executable calendar actions.

## Run

```bash
python demo.py
```

You will see:

1. First pass: `needs_input` with a concrete question.
2. Second pass: `resolved` after providing a preference.

## Files

- `agent.py` — conflict-resolution agent loop.
- `demo.py` — minimal reproducible scenario.
