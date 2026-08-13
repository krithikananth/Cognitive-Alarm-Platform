"""
AI provider abstraction for cognitive challenge generation.

The alarm flow must never depend on a third-party service being reachable, so
this module only *offers* AI generation:

- ``get_challenge_provider()`` returns a provider when one is configured and
  healthy, otherwise ``None`` — callers then use the deterministic procedural
  generators in :mod:`app.services.challenge_service`.
- Provider failures trip a short cooldown so a broken key or an outage cannot
  add latency to every ringing alarm.

Only Google Gemini is implemented today; no ML model is trained or bundled in
this repository.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from app.models.alarm import ChallengeType

logger = logging.getLogger(__name__)


# Types the AI provider may generate. MEMORY is excluded on purpose: its
# prompt *is* the digit sequence the user must retype, so it has a dedicated
# UI contract that free-form generation cannot satisfy.
AI_ELIGIBLE_TYPES = frozenset(
    {
        ChallengeType.MATH,
        ChallengeType.LOGIC,
        ChallengeType.PATTERN,
        ChallengeType.WORD_GAME,
        ChallengeType.RIDDLE,
        ChallengeType.QUIZ,
    }
)

# Per-type framing so a generated puzzle still matches the category the user
# (or their alarm) asked for.
_TYPE_INSTRUCTIONS: Dict[ChallengeType, str] = {
    ChallengeType.MATH: (
        "an arithmetic problem stated in digits and operators; the answer must "
        "be a single number"
    ),
    ChallengeType.LOGIC: (
        "a short deductive reasoning problem solvable in a few seconds without "
        "pen and paper"
    ),
    ChallengeType.PATTERN: (
        "a sequence-continuation puzzle: show 4-6 terms and ask what comes "
        "next; the answer must be the single next term"
    ),
    ChallengeType.WORD_GAME: (
        "a word puzzle such as an anagram, a scrambled word, or a missing "
        "letter; the answer must be a single common English word"
    ),
    ChallengeType.RIDDLE: (
        "a classic riddle with exactly one universally accepted answer"
    ),
    ChallengeType.QUIZ: (
        "a general-knowledge question with one objectively verifiable answer"
    ),
}

_DIFFICULTY_INSTRUCTIONS = {
    "beginner": "Very simple — solvable instantly by anyone half awake.",
    "easy": "Simple and straightforward.",
    "medium": "Moderately challenging.",
    "hard": "Difficult; requires deliberate thought.",
    "expert": "Extremely challenging, suitable for experts.",
}

_QUALITY_RULES = """
Critical quality rules:
- Exactly ONE objectively correct answer; no subjective or multi-answer items.
- Wording must be unambiguous; the correct option must match the question exactly.
- The other 3 options must be plausible distractors that are definitively incorrect.
- No duplicate, synonymous, partially correct, or conflicting options.
- Keep the prompt under 200 characters and suitable for a general audience.
- No offensive, violent, sexual, discriminatory, or inappropriate content.
- All facts, numbers, dates, units, and calculations must be correct.

Return a raw JSON object with NO markdown formatting, NO backticks, and no extra
text. It must have exactly these keys:
- "prompt": the question or puzzle text.
- "answer": the correct answer (string).
- "options": a list of exactly 4 strings, one of which is the exact correct answer.

