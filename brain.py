from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrainDecision:
    action: str
    choice_id: str = ""
    question: str = ""
    reason: str = ""


class ConflictResolutionBrain:
    def __init__(self) -> None:
        self.enable_llm = self._as_bool(os.getenv("FAMILY_AGENT_ENABLE_LLM_BRAIN", "0"))
        self.provider = (os.getenv("FAMILY_AGENT_BRAIN_PROVIDER", "ollama") or "ollama").lower()
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = os.getenv("FAMILY_AGENT_BRAIN_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:9b"))
        self.openai_model = os.getenv("FAMILY_AGENT_BRAIN_OPENAI_MODEL", "gpt-5-nano")
        self.system_prompt = self._load_system_prompt()

    def decide(
        self,
        *,
        candidates: list[dict[str, Any]],
        memory: dict[str, dict[str, int]],
        context: dict[str, Any] | None = None,
    ) -> BrainDecision:
        if not candidates:
            return BrainDecision(
                action="ask",
                question="No candidate options were generated. Allow larger movement window?",
                reason="no_candidates",
            )
        if len(candidates) == 1:
            return BrainDecision(
                action="select",
                choice_id=str(candidates[0].get("choice_id", "")),
                reason="single_candidate",
            )

        llm_choice = self._llm_decide(candidates=candidates, memory=memory, context=context or {})
        if llm_choice is not None:
            return llm_choice

        candidate_ids = [str(candidate.get("choice_id", "")) for candidate in candidates]
        return BrainDecision(
            action="ask",
            question=(
                "Two valid plans remain. Which should move? "
                f"(answer: preferred_move_event_id=<id>, options: {', '.join(candidate_ids)})"
            ),
            reason="ask_human_tie_break",
        )

    def _llm_decide(
        self,
        *,
        candidates: list[dict[str, Any]],
        memory: dict[str, dict[str, int]],
        context: dict[str, Any],
    ) -> BrainDecision | None:
        if not self.enable_llm:
            return None
        payload = {
            "context": context,
            "memory": memory,
            "candidates": candidates,
            "instructions": (
                "Return strict JSON only: "
                '{"action":"select|ask","choice_id":"string","question":"string","reason":"string"}'
            ),
        }
        user_prompt = json.dumps(payload, ensure_ascii=False)

        raw = self._call_ollama(user_prompt) if self.provider == "ollama" else self._call_openai(user_prompt)
        if not raw:
            return None
        parsed = self._parse_json(raw)
        if not isinstance(parsed, dict):
            return None
        action = str(parsed.get("action", "")).strip().lower()
        choice_id = str(parsed.get("choice_id", "")).strip()
        question = str(parsed.get("question", "")).strip()
        reason = str(parsed.get("reason", "")).strip()

        allowed_ids = {str(candidate.get("choice_id", "")) for candidate in candidates}
        if action == "select" and choice_id in allowed_ids:
            return BrainDecision(action="select", choice_id=choice_id, reason=reason or "llm_select")
        if action == "ask":
            return BrainDecision(
                action="ask",
                question=question or "Which option should move?",
                reason=reason or "llm_ask",
            )
        return None

    def _call_ollama(self, user_prompt: str) -> str | None:
        body = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        if "qwen3" in self.ollama_model.lower():
            body["think"] = False
        try:
            request = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return str((payload.get("message") or {}).get("content") or "").strip() or None
        except Exception:
            return None

    def _call_openai(self, user_prompt: str) -> str | None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        body = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": 1000,
        }
        try:
            request = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return str(((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip() or None
        except Exception:
            return None

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    @staticmethod
    def _as_bool(raw: str) -> bool:
        return str(raw).strip().lower() in {"1", "true", "yes", "y"}

    @staticmethod
    def _load_system_prompt() -> str:
        prompt_path = Path(__file__).with_name("SYSTEM_PROMPT.md")
        fallback = (
            "You are a scheduling conflict-resolution brain. Return strict JSON only with "
            "action select|ask, choice_id, question, reason."
        )
        if not prompt_path.exists():
            return fallback
        try:
            text = prompt_path.read_text(encoding="utf-8").strip()
        except Exception:
            return fallback
        return text or fallback
