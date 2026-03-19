from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from brain import ConflictResolutionBrain


@dataclass(frozen=True)
class Event:
    event_id: str
    title: str
    owner: str
    start: datetime
    end: datetime
    location: str
    movable: bool = False
    required_drivers: int = 0
    driver_candidates: tuple[str, ...] = ()
    required_resources: tuple[str, ...] = ()
    blocked_resources: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "owner": self.owner,
            "start": self.start.strftime("%Y-%m-%d %H:%M"),
            "end": self.end.strftime("%Y-%m-%d %H:%M"),
            "location": self.location,
            "movable": self.movable,
            "required_drivers": self.required_drivers,
            "driver_candidates": list(self.driver_candidates),
            "required_resources": list(self.required_resources),
            "blocked_resources": list(self.blocked_resources),
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
        memory_path: str | None = "agent_memory.json",
        brain: ConflictResolutionBrain | None = None,
    ) -> None:
        self.travel_minutes = travel_minutes or {}
        self.buffer_minutes = buffer_minutes
        self.max_shift_minutes = max_shift_minutes
        self.max_turns = max_turns
        self.memory_path = Path(memory_path) if memory_path else None
        self._memory = self._load_memory()
        self.brain = brain or ConflictResolutionBrain()
        self._pending_question = ""

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
                question = self._pending_question.strip()
                if not question:
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
                    "choice_id": pick.moved_event_id,
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
        self._pending_question = ""
        if len(candidates) == 1:
            return candidates[0]

        same_score = (
            len(candidates) > 1
            and candidates[0].score == candidates[1].score
        )
        if not same_score:
            return candidates[0]

        preferred = (answers.get("preferred_move_event_id") or "").strip()
        if preferred:
            for candidate in candidates:
                if candidate.moved_event_id == preferred:
                    return candidate
            return candidates[0]

        learned = self._learned_preference(candidates)
        if learned is not None:
            return learned

        brain_decision = self.brain.decide(
            candidates=[self._candidate_context(candidate) for candidate in candidates],
            memory=self._memory,
            context={"phase": "tie_break"},
        )
        if brain_decision.action == "select":
            for candidate in candidates:
                if candidate.moved_event_id == brain_decision.choice_id:
                    return candidate
        if brain_decision.action == "ask":
            self._pending_question = brain_decision.question
        return None

    @staticmethod
    def _candidate_context(candidate: Candidate) -> dict[str, object]:
        return {
            "choice_id": candidate.moved_event_id,
            "shift_minutes": candidate.score,
            "reason": candidate.reason,
            "new_start": candidate.moved_event.start.strftime("%Y-%m-%d %H:%M"),
            "new_end": candidate.moved_event.end.strftime("%Y-%m-%d %H:%M"),
        }

    def record_outcome(self, chosen_move_event_id: str, success: bool) -> None:
        choice_id = (chosen_move_event_id or "").strip()
        if not choice_id:
            return
        key = "wins" if success else "losses"
        bucket = self._memory.setdefault(key, {})
        bucket[choice_id] = int(bucket.get(choice_id, 0)) + 1
        self._save_memory()

    def _learned_preference(self, candidates: list[Candidate]) -> Candidate | None:
        wins = self._memory.get("wins", {})
        losses = self._memory.get("losses", {})
        best: Candidate | None = None
        best_score: int | None = None
        has_tie = False

        for candidate in candidates:
            choice_id = candidate.moved_event_id
            learned_score = int(wins.get(choice_id, 0)) - int(losses.get(choice_id, 0))
            if best_score is None or learned_score > best_score:
                best = candidate
                best_score = learned_score
                has_tie = False
            elif learned_score == best_score:
                has_tie = True

        if best is None or best_score is None or best_score <= 0 or has_tie:
            return None
        return best

    def _load_memory(self) -> dict[str, dict[str, int]]:
        empty: dict[str, dict[str, int]] = {"wins": {}, "losses": {}}
        if self.memory_path is None or not self.memory_path.exists():
            return empty
        try:
            data = json.loads(self.memory_path.read_text(encoding="utf-8"))
        except Exception:
            return empty
        if not isinstance(data, dict):
            return empty
        loaded: dict[str, dict[str, int]] = {"wins": {}, "losses": {}}
        for key in ("wins", "losses"):
            bucket = data.get(key, {})
            if not isinstance(bucket, dict):
                continue
            for choice_id, value in bucket.items():
                try:
                    loaded[key][str(choice_id)] = int(value)
                except Exception:
                    continue
        return loaded

    def _save_memory(self) -> None:
        if self.memory_path is None:
            return
        payload = {
            "wins": self._memory.get("wins", {}),
            "losses": self._memory.get("losses", {}),
        }
        try:
            self.memory_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            pass

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
        filtered_schedule = [
            existing
            for existing in schedule
            if existing.event_id != ignore_event_id
        ]
        return not self._blocking_events(candidate, filtered_schedule)

    def _blocking_events(self, incoming: Event, schedule: list[Event]) -> list[Event]:
        blockers: list[Event] = []
        seen_event_ids: set[str] = set()

        for event in schedule:
            if not self._events_conflict(incoming, event) and not self._resource_conflict(incoming, event):
                continue
            if event.event_id in seen_event_ids:
                continue
            seen_event_ids.add(event.event_id)
            blockers.append(event)

        for event in self._driver_blocking_events(incoming, schedule):
            if event.event_id in seen_event_ids:
                continue
            seen_event_ids.add(event.event_id)
            blockers.append(event)

        return blockers

    def _driver_blocking_events(self, target: Event, schedule: list[Event]) -> list[Event]:
        required = max(0, int(target.required_drivers))
        if required == 0 or not target.driver_candidates:
            return []

        candidates = tuple(
            person
            for person in dict.fromkeys(str(person).strip() for person in target.driver_candidates)
            if person
        )
        if not candidates:
            return []

        required = min(required, len(candidates))
        available = 0
        blocking_events: list[Event] = []
        seen_event_ids: set[str] = set()

        for person in candidates:
            person_blockers = self._person_conflicts_for_event(person, target, schedule)
            if not person_blockers:
                available += 1
                continue
            for event in person_blockers:
                if event.event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event.event_id)
                blocking_events.append(event)

        if available >= required:
            return []
        return blocking_events

    def _person_conflicts_for_event(
        self,
        person: str,
        target: Event,
        schedule: list[Event],
    ) -> list[Event]:
        conflicts: list[Event] = []
        for existing in schedule:
            if existing.owner != person:
                continue
            if self._events_conflict_for_person(target, existing):
                conflicts.append(existing)
        return conflicts

    def _events_conflict(self, a: Event, b: Event) -> bool:
        if a.owner != b.owner:
            return False
        return self._events_conflict_for_person(a, b)

    def _resource_conflict(self, a: Event, b: Event) -> bool:
        if not self._overlap(a, b):
            return False

        a_required = self._normalized_resources(a.required_resources)
        b_required = self._normalized_resources(b.required_resources)
        a_blocked = self._normalized_resources(a.blocked_resources)
        b_blocked = self._normalized_resources(b.blocked_resources)

        return bool(
            (a_required & b_required)
            or (a_required & b_blocked)
            or (b_required & a_blocked)
            or (a_blocked & b_blocked)
        )

    @staticmethod
    def _overlap(a: Event, b: Event) -> bool:
        return max(a.start, b.start) < min(a.end, b.end)

    def _travel_gap_conflict(self, a: Event, b: Event) -> bool:
        if a.owner != b.owner:
            return False

        return self._travel_gap_only_conflict(a, b)

    def _events_conflict_for_person(self, a: Event, b: Event) -> bool:
        if self._overlap(a, b):
            return True
        return self._travel_gap_only_conflict(a, b)

    def _travel_gap_only_conflict(self, a: Event, b: Event) -> bool:
        if a.end <= b.start:
            gap = int((b.start - a.end).total_seconds() // 60)
            required = self._required_gap(a.location, b.location)
            return gap < required

        if b.end <= a.start:
            gap = int((a.start - b.end).total_seconds() // 60)
            required = self._required_gap(b.location, a.location)
            return gap < required

        return False

    @staticmethod
    def _normalized_resources(resources: tuple[str, ...]) -> set[str]:
        return {
            resource
            for resource in (str(item).strip() for item in resources)
            if resource
        }

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
