from __future__ import annotations

import unittest
from datetime import datetime

from agent import Event, FamilyConflictResolutionAgent


def dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


class FamilyConflictResolutionAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = FamilyConflictResolutionAgent(memory_path=None)

    def test_different_owners_can_overlap(self) -> None:
        schedule = [
            Event(
                event_id="mom-work",
                title="Mom Work Meeting",
                owner="mom",
                start=dt("2026-03-20 15:00"),
                end=dt("2026-03-20 16:00"),
                location="Office",
            )
        ]
        incoming = Event(
            event_id="kid-art",
            title="Kid Art Class",
            owner="kid",
            start=dt("2026-03-20 15:00"),
            end=dt("2026-03-20 16:00"),
            location="School",
        )

        resolution = self.agent.resolve(incoming, schedule)

        self.assertEqual(resolution.status, "resolved")
        self.assertEqual(len(resolution.actions), 1)
        self.assertEqual(resolution.actions[0]["action"], "add_event")

    def test_driver_dependency_blocks_when_all_candidates_busy(self) -> None:
        schedule = [
            Event(
                event_id="mom-work",
                title="Mom Work Meeting",
                owner="mom",
                start=dt("2026-03-20 15:00"),
                end=dt("2026-03-20 16:00"),
                location="Office",
            ),
            Event(
                event_id="dad-call",
                title="Dad Client Call",
                owner="dad",
                start=dt("2026-03-20 15:00"),
                end=dt("2026-03-20 16:00"),
                location="Home",
            ),
        ]
        incoming = Event(
            event_id="kid-tel-aviv-meeting",
            title="Kid Meeting in Tel Aviv",
            owner="kid",
            start=dt("2026-03-20 15:15"),
            end=dt("2026-03-20 16:00"),
            location="Tel Aviv",
            required_drivers=1,
            driver_candidates=("mom", "dad"),
        )

        resolution = self.agent.resolve(incoming, schedule)

        self.assertEqual(resolution.status, "needs_input")
        self.assertFalse(resolution.actions)
        self.assertTrue(resolution.questions)

    def test_driver_dependency_allows_when_one_candidate_free(self) -> None:
        schedule = [
            Event(
                event_id="mom-work",
                title="Mom Work Meeting",
                owner="mom",
                start=dt("2026-03-20 15:00"),
                end=dt("2026-03-20 16:00"),
                location="Office",
            )
        ]
        incoming = Event(
            event_id="kid-tel-aviv-meeting",
            title="Kid Meeting in Tel Aviv",
            owner="kid",
            start=dt("2026-03-20 15:15"),
            end=dt("2026-03-20 16:00"),
            location="Tel Aviv",
            required_drivers=1,
            driver_candidates=("mom", "dad"),
        )

        resolution = self.agent.resolve(incoming, schedule)

        self.assertEqual(resolution.status, "resolved")
        self.assertEqual(len(resolution.actions), 1)
        self.assertEqual(resolution.actions[0]["action"], "add_event")


if __name__ == "__main__":
    unittest.main()
