# Stop Writing Prompts. Start Raising Agents.

Most automation scripts are single-pass:

1. read input
2. produce output
3. exit

That works when the path is deterministic.

Family scheduling is often not deterministic. A new event can collide with
existing plans, commute buffers, and person-specific constraints. In those
cases, the hard part is not formatting text; it is making a decision loop:

- detect conflicts
- generate alternatives
- ask a focused follow-up when ambiguity remains
- replan using the answer
- emit concrete execution actions

That is the boundary where an agent is justified.

---

## What This Demo Shows

This repository is a tiny, public showcase of that loop:

- `agent.py` implements conflict detection, candidate generation, and
  decision turns.
- `demo.py` runs a realistic scenario where two plans have equal quality.
- the first run returns `needs_input` with a specific question.
- the second run applies the answer and returns `resolved` actions.

The point is not model output quality. The point is process quality.

---

## Why This Needs an Agent

A regular script can sort events and apply fixed rules.
It cannot reliably handle ambiguous tradeoffs without human input.

This demo includes that missing behavior:

- **plan**: evaluate multiple valid repairs
- **ask**: request exactly one missing decision
- **replan**: continue from updated context

If your workflow needs this `plan -> ask -> replan` pattern, you are no
longer building a formatter. You are building an agent.
