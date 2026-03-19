from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent import Event, FamilyConflictResolutionAgent, Resolution


def dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def as_dict(resolution: Resolution) -> dict[str, object]:
    return {
        "status": resolution.status,
        "actions": resolution.actions,
        "questions": resolution.questions,
        "notes": resolution.notes,
    }


def main() -> None:
    memory_file = Path(".demo_memory.json")
    if memory_file.exists():
        memory_file.unlink()

    schedule = [
        Event(
            event_id="soccer-practice",
            title="Soccer Practice",
            owner="child-a",
            start=dt("2026-03-20 17:30"),
            end=dt("2026-03-20 18:30"),
            location="Field",
            movable=True,
        )
    ]
    incoming = Event(
        event_id="dentist-checkup",
        title="Dentist Checkup",
        owner="child-a",
        start=dt("2026-03-20 17:45"),
        end=dt("2026-03-20 18:15"),
        location="Clinic",
        movable=True,
    )

    agent = FamilyConflictResolutionAgent(
        travel_minutes={
            ("Field", "Clinic"): 15,
            ("Clinic", "Field"): 15,
        },
        buffer_minutes=10,
        max_shift_minutes=120,
        memory_path=str(memory_file),
    )

    first_pass = agent.resolve(incoming, schedule)
    print("First pass:")
    print(json.dumps(as_dict(first_pass), indent=2))

    if first_pass.status == "needs_input":
        second_pass = agent.resolve(
            incoming=incoming,
            schedule=schedule,
            answers={"preferred_move_event_id": "incoming"},
        )
        print("\nSecond pass (after answer):")
        print(json.dumps(as_dict(second_pass), indent=2))

        move_action = next(
            (
                action
                for action in second_pass.actions
                if action.get("action") == "move_event"
            ),
            None,
        )
        if move_action:
            agent.record_outcome(str(move_action.get("choice_id", "")), success=True)

        learned_agent = FamilyConflictResolutionAgent(
            travel_minutes={
                ("Field", "Clinic"): 15,
                ("Clinic", "Field"): 15,
            },
            buffer_minutes=10,
            max_shift_minutes=120,
            memory_path=str(memory_file),
        )
        third_pass = learned_agent.resolve(incoming, schedule)
        print("\nThird pass (same input, learned tie-break):")
        print(json.dumps(as_dict(third_pass), indent=2))


if __name__ == "__main__":
    main()