Example format:
{"prompt": "What has keys but no locks?", "answer": "Piano", "options": ["Piano", "Door", "Map", "Computer"]}
""".strip()


class AIProviderError(RuntimeError):
    """Raised when an AI provider cannot produce a usable challenge."""


class AIChallengeProvider:
    """Interface every AI challenge backend must implement."""

    name = "base"
    model_name = ""

    def is_available(self) -> bool:
        """Whether this provider is configured well enough to be called."""
        raise NotImplementedError

    def generate(
        self,
        challenge_type: ChallengeType,
        difficulty: str,
        *,
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        """Return a raw challenge dict (type / prompt / answer / options).

        Implementations must raise :class:`AIProviderError` on any failure —
        callers treat that as "fall back to procedural generation".
        """
        raise NotImplementedError


def build_challenge_prompt(
    challenge_type: ChallengeType,
    difficulty: str,
    exclude_prompts: Optional[set] = None,
) -> str:
    """Build the instruction text sent to the model for one challenge."""
    type_hint = _TYPE_INSTRUCTIONS.get(
        challenge_type, "a short cognitive puzzle"
    )
    difficulty_hint = _DIFFICULTY_INSTRUCTIONS.get(
        difficulty, _DIFFICULTY_INSTRUCTIONS["medium"]
    )
    avoid = [str(p) for p in list(exclude_prompts or [])[:10] if p]
    avoid_block = ""
    if avoid:
        rendered = "\n".join(f"- {text}" for text in avoid)
        avoid_block = (
            "\nThe user has recently seen the puzzles below. Produce something "
            f"clearly different:\n{rendered}\n"
        )

    return (
        f"Generate one original cognitive wake-up puzzle of type "
        f"{challenge_type.value.upper()}: {type_hint}.\n"
        f"Difficulty: {difficulty}. {difficulty_hint}\n"
        f"It must be solvable in under a minute but demanding enough to wake "
        f"someone up.{avoid_block}\n{_QUALITY_RULES}"
    )


def parse_challenge_json(text: str) -> Dict[str, Any]:
    """Parse a model response into a challenge dict, tolerating code fences."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    try:
        data = json.loads(cleaned.strip())
    except (ValueError, TypeError) as exc:
        raise AIProviderError(f"Model returned non-JSON content: {exc}") from exc

    if not isinstance(data, dict):
        raise AIProviderError("Model response was not a JSON object")
    missing = [key for key in ("prompt", "answer", "options") if key not in data]
    if missing:
        raise AIProviderError(f"Model response missing keys: {missing}")
    if not isinstance(data["options"], list):
        raise AIProviderError("Model response options must be a list")
    return data


class GeminiChallengeProvider(AIChallengeProvider):
    """Google Gemini backed challenge generator."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-1.5-flash",
        timeout_seconds: int = 6,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = max(1, int(timeout_seconds or 1))

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        challenge_type: ChallengeType,
        difficulty: str,
        *,
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        if not self.is_available():
            raise AIProviderError("Gemini API key is not configured")

        try:
            import google.generativeai as genai
        except ImportError as exc:  # SDK not installed in this environment
            raise AIProviderError(f"google-generativeai unavailable: {exc}") from exc

        prompt = build_challenge_prompt(challenge_type, difficulty, exclude_prompts)
        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(
                prompt,
                request_options={"timeout": self.timeout_seconds},
            )
            text = response.text
        except AIProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — any SDK/network error is soft
            raise AIProviderError(f"Gemini request failed: {exc}") from exc

        data = parse_challenge_json(text)
        return {
            "type": challenge_type.value.upper(),
            "prompt": str(data["prompt"]),
            "answer": str(data["answer"]),
            "options": [str(opt) for opt in data["options"]],
        }


# ── Availability / circuit breaker ───────────────────────────────────

_cooldown_until: float = 0.0


def reset_provider_state() -> None:
    """Clear the failure cooldown (used by tests and admin tooling)."""
    global _cooldown_until
    _cooldown_until = 0.0


def note_provider_failure() -> None:
    """Trip the cooldown after a provider failure."""
    global _cooldown_until
    from app.core.config import settings

    seconds = max(0, int(getattr(settings, "AI_CHALLENGE_COOLDOWN_SECONDS", 300) or 0))
    _cooldown_until = time.monotonic() + seconds


def in_cooldown() -> bool:
    """Whether AI generation is currently suppressed after a failure."""
    return time.monotonic() < _cooldown_until


def get_challenge_provider() -> Optional[AIChallengeProvider]:
    """Return a healthy, configured AI provider, or ``None``.

    ``None`` means callers must use the deterministic procedural generators.
    """
    from app.core.config import settings

    if not getattr(settings, "AI_CHALLENGE_ENABLED", False):
        return None
    if in_cooldown():
        return None

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return None

    provider = GeminiChallengeProvider(
        api_key=api_key,
        model_name=getattr(settings, "AI_CHALLENGE_MODEL", "gemini-1.5-flash"),
        timeout_seconds=getattr(settings, "AI_CHALLENGE_TIMEOUT_SECONDS", 6),
    )
    return provider if provider.is_available() else None
