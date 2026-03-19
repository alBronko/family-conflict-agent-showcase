from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Event:
    event_id: str
    title: str
    owner: str
    start: datetime
    end: datetime
    location: str
    movable: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "owner": self.owner,
            "start": self.start.strftime("%Y-%m-%d %H:%M"),
            "end": self.end.strftime("%Y-%m-%d %H:%M"),
            "location": self.location,
            "movable": self.movable,
        }


@dataclass(frozen=True)
class Candidate:
    moved_event_id: str
    moved_event: Event
    score: int
    reason: str


@dataclass(frozen=True)
class Resolution:
    status: str
    actions: list[dict[str, object]]
    questions: list[str]
    notes: list[str]


class FamilyConflictResolutionAgent:
    def __init__(
        self,
        travel_minutes: dict[tuple[str, str], int] | None = None,
        buffer_minutes: int = 15,
        max_shift_minutes: int = 120,
        max_turns: int = 3,
    ) -> None:
        self.travel_minutes = travel_minutes or {}
        self.buffer_minutes = buffer_minutes
        self.max_shift_minutes = max_shift_minutes
        self.max_turns = max_turns

    def resolve(
        self,
        incoming: Event,
        schedule: list[Event],
        answers: dict[str, str] | None = None,
    ) -> Resolution:
        answer_map = answers or {}
        force_fixed_moves = self._as_bool(answer_map.get("allow_fixed_moves", "false"))
        working_incoming = incoming
        working_schedule = {event.event_id: event for event in schedule}
        actions: list[dict[str, object]] = []
        notes: list[str] = []

        for turn in range(1, self.max_turns + 1):
            blockers = self._blocking_events(working_incoming, list(working_schedule.values()))
            if not blockers:
                actions.append({"action": "add_event", "event": working_incoming.as_dict()})
                notes.append("No blocking conflicts left.")
                return Resolution("resolved", actions, [], notes)

            candidates = self._build_candidates(
                incoming=working_incoming,
                schedule=list(working_schedule.values()),
                force_fixed_moves=force_fixed_moves,
            )
            if not candidates:
                if force_fixed_moves:
                    notes.append("Unable to find a legal time slot, even after forced moves.")
                    return Resolution("failed", actions, [], notes)
                question = (
                    "No movable option found. Allow moving fixed events up to "
                    f"{self.max_shift_minutes} minutes? (answer: allow_fixed_moves=yes)"
                )
                return Resolution("needs_input", actions, [question], notes)

            pick = self._pick_candidate(candidates, answer_map)
            if pick is None:
                options = ", ".join(candidate.moved_event_id for candidate in candidates[:4])
                question = (
                    "Multiple equal plans. Which event should move? "
                    f"(answer: preferred_move_event_id=<id>, options: {options})"
                )
                return Resolution("needs_input", actions, [question], notes)

            if pick.moved_event_id == "incoming":
                old_event = working_incoming
                working_incoming = pick.moved_event
            else:
                old_event = working_schedule[pick.moved_event_id]
                working_schedule[pick.moved_event_id] = pick.moved_event

            actions.append(
                {
                    "action": "move_event",
                    "event_id": old_event.event_id,
                    "from_start": old_event.start.strftime("%Y-%m-%d %H:%M"),
                    "from_end": old_event.end.strftime("%Y-%m-%d %H:%M"),
                    "to_start": pick.moved_event.start.strftime("%Y-%m-%d %H:%M"),
                    "to_end": pick.moved_event.end.strftime("%Y-%m-%d %H:%M"),
                    "reason": pick.reason,
                }
            )
            notes.append(f"Turn {turn}: moved {old_event.event_id}.")

        notes.append("Max planning turns reached without a stable schedule.")
        return Resolution("failed", actions, [], notes)

    def _pick_candidate(
        self,
        candidates: list[Candidate],
        answers: dict[str, str],
    ) -> Candidate | None:
        if len(candidates) == 1:
            return candidates[0]

        same_score = (
            len(candidates) > 1
            and candidates[0].score == candidates[1].score
        )
        if not same_score:
            return candidates[0]

        preferred = (answers.get("preferred_move_event_id") or "").strip()
        if not preferred:
            return None
        for candidate in candidates:
            if candidate.moved_event_id == preferred:
                return candidate
        return candidates[0]

    def _build_candidates(
        self,
        incoming: Event,
        schedule: list[Event],
        force_fixed_moves: bool,
    ) -> list[Candidate]:
        blockers = self._blocking_events(incoming, schedule)
        candidates: list[Candidate] = []

        moved_incoming = self._find_shifted_slot(incoming, schedule, ignore_event_id=None, force=False)
        if moved_incoming is not None:
            score = int((moved_incoming.start - incoming.start).total_seconds() // 60)
            candidates.append(
                Candidate(
                    moved_event_id="incoming",
                    moved_event=moved_incoming,
                    score=score,
                    reason="shift incoming to next legal slot",
                )
            )

        for blocker in blockers:
            moved_blocker = self._find_shifted_slot(
                blocker,
                schedule + [incoming],
                ignore_event_id=blocker.event_id,
                force=force_fixed_moves,
            )
            if moved_blocker is None:
                continue
            score = int((moved_blocker.start - blocker.start).total_seconds() // 60)
            candidates.append(
                Candidate(
                    moved_event_id=blocker.event_id,
                    moved_event=moved_blocker,
                    score=score,
                    reason=f"shift {blocker.event_id} to preserve new request",
                )
            )

        return sorted(candidates, key=lambda candidate: candidate.score)

    def _find_shifted_slot(
        self,
        event: Event,
        schedule: list[Event],
        ignore_event_id: str | None,
        force: bool,
    ) -> Event | None:
        if not event.movable and not force:
            return None
        step = 15
        for shift in range(step, self.max_shift_minutes + step, step):
            delta = timedelta(minutes=shift)
            candidate = replace(event, start=event.start + delta, end=event.end + delta)
            if self._is_slot_clear(candidate, schedule, ignore_event_id=ignore_event_id):
                return candidate
        return None

    def _is_slot_clear(
        self,
        candidate: Event,
        schedule: list[Event],
        ignore_event_id: str | None,
    ) -> bool:
        for existing in schedule:
            if existing.event_id == ignore_event_id:
                continue
            if self._events_conflict(candidate, existing):
                return False
        return True

    def _blocking_events(self, incoming: Event, schedule: list[Event]) -> list[Event]:
        return [event for event in schedule if self._events_conflict(incoming, event)]

    def _events_conflict(self, a: Event, b: Event) -> bool:
        if self._overlap(a, b):
            return True
        return self._travel_gap_conflict(a, b)

    @staticmethod
    def _overlap(a: Event, b: Event) -> bool:
        return max(a.start, b.start) < min(a.end, b.end)

    def _travel_gap_conflict(self, a: Event, b: Event) -> bool:
        if a.owner != b.owner:
            return False

        if a.end <= b.start:
            gap = int((b.start - a.end).total_seconds() // 60)
            required = self._required_gap(a.location, b.location)
            return gap < required

        if b.end <= a.start:
            gap = int((a.start - b.end).total_seconds() // 60)
            required = self._required_gap(b.location, a.location)
            return gap < required

        return False

    def _required_gap(self, origin: str, destination: str) -> int:
        if origin == destination:
            travel = 0
        else:
            travel = self._travel_lookup(origin, destination)
        return travel + self.buffer_minutes

    def _travel_lookup(self, origin: str, destination: str) -> int:
        direct = self.travel_minutes.get((origin, destination))
        if direct is not None:
            return direct
        reverse = self.travel_minutes.get((destination, origin))
        if reverse is not None:
            return reverse
        return 20

    @staticmethod
    def _as_bool(raw: str) -> bool:
        return str(raw).strip().lower() in {"1", "true", "yes", "y"}
