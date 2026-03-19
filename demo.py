from __future__ import annotations

import json
from datetime import datetime

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


if __name__ == "__main__":
    main()
