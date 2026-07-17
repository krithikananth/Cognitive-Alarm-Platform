"""
Cognitive Challenge Engine.

Generates and verifies different types of cognitive challenges to wake up users.
Supports **personalized difficulty** based on user profile preferences and
**time-of-day adaptation** (easier challenges during very early hours).

Active challenge sessions are stored server-side so verification does not
trust a client-supplied expected answer or wall-clock measurement.
"""

import random
from datetime import datetime, timezone
from typing import Dict, Any, Optional, TYPE_CHECKING

from fastapi import HTTPException, status
from app.models.alarm import ChallengeType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Difficulty level ordering (lowest → highest) ──────────────────────
DIFFICULTY_LEVELS = ["beginner", "easy", "medium", "hard", "expert"]

# Concrete challenge types used for RANDOM / preference pools
SELECTABLE_CHALLENGE_TYPES = [
    ChallengeType.MATH,
    ChallengeType.LOGIC,
    ChallengeType.MEMORY,
    ChallengeType.WORD_GAME,
    ChallengeType.PATTERN,
    ChallengeType.RIDDLE,
    ChallengeType.QUIZ,
]

# Network / UI grace added on top of the published time limit (seconds)
VERIFY_TIME_GRACE_SECONDS = 5

# Recent attempts used for adaptive difficulty / type weighting
PERFORMANCE_WINDOW = 20

# Avoid repeating the same prompt across consecutive alarms / multi-step sessions
RECENT_PROMPT_WINDOW = 25

# Soft anti-repeat window for RANDOM type fairness
RECENT_TYPE_WINDOW = 7

# Max attempts when generation fails or yields a duplicate prompt
MAX_GENERATION_ATTEMPTS = 8


def _clamp_difficulty(level: str) -> str:
    """Ensure the difficulty string is a valid level, defaulting to medium."""
    level = level.lower() if level else "medium"
    return level if level in DIFFICULTY_LEVELS else "medium"


def _difficulty_index(level: str) -> int:
    """Return the 0-based index of a difficulty level."""
    try:
        return DIFFICULTY_LEVELS.index(_clamp_difficulty(level))
    except ValueError:
        return 2  # medium


def _preference_value(profile: Any) -> Optional[str]:
    """Extract a difficulty preference string from a profile-like object."""
    if profile is None:
        return None
    pref = getattr(profile, "difficulty_preference", None)
    if pref is None:
        return None
    return pref.value if hasattr(pref, "value") else str(pref)


def _option_key(text: str) -> str:
    """Case-insensitive key for comparing multiple-choice options."""
    return str(text).strip().lower()


def _prompt_key(text: str) -> str:
    """Normalized key for comparing challenge prompts (dedup)."""
    return " ".join(str(text or "").strip().lower().split())


def _adjust_for_time(base_difficulty: str, current_hour: Optional[int] = None) -> str:
    """
    Soften difficulty during early-morning hours when the user is groggiest.

    Rules:
        - 03:00–05:59 → reduce difficulty by 2 levels (very early, barely awake)
        - 06:00–06:59 → reduce difficulty by 1 level  (early morning)
        - 07:00–08:59 → keep as-is (normal wake-up window)
        - 09:00–23:59 → keep as-is
        - 00:00–02:59 → reduce difficulty by 1 level  (late night / graveyard)

    Args:
        base_difficulty: The user's configured difficulty preference.
        current_hour: Hour of the day (0-23). If None, uses current UTC hour.

    Returns:
        The adjusted difficulty level string.
    """
    if current_hour is None:
        current_hour = datetime.now(timezone.utc).hour

    idx = _difficulty_index(base_difficulty)

    if 3 <= current_hour <= 5:
        idx = max(0, idx - 2)
    elif 6 <= current_hour <= 6:
        idx = max(0, idx - 1)
    elif 0 <= current_hour <= 2:
        idx = max(0, idx - 1)
    # else: 7+ → keep as-is

    return DIFFICULTY_LEVELS[idx]


class ChallengeService:
    """Generates and verifies cognitive challenges for alarms."""

    # ── Public entry point ──────────────────────────────────────────

    @staticmethod
    def _normalize_type(challenge_type: ChallengeType) -> ChallengeType:
        """Normalize aliases (e.g. WORD → WORD_GAME)."""
        if challenge_type == ChallengeType.WORD:
            return ChallengeType.WORD_GAME
        return challenge_type

    @staticmethod
    def validate_mcq_item(
        prompt: str,
        answer: str,
        options: list,
        *,
        expected_count: int = 4,
    ) -> list[str]:
        """
        Validate a multiple-choice item has exactly one unambiguous correct answer.

        Rules:
            - Non-empty prompt and answer
            - Exactly ``expected_count`` unique options (case-insensitive)
            - Correct answer appears exactly once among the options
            - No blank / whitespace-only options

        Returns:
            Normalized options list with the canonical answer spelling preserved.

        Raises:
            ValueError: if the item is ambiguous, incomplete, or inconsistent.
        """
        prompt_text = (prompt or "").strip()
        answer_text = str(answer or "").strip()
        if not prompt_text:
            raise ValueError("Challenge prompt must be non-empty")
        if not answer_text:
            raise ValueError("Challenge answer must be non-empty")

        normalized: list[str] = []
        seen: set[str] = set()
        answer_key = _option_key(answer_text)
        answer_hits = 0

        for raw in options or []:
            text = str(raw).strip()
            if not text:
                raise ValueError("Options must not be blank")
            key = _option_key(text)
            if key in seen:
                raise ValueError(f"Duplicate option: {text}")
            seen.add(key)
            if key == answer_key:
                answer_hits += 1
                normalized.append(answer_text)
            else:
                normalized.append(text)

        if answer_hits != 1:
            raise ValueError(
                "Correct answer must appear exactly once among the options"
            )
        if len(normalized) != expected_count:
            raise ValueError(
                f"Expected exactly {expected_count} unique options, "
                f"got {len(normalized)}"
            )
        return normalized

    @staticmethod
    def _finalize_mcq(
        challenge_type: str,
        prompt: str,
        answer: str,
        options: list,
    ) -> Dict[str, Any]:
        """Shuffle validated MCQ options into a challenge payload."""
        validated = ChallengeService.validate_mcq_item(prompt, answer, options)
        shuffled = validated[:]
        random.shuffle(shuffled)
        return {
            "type": challenge_type,
            "prompt": prompt.strip(),
            "answer": str(answer).strip(),
            "options": shuffled,
        }

    @staticmethod
    def _pick_mcq_from_bank(
        pool: list,
        challenge_type: str,
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Select a bank entry that passes single-answer MCQ validation.

        Invalid curated items are skipped so ambiguous questions are never shown.
        Recently shown prompts are avoided when alternatives remain in the pool.
        """
        if not pool:
            raise ValueError(f"Empty challenge bank for {challenge_type}")

        excluded = {_prompt_key(p) for p in (exclude_prompts or set()) if p}
        order = list(range(len(pool)))
        random.shuffle(order)
        last_error: Optional[Exception] = None
        fallback: Optional[Dict[str, Any]] = None

        for idx in order:
            item = pool[idx]
            try:
                prompt = item["q"]
                result = ChallengeService._finalize_mcq(
                    challenge_type,
                    prompt,
                    item["a"],
                    item["opts"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                last_error = exc
                continue

            if _prompt_key(prompt) in excluded:
                if fallback is None:
                    fallback = result
                continue
            return result

        if fallback is not None:
            return fallback

        raise ValueError(
            f"No valid {challenge_type} challenge in bank"
            + (f": {last_error}" if last_error else "")
        )

    @staticmethod
    def _collect_recent_prompts(
        recent_logs: Optional[list] = None,
        exclude_prompts: Optional[list] = None,
    ) -> set[str]:
        """Build a set of normalized prompts to avoid repeating soon."""
        keys: set[str] = set()
        for raw in exclude_prompts or []:
            key = _prompt_key(raw)
            if key:
                keys.add(key)
        for log in list(recent_logs or [])[:RECENT_PROMPT_WINDOW]:
            prompt = getattr(log, "challenge_prompt", None)
            key = _prompt_key(prompt)
            if key:
                keys.add(key)
        return keys

    @staticmethod
    def _validate_generated_challenge(result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure a generated challenge is internally consistent before serving.

        Raises ValueError when the payload is incomplete, inconsistent, or
        unsafe for a general audience.
        """
        if not isinstance(result, dict):
            raise ValueError("Challenge payload must be a dict")

        prompt = str(result.get("prompt") or "").strip()
        answer = str(result.get("answer") or "").strip()
        challenge_type = str(result.get("type") or "").strip().upper()
        if not prompt:
            raise ValueError("Challenge prompt must be non-empty")
        if not answer:
            raise ValueError("Challenge answer must be non-empty")
        if not challenge_type:
            raise ValueError("Challenge type must be non-empty")

        # Keep prompts readable on mobile alarm UI
        if len(prompt) > 280:
            raise ValueError("Challenge prompt is too long")

        blocked = (
            "kill", "suicide", "racist", "nazi", "porn", "nude", "sex",
            "drugs", "cocaine", "heroin", "slur",
        )
        haystack = f"{prompt} {answer}".lower()
        if any(term in haystack for term in blocked):
            raise ValueError("Challenge content failed appropriateness check")

        options = result.get("options")
        if options is None:
            # Memory / free-text challenges: single exact answer, no MCQ list
            result["prompt"] = prompt
            result["answer"] = answer
            result["type"] = challenge_type
            return result

        if not isinstance(options, list):
            raise ValueError("Challenge options must be a list or null")

        validated = ChallengeService.validate_mcq_item(prompt, answer, options)
        result["prompt"] = prompt
        result["answer"] = answer
        result["type"] = challenge_type
        result["options"] = validated
        return result

    @staticmethod
    def _parse_preferred_types(preferred_types: Optional[list]) -> list[ChallengeType]:
        """Parse preferred type strings into ChallengeType enums."""
        if not preferred_types:
            return list(SELECTABLE_CHALLENGE_TYPES)

        parsed: list[ChallengeType] = []
        for raw in preferred_types:
            try:
                ct = ChallengeType(str(raw).lower().strip())
            except ValueError:
                continue
            ct = ChallengeService._normalize_type(ct)
            if ct in SELECTABLE_CHALLENGE_TYPES and ct not in parsed:
                parsed.append(ct)

        return parsed or list(SELECTABLE_CHALLENGE_TYPES)

    @staticmethod
    def select_challenge_type(
        requested: ChallengeType,
        preferred_types: Optional[list] = None,
        recent_logs: Optional[list] = None,
    ) -> ChallengeType:
        """
        Resolve which concrete challenge type to serve.

        - Fixed alarm types are honored as-is.
        - RANDOM picks fairly from the preferred pool (or all supported types),
          with a light penalty for types shown in the most recent attempts so
          the same few categories are not favored repeatedly.
        """
        requested = ChallengeService._normalize_type(requested)
        if requested != ChallengeType.RANDOM:
            return requested

        pool = ChallengeService._parse_preferred_types(preferred_types)

        # Count how recently each type appeared (newer = stronger penalty)
        recent_hits: Dict[str, int] = {ct.value: 0 for ct in pool}
        for position, log in enumerate(list(recent_logs or [])[:RECENT_TYPE_WINDOW]):
            ct = (getattr(log, "challenge_type", None) or "").lower()
            if ct in ("random", ""):
                continue
            if ct == "word" or ct.startswith("word"):
                ct = "word_game"
            if ct in recent_hits:
                # More recent appearances count more toward the penalty
                recent_hits[ct] += RECENT_TYPE_WINDOW - position

        weights = []
        for ct in pool:
            # Base weight 1.0 for every type → fair coverage of the full pool
            penalty = recent_hits.get(ct.value, 0)
            weights.append(max(0.35, 1.0 - (0.12 * penalty)))

        return random.choices(pool, weights=weights, k=1)[0]

    @staticmethod
    def resolve_baseline_difficulty(
        profile: Any = None,
        alarm_difficulty: Optional[str] = None,
    ) -> str:
        """
        Resolve the initial difficulty used by the challenge engine.

        Profile ``difficulty_preference`` is the primary baseline so adaptive
        difficulty can adjust around the user's preferred level. Falls back to
        the alarm's stored ``challenge_difficulty``, then ``medium``, so
        existing alarms and users without a profile keep working.
        """
        preferred = _preference_value(profile)
        if preferred:
            return _clamp_difficulty(preferred)
        return _clamp_difficulty(alarm_difficulty or "medium")

    @staticmethod
    def adapt_difficulty(
        base_difficulty: str,
        recent_logs: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Adjust difficulty from recent performance before time-of-day softening.

        Centers on the caller's baseline (normally the profile preference)
        and shifts at most one level up or down.

        Returns dict with keys: difficulty, adjustment (-1/0/+1), reason.
        """
        base = _clamp_difficulty(base_difficulty)
        logs = list(recent_logs or [])[:PERFORMANCE_WINDOW]

        if len(logs) < 5:
            return {
                "difficulty": base,
                "adjustment": 0,
                "reason": "Not enough recent attempts to adapt (need 5+).",
            }

        correct = sum(1 for l in logs if getattr(l, "is_correct", False))
        accuracy = correct / len(logs)
        avg_time = sum(getattr(l, "time_taken_seconds", 0) or 0 for l in logs) / len(logs)

        # Compare average solve time to medium baseline (30s) as a speed signal
        speed_ratio = avg_time / 30.0

        idx = _difficulty_index(base)
        adjustment = 0
        reason = "Performance stable — keeping preferred difficulty."

        if accuracy >= 0.85 and speed_ratio <= 0.55:
            adjustment = 1
            reason = (
                f"Strong recent form ({round(accuracy * 100)}% accuracy, "
                f"fast solves) — raising difficulty."
            )
        elif accuracy >= 0.75 and speed_ratio <= 0.4:
            adjustment = 1
            reason = (
                f"Consistently fast and accurate ({round(accuracy * 100)}%) "
                f"— raising difficulty."
            )
        elif accuracy <= 0.35:
            adjustment = -1
            reason = (
                f"Low recent accuracy ({round(accuracy * 100)}%) "
                f"— lowering difficulty."
            )
        elif accuracy <= 0.5 and speed_ratio >= 0.9:
            adjustment = -1
            reason = (
                f"Struggling on time and accuracy ({round(accuracy * 100)}%) "
                f"— lowering difficulty."
            )

        new_idx = max(0, min(len(DIFFICULTY_LEVELS) - 1, idx + adjustment))
        return {
            "difficulty": DIFFICULTY_LEVELS[new_idx],
            "adjustment": new_idx - idx,
            "reason": reason,
            "recent_accuracy": round(accuracy * 100, 1),
            "recent_avg_time": round(avg_time, 1),
            "sample_size": len(logs),
        }

    @staticmethod
    def generate_challenge(
        challenge_type: ChallengeType,
        difficulty: str = "medium",
        current_hour: Optional[int] = None,
        preferred_types: Optional[list] = None,
        recent_logs: Optional[list] = None,
        apply_adaptive_difficulty: bool = True,
        exclude_prompts: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Generate a cognitive puzzle personalized by preferences, performance,
        and time of day.

        Args:
            challenge_type: The requested category of puzzle (or RANDOM).
            difficulty: User's difficulty preference
                        (beginner / easy / medium / hard / expert).
            current_hour: Current hour (0-23) for time-of-day adjustment.
                          If None, the system clock is used.
            preferred_types: Profile preferred challenge type strings.
            recent_logs: Recent AlarmChallengeLog rows for personalization.
            apply_adaptive_difficulty: When True, shift difficulty from
                recent performance before applying time-of-day softening.
            exclude_prompts: Extra prompts to avoid (e.g. active session).

        Returns:
            A dictionary with the challenge prompt, type, correct answer,
            the effective difficulty applied, and a time_limit_seconds hint.
        """
        # 2) Performance-based adaptive difficulty
        adaptation = {"adjustment": 0, "reason": "Adaptive difficulty disabled."}
        working_difficulty = _clamp_difficulty(difficulty)
        if apply_adaptive_difficulty:
            adaptation = ChallengeService.adapt_difficulty(
                working_difficulty, recent_logs
            )
            working_difficulty = adaptation["difficulty"]

        # 3) Time-of-day softening
        effective = _adjust_for_time(working_difficulty, current_hour)

        generators = {
            ChallengeType.MATH: ChallengeService._generate_math,
            ChallengeType.LOGIC: ChallengeService._generate_logic,
            ChallengeType.PATTERN: ChallengeService._generate_pattern,
            ChallengeType.MEMORY: ChallengeService._generate_memory,
            ChallengeType.WORD_GAME: ChallengeService._generate_word_game,
            ChallengeType.RIDDLE: ChallengeService._generate_riddle,
            ChallengeType.QUIZ: ChallengeService._generate_quiz,
        }

        recent_prompt_keys = ChallengeService._collect_recent_prompts(
            recent_logs, exclude_prompts
        )
        is_random = (
            challenge_type == ChallengeType.RANDOM
            or ChallengeService._normalize_type(challenge_type)
            == ChallengeType.RANDOM
        )
        selection_reason = (
            "Fair rotation across supported challenge types"
            if is_random
            else "Alarm-configured challenge type"
        )

        last_error: Optional[Exception] = None
        for attempt in range(MAX_GENERATION_ATTEMPTS):
            try:
                # 1) Fair type selection (RANDOM → all preferred / supported types)
                resolved_type = ChallengeService.select_challenge_type(
                    challenge_type, preferred_types, recent_logs
                )

                generator = generators.get(resolved_type)
                if generator in (
                    ChallengeService._generate_logic,
                    ChallengeService._generate_riddle,
                    ChallengeService._generate_quiz,
                    ChallengeService._generate_word_game,
                ):
                    result = generator(
                        effective, exclude_prompts=recent_prompt_keys
                    )
                elif generator:
                    result = generator(effective)
                else:
                    result = ChallengeService._generate_ai_challenge(
                        resolved_type, effective
                    )

                result = ChallengeService._validate_generated_challenge(result)

                prompt_key = _prompt_key(result.get("prompt"))
                # Avoid duplicates when another distinct prompt is available
                if (
                    prompt_key
                    and prompt_key in recent_prompt_keys
                    and attempt < MAX_GENERATION_ATTEMPTS - 1
                ):
                    last_error = ValueError("Duplicate recent prompt")
                    continue

                result["difficulty"] = effective
                result["time_limit_seconds"] = ChallengeService._time_limit_for(
                    effective
                )
                result["requested_type"] = challenge_type.value
                result["selection_reason"] = selection_reason
                result["adaptive_difficulty"] = adaptation
                return result
            except Exception as exc:  # noqa: BLE001 — regenerate gracefully
                last_error = exc
                continue

        # Absolute last resort: simple math so the alarm flow never crashes
        try:
            result = ChallengeService._validate_generated_challenge(
                ChallengeService._generate_math(effective)
            )
        except Exception:
            result = {
                "type": "MATH",
                "prompt": "What is 2 + 2?",
                "answer": "4",
                "options": ["4", "3", "5", "6"],
            }
            result = ChallengeService._validate_generated_challenge(result)

        result["difficulty"] = effective
        result["time_limit_seconds"] = ChallengeService._time_limit_for(effective)
        result["requested_type"] = challenge_type.value
        result["selection_reason"] = selection_reason
        result["adaptive_difficulty"] = adaptation
        if last_error is not None:
            result["generation_note"] = (
                f"Regenerated after failure: {type(last_error).__name__}"
            )
        return result

    @staticmethod
    def analyze_completion(logs: list) -> Dict[str, Any]:
        """
        Produce deep challenge-completion analysis and actionable recommendations.
        """
        if not logs:
            return {
                "summary": {
                    "total_attempts": 0,
                    "correct_answers": 0,
                    "accuracy_percentage": 0.0,
                    "avg_response_time": 0.0,
                    "total_points_earned": 0,
                    "completion_rate": 0.0,
                    "trend": "insufficient_data",
                    "trend_label": "Not enough data yet",
                },
                "strengths": [],
                "weaknesses": [],
                "by_type": {},
                "by_difficulty": {},
                "recommendations": [
                    {
                        "priority": "high",
                        "category": "getting_started",
                        "title": "Complete a few morning challenges",
                        "detail": (
                            "Solve at least 5 challenges so we can personalize "
                            "difficulty and type selection for you."
                        ),
                    }
                ],
                "insights": [
                    "No challenge attempts logged yet — your analytics will appear after your first alarm."
                ],
            }

        total = len(logs)
        correct = sum(1 for l in logs if l.is_correct)
        accuracy = round((correct / total) * 100, 1)
        avg_time = round(
            sum(l.time_taken_seconds or 0 for l in logs) / total, 1
        )
        total_points = sum(l.points_earned or 0 for l in logs)
        completion_rate = accuracy  # correct attempts = successful completions

        # ── Per-type breakdown ──
        by_type: Dict[str, Dict[str, Any]] = {}
        for log in logs:
            ct = (log.challenge_type or "unknown").lower()
            if ct == "word":
                ct = "word_game"
            if ct not in by_type:
                by_type[ct] = {
                    "total": 0, "correct": 0, "total_time": 0, "points": 0,
                }
            by_type[ct]["total"] += 1
            by_type[ct]["correct"] += 1 if log.is_correct else 0
            by_type[ct]["total_time"] += log.time_taken_seconds or 0
            by_type[ct]["points"] += log.points_earned or 0

        for ct, stats in by_type.items():
            stats["accuracy"] = round(
                (stats["correct"] / stats["total"]) * 100, 1
            ) if stats["total"] else 0.0
            stats["avg_time"] = round(
                stats["total_time"] / stats["total"], 1
            ) if stats["total"] else 0.0
            del stats["total_time"]

        # ── Per-difficulty breakdown ──
        by_difficulty: Dict[str, Dict[str, Any]] = {}
        for log in logs:
            diff = (log.difficulty or "unknown").lower()
            if diff not in by_difficulty:
                by_difficulty[diff] = {"total": 0, "correct": 0, "total_time": 0}
            by_difficulty[diff]["total"] += 1
            by_difficulty[diff]["correct"] += 1 if log.is_correct else 0
            by_difficulty[diff]["total_time"] += log.time_taken_seconds or 0

        for diff, stats in by_difficulty.items():
            stats["accuracy"] = round(
                (stats["correct"] / stats["total"]) * 100, 1
            ) if stats["total"] else 0.0
            stats["avg_time"] = round(
                stats["total_time"] / stats["total"], 1
            ) if stats["total"] else 0.0
            del stats["total_time"]

        # ── Strengths / weaknesses (min 3 attempts) ──
        ranked = [
            (ct, s) for ct, s in by_type.items()
            if s["total"] >= 3 and ct != "random"
        ]
        ranked.sort(key=lambda x: (x[1]["accuracy"], -x[1]["avg_time"]), reverse=True)
        strengths = [
            {
                "type": ct,
                "accuracy": s["accuracy"],
                "avg_time": s["avg_time"],
                "attempts": s["total"],
                "label": f"Strong at {ct.replace('_', ' ')} "
                         f"({s['accuracy']}% accuracy)",
            }
            for ct, s in ranked[:3]
            if s["accuracy"] >= 70
        ]
        weaknesses = [
            {
                "type": ct,
                "accuracy": s["accuracy"],
                "avg_time": s["avg_time"],
                "attempts": s["total"],
                "label": f"Needs practice: {ct.replace('_', ' ')} "
                         f"({s['accuracy']}% accuracy)",
            }
            for ct, s in reversed(ranked)
            if s["accuracy"] < 60
        ][:3]

        # ── Trend: compare newest half vs oldest half of last 20 ──
        window = list(logs[:PERFORMANCE_WINDOW])
        trend = "insufficient_data"
        trend_label = "Not enough data for a trend"
        if len(window) >= 8:
            mid = len(window) // 2
            # logs are expected newest-first
            recent_half = window[:mid]
            older_half = window[mid:]
            r_acc = sum(1 for l in recent_half if l.is_correct) / len(recent_half)
            o_acc = sum(1 for l in older_half if l.is_correct) / len(older_half)
            delta = r_acc - o_acc
            if delta >= 0.1:
                trend, trend_label = "improving", "Improving — keep it up"
            elif delta <= -0.1:
                trend, trend_label = "declining", "Declining — ease difficulty or focus weak types"
            else:
                trend, trend_label = "stable", "Stable performance"

        # ── Recommendations ──
        recommendations = []
        if weaknesses:
            weak = weaknesses[0]
            recommendations.append({
                "priority": "high",
                "category": "practice_focus",
                "title": f"Focus on {weak['type'].replace('_', ' ')} challenges",
                "detail": (
                    f"Your accuracy on {weak['type'].replace('_', ' ')} is "
                    f"{weak['accuracy']}%. Prefer this type in Profile or set "
                    f"an alarm to this type for targeted practice."
                ),
            })
        if accuracy >= 85 and total >= 8:
            recommendations.append({
                "priority": "medium",
                "category": "difficulty",
                "title": "Ready for a harder difficulty",
                "detail": (
                    f"Overall accuracy is {accuracy}%. Raise your difficulty "
                    f"preference in Profile — adaptive difficulty will also "
                    f"nudge you up automatically."
                ),
            })
        elif accuracy < 45 and total >= 5:
            recommendations.append({
                "priority": "high",
                "category": "difficulty",
                "title": "Lower difficulty temporarily",
                "detail": (
                    f"Accuracy is {accuracy}%. Dropping difficulty builds "
                    f"momentum; adaptive difficulty will also ease challenges."
                ),
            })
        if avg_time > 25 and accuracy < 70:
            recommendations.append({
                "priority": "medium",
                "category": "speed",
                "title": "Practice faster recalls",
                "detail": (
                    f"Average solve time is {avg_time}s. Short memory and math "
                    f"drills help reduce morning cognitive lag."
                ),
            })
        if strengths and not any(r["category"] == "practice_focus" for r in recommendations):
            recommendations.append({
                "priority": "low",
                "category": "variety",
                "title": "Keep variety in your challenge mix",
                "detail": (
                    f"You're strong at {strengths[0]['type'].replace('_', ' ')}. "
                    f"Enable Random + preferred types so weaker skills still get practice."
                ),
            })
        if not recommendations:
            recommendations.append({
                "priority": "low",
                "category": "maintain",
                "title": "You're on track",
                "detail": (
                    "Performance looks balanced. Keep completing morning challenges "
                    "to maintain your streak and habit score."
                ),
            })

        insights = []
        insights.append(
            f"You completed {correct}/{total} challenges correctly "
            f"({accuracy}% accuracy) averaging {avg_time}s per attempt."
        )
        if strengths:
            insights.append(strengths[0]["label"] + ".")
        if weaknesses:
            insights.append(weaknesses[0]["label"] + ".")
        insights.append(f"Trend: {trend_label}.")

        # Suggested preferred types: keep strengths + boost weaknesses
        suggested_types = []
        for w in weaknesses:
            if w["type"] not in suggested_types:
                suggested_types.append(w["type"])
        for s in strengths:
            if s["type"] not in suggested_types:
                suggested_types.append(s["type"])
        for ct in SELECTABLE_CHALLENGE_TYPES:
            if ct.value not in suggested_types and len(suggested_types) < 4:
                suggested_types.append(ct.value)

        return {
            "summary": {
                "total_attempts": total,
                "correct_answers": correct,
                "accuracy_percentage": accuracy,
                "avg_response_time": avg_time,
                "total_points_earned": total_points,
                "completion_rate": completion_rate,
                "trend": trend,
                "trend_label": trend_label,
            },
            "strengths": strengths,
            "weaknesses": weaknesses,
            "by_type": by_type,
            "by_difficulty": by_difficulty,
            "recommendations": recommendations,
            "insights": insights,
            "suggested_preferred_types": suggested_types[:5],
        }

    # ── Time limit per difficulty ────────────────────────────────────

    @staticmethod
    def _time_limit_for(difficulty: str) -> int:
        """Return the recommended time limit in seconds for a difficulty."""
        limits = {
            "beginner": 60,
            "easy": 45,
            "medium": 30,
            "hard": 20,
            "expert": 15,
        }
        return limits.get(difficulty, 30)

    # ── AI-powered generation ────────────────────────────────────────

    @staticmethod
    def _generate_ai_challenge(
        challenge_type: ChallengeType, difficulty: str = "medium"
    ) -> Dict[str, Any]:
        """Generate a challenge via Google Gemini AI, with fallback."""
        from app.core.config import settings
        import json

        if not settings.GEMINI_API_KEY:
            return ChallengeService._fallback_challenge(challenge_type, difficulty)

        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)

            model = genai.GenerativeModel("gemini-1.5-flash")

            prompt = f"""
            Generate a completely original cognitive puzzle of type: {challenge_type.value}.
            Difficulty level: {difficulty}.
            {"Make it very simple and straightforward." if difficulty in ("beginner", "easy") else ""}
            {"Make it moderately challenging." if difficulty == "medium" else ""}
            {"Make it quite difficult and require deeper thinking." if difficulty == "hard" else ""}
            {"Make it extremely challenging, suitable for experts." if difficulty == "expert" else ""}
            The puzzle must be solvable but challenging enough to wake someone up.

            Critical quality rules:
            - Exactly ONE objectively correct answer; no subjective or multi-answer riddles.
            - Wording must be unambiguous; the correct option must match the question exactly.
            - The other 3 options must be plausible distractors that are definitively incorrect.
            - Do not include duplicate, synonymous, partially correct, or conflicting options.
            - Keep the prompt short (under 200 characters) and suitable for a general audience.
            - No offensive, violent, sexual, discriminatory, or inappropriate content.
            - All facts, numbers, dates, units, and calculations must be correct.

            You must return a raw JSON object with NO markdown formatting, NO backticks, and NO extra text.
            The JSON object must have exactly these keys:
            - "prompt": The question or puzzle text.
            - "answer": The correct answer (string).
            - "options": A list of exactly 4 strings. One must be the exact correct answer, and 3 must be plausible but incorrect.

            Example format:
            {{"prompt": "What has keys but no locks?", "answer": "Piano", "options": ["Piano", "Door", "Map", "Computer"]}}
            """

            response = model.generate_content(prompt)
            text = response.text.strip()

            # Clean up markdown fences
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            data = json.loads(text.strip())

            if "prompt" not in data or "answer" not in data or "options" not in data:
                raise ValueError("Missing required keys in AI response")

            finalized = ChallengeService._finalize_mcq(
                challenge_type.value.upper(),
                str(data["prompt"]),
                str(data["answer"]),
                list(data["options"]),
            )
            # Discard invalid AI content before presenting to the user
            return ChallengeService._validate_generated_challenge(finalized)

        except Exception as e:
            print(f"⚠️ AI Generation Failed: {e}. Falling back to procedural puzzle.")
            return ChallengeService._fallback_challenge(challenge_type, difficulty)

    @staticmethod
    def _fallback_challenge(
        challenge_type: ChallengeType, difficulty: str = "medium"
    ) -> Dict[str, Any]:
        """Fallback to algorithmic generation if AI fails or key is missing."""
        fallbacks = {
            ChallengeType.LOGIC: ChallengeService._generate_logic,
            ChallengeType.WORD_GAME: ChallengeService._generate_word_game,
            ChallengeType.WORD: ChallengeService._generate_word_game,
            ChallengeType.QUIZ: ChallengeService._generate_quiz,
            ChallengeType.RIDDLE: ChallengeService._generate_riddle,
            ChallengeType.PATTERN: ChallengeService._generate_pattern,
            ChallengeType.MEMORY: ChallengeService._generate_memory,
        }
        generator = fallbacks.get(challenge_type, ChallengeService._generate_math)
        return generator(difficulty)

    # ── MATH generator (difficulty-aware) ────────────────────────────

    @staticmethod
    def _generate_math(difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate a math problem scaled to the given difficulty.

        Difficulty mapping:
            beginner : single-digit addition / subtraction
            easy     : two-digit add / subtract, single-digit multiply
            medium   : 3-operand arithmetic
            hard     : parenthesized multi-step equations
            expert   : nested parentheses, larger numbers, division
        """
        difficulty = _clamp_difficulty(difficulty)

        if difficulty == "beginner":
            # Single-digit addition or subtraction
            a = random.randint(1, 9)
            b = random.randint(1, 9)
            op = random.choice(["+", "-"])
            if op == "-" and b > a:
                a, b = b, a
            equation = f"{a} {op} {b}"
            answer = str(eval(equation))

        elif difficulty == "easy":
            # Two-digit ± or single-digit ×
            ops = ["+", "-", "*"]
            op = random.choice(ops)
            if op == "*":
                a = random.randint(2, 9)
                b = random.randint(2, 9)
            else:
                a = random.randint(10, 50)
                b = random.randint(5, 25)
            if op == "-" and b > a:
                a, b = b, a
            equation = f"{a} {op} {b}"
            answer = str(eval(equation))

        elif difficulty == "medium":
            # 3-operand arithmetic
            a = random.randint(5, 30)
            b = random.randint(2, 15)
            c = random.randint(1, 10)
            ops = ["+", "-"]
            op1 = random.choice(ops)
            op2 = random.choice(ops)
            equation = f"{a} {op1} {b} {op2} {c}"
            answer = str(eval(equation))
            if int(answer) < 0:
                return ChallengeService._generate_math(difficulty)

        elif difficulty == "hard":
            # Parenthesized equation
            a = random.randint(3, 20)
            b = random.randint(2, 12)
            c = random.randint(2, 6)
            style = random.choice(["add_mul", "sub_mul", "mul_add"])
            if style == "add_mul":
                equation = f"({a} + {b}) \u00d7 {c}"
                answer = str((a + b) * c)
            elif style == "sub_mul":
                if b > a:
                    a, b = b, a
                equation = f"({a} - {b}) \u00d7 {c}"
                answer = str((a - b) * c)
            else:
                equation = f"{a} \u00d7 {b} + {c}"
                answer = str(a * b + c)

        else:  # expert
            # Nested / multi-step with larger numbers and division
            variant = random.choice(["nested", "div_combo", "quad_op"])
            if variant == "nested":
                a = random.randint(5, 25)
                b = random.randint(2, 10)
                c = random.randint(2, 8)
                d = random.randint(1, 5)
                equation = f"({a} + {b}) \u00d7 {c} - {d}"
                answer = str((a + b) * c - d)
            elif variant == "div_combo":
                # Ensure clean division
                divisor = random.randint(2, 9)
                quotient = random.randint(3, 15)
                dividend = divisor * quotient
                addend = random.randint(10, 50)
                equation = f"{dividend} \u00f7 {divisor} + {addend}"
                answer = str(quotient + addend)
            else:
                # 4-operand chain
                a = random.randint(10, 40)
                b = random.randint(2, 8)
                c = random.randint(2, 6)
                d = random.randint(1, 10)
                equation = f"{a} + {b} \u00d7 {c} - {d}"
                # Follow order of operations
                answer = str(a + b * c - d)

        return ChallengeService._finalize_mcq(
            "MATH",
            f"Solve: {equation} = ?",
            answer,
            ChallengeService._generate_options(answer),
        )

    # ── PATTERN generator (difficulty-aware, multi-category) ─────────

    @staticmethod
    def _build_pattern_options(answer: str, distractors: list) -> list[str]:
        """Build 4 unique MCQ options with exactly one correct answer."""
        answer = str(answer).strip()
        pool: list[str] = []
        seen = {_option_key(answer)}
        for item in distractors:
            text = str(item).strip()
            if not text:
                continue
            key = _option_key(text)
            if key not in seen:
                pool.append(text)
                seen.add(key)
        random.shuffle(pool)
        options = [answer] + pool[:3]
        # Prefer numeric near-misses over placeholder pads when possible
        if len(options) < 4:
            try:
                ans_val = int(answer)
                offset = 1
                while len(options) < 4 and offset < 50:
                    for candidate in (ans_val + offset, ans_val - offset):
                        text = str(candidate)
                        key = _option_key(text)
                        if key not in seen:
                            options.append(text)
                            seen.add(key)
                        if len(options) == 4:
                            break
                    offset += 1
            except ValueError:
                # Believable non-numeric pads (never generic "Option N")
                pads = [
                    "◆", "●", "▲", "■", "★", "○", "◇", "✦",
                    "A", "B", "C", "D", "X", "Y", "Z",
                    "None", "Same", "Skip",
                ]
                for pad in pads:
                    if len(options) >= 4:
                        break
                    key = _option_key(pad)
                    if key not in seen:
                        options.append(pad)
                        seen.add(key)
                filler = 1
                while len(options) < 4:
                    pad = f"?{filler}"
                    key = _option_key(pad)
                    if key not in seen:
                        options.append(pad)
                        seen.add(key)
                    filler += 1
        return ChallengeService.validate_mcq_item(
            "pattern", answer, options[:4]
        )

    @staticmethod
    def _pattern_result(seq: list, answer: Any, distractors: Optional[list] = None) -> Dict[str, Any]:
        """Assemble a PATTERN challenge payload from a sequence and answer."""
        answer_str = str(answer)
        shown = ", ".join(str(x) for x in seq)
        prompt = f"What comes next? {shown}, ...?"
        if distractors is None:
            options = ChallengeService._generate_options(answer_str)
        else:
            options = ChallengeService._build_pattern_options(answer_str, distractors)
        return ChallengeService._finalize_mcq("PATTERN", prompt, answer_str, options)

    @staticmethod
    def _generate_pattern(difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate a pattern challenge with varied visual/logical styles.

        Randomly selects among number, symbol, emoji, shape, letter, color,
        and other visual/logical pattern categories. Each category scales
        with difficulty and always has one unambiguous correct answer.
        """
        difficulty = _clamp_difficulty(difficulty)
        generators = [
            ChallengeService._pattern_numbers,
            ChallengeService._pattern_symbols,
            ChallengeService._pattern_emoji,
            ChallengeService._pattern_shapes,
            ChallengeService._pattern_letters,
            ChallengeService._pattern_colors,
            ChallengeService._pattern_visual_logic,
        ]
        return random.choice(generators)(difficulty)

    @staticmethod
    def _pattern_numbers(difficulty: str) -> Dict[str, Any]:
        """Classic numeric sequences scaled by difficulty."""
        if difficulty == "beginner":
            start = random.randint(1, 5)
            step = random.randint(1, 3)
            seq = [start + step * i for i in range(4)]
            answer = start + step * 4

        elif difficulty == "easy":
            start = random.randint(2, 15)
            step = random.randint(2, 6)
            seq = [start + step * i for i in range(4)]
            answer = start + step * 4

        elif difficulty == "medium":
            if random.choice(["geometric", "fibonacci"]) == "geometric":
                start = random.randint(2, 5)
                factor = random.choice([2, 3])
                seq = [start * (factor ** i) for i in range(4)]
                answer = start * (factor ** 4)
            else:
                a = random.randint(1, 5)
                b = random.randint(1, 5)
                seq = [a, b]
                for _ in range(2):
                    seq.append(seq[-1] + seq[-2])
                answer = seq[-1] + seq[-2]

        elif difficulty == "hard":
            if random.choice(["squares", "cubes"]) == "squares":
                start_n = random.randint(2, 7)
                seq = [(start_n + i) ** 2 for i in range(4)]
                answer = (start_n + 4) ** 2
            else:
                start_n = random.randint(1, 4)
                seq = [(start_n + i) ** 3 for i in range(4)]
                answer = (start_n + 4) ** 3

        else:  # expert — alternating +a, ×b
            start = random.randint(1, 5)
            add_val = random.randint(2, 5)
            mul_val = random.choice([2, 3])
            seq = [start]
            for i in range(4):
                if i % 2 == 0:
                    seq.append(seq[-1] + add_val)
                else:
                    seq.append(seq[-1] * mul_val)
            answer = seq[4]
            seq = seq[:4]

        return ChallengeService._pattern_result(seq, answer)

    @staticmethod
    def _cycle_pattern(items: list, length: int = 4) -> tuple[list, Any, list]:
        """Build a cycling sequence; return (shown, answer, distractors)."""
        full = [items[i % len(items)] for i in range(length + 1)]
        distractors = [x for x in items if x != full[length]]
        # Add a few extras from a rotated start so options stay plentiful
        if len(distractors) < 3:
            distractors = distractors + [items[(items.index(full[length]) + k) % len(items)]
                                        for k in range(1, 4)]
        return full[:length], full[length], distractors

    @staticmethod
    def _growing_token_pattern(token: str, start: int = 1) -> tuple[list, str, list]:
        """Growing repetition: ★, ★★, ★★★ → ★★★★."""
        seq = [token * (start + i) for i in range(4)]
        answer = token * (start + 4)
        distractors = [
            token * (start + 3),
            token * (start + 5),
            token * (start + 6),
            token * max(1, start),
            (token + "·") * (start + 2),
        ]
        return seq, answer, distractors

    @staticmethod
    def _pattern_symbols(difficulty: str) -> Dict[str, Any]:
        """Symbol sequences (stars, arrows, geometric marks)."""
        symbols = ["★", "☆", "◆", "◇", "●", "○", "▲", "■", "→", "←", "↑", "↓", "✦"]

        if difficulty == "beginner":
            pair = random.sample(symbols, 2)
            seq, answer, distractors = ChallengeService._cycle_pattern(pair)
            distractors = distractors + random.sample(
                [s for s in symbols if s not in pair], 2
            )

        elif difficulty == "easy":
            trio = random.sample(symbols, 3)
            seq, answer, distractors = ChallengeService._cycle_pattern(trio)
            distractors = distractors + random.sample(
                [s for s in symbols if s not in trio], 2
            )

        elif difficulty == "medium":
            token = random.choice(["★", "●", "▲", "◆", "✦"])
            seq, answer, distractors = ChallengeService._growing_token_pattern(token)

        elif difficulty == "hard":
            # Skip through an ordered symbol ring
            ring = ["●", "◆", "▲", "■", "★", "✦"]
            start = random.randint(0, len(ring) - 1)
            step = random.choice([2, 3])
            idxs = [(start + step * i) % len(ring) for i in range(5)]
            seq = [ring[i] for i in idxs[:4]]
            answer = ring[idxs[4]]
            distractors = [s for s in ring if s != answer] + random.sample(symbols, 3)

        else:  # expert — two interleaved symbols: A B A B … then continues
            a, b = random.sample(symbols, 2)
            # Pattern A A B A A B … groups of (2 A's then B), ask for next
            pattern = [a, a, b, a, a]
            seq = pattern[:4]
            answer = pattern[4]
            distractors = [b, a + b, b + a] + random.sample(
                [s for s in symbols if s not in (a, b)], 3
            )

        return ChallengeService._pattern_result(seq, answer, distractors)

    @staticmethod
    def _pattern_emoji(difficulty: str) -> Dict[str, Any]:
        """Emoji sequences with clear cyclic or growth rules."""
        faces = ["😀", "😎", "🥳", "😴", "🤔"]
        animals = ["🐶", "🐱", "🐭", "🐹", "🐰"]
        food = ["🍎", "🍌", "🍇", "🍓", "🍒"]
        weather = ["☀️", "⛅", "☁️", "🌧️", "⛈️"]
        pools = [faces, animals, food, weather]
        pool = random.choice(pools)

        if difficulty == "beginner":
            pair = random.sample(pool, 2)
            seq, answer, distractors = ChallengeService._cycle_pattern(pair)
            distractors = distractors + [e for e in pool if e not in pair]

        elif difficulty == "easy":
            trio = random.sample(pool, 3)
            seq, answer, distractors = ChallengeService._cycle_pattern(trio)
            distractors = distractors + [e for e in pool if e not in trio]

        elif difficulty == "medium":
            token = random.choice(pool)
            seq, answer, distractors = ChallengeService._growing_token_pattern(token)
            distractors = distractors + [e for e in pool if e != token]

        elif difficulty == "hard":
            # Walk the pool with a skip
            start = random.randint(0, len(pool) - 1)
            step = 2
            idxs = [(start + step * i) % len(pool) for i in range(5)]
            seq = [pool[i] for i in idxs[:4]]
            answer = pool[idxs[4]]
            distractors = [e for e in pool if e != answer]
            for other in pools:
                if other is not pool:
                    distractors.extend(random.sample(other, 2))
                    break

        else:  # expert — palindrome path: A B C B A
            trio = random.sample(pool, 3)
            path = [trio[0], trio[1], trio[2], trio[1], trio[0]]
            seq = path[:4]
            answer = path[4]
            extras = [e for e in faces + animals + food if e not in trio]
            distractors = [e for e in pool if e != answer] + random.sample(
                extras, min(3, len(extras))
            )

        return ChallengeService._pattern_result(seq, answer, distractors)

    @staticmethod
    def _pattern_shapes(difficulty: str) -> Dict[str, Any]:
        """Geometric shape sequences."""
        shapes = ["△", "□", "○", "◇", "☆", "⬠", "⬡"]
        filled = ["▲", "■", "●", "◆", "★"]

        if difficulty == "beginner":
            pair = random.sample(shapes, 2)
            seq, answer, distractors = ChallengeService._cycle_pattern(pair)
            distractors = distractors + [s for s in shapes if s not in pair]

        elif difficulty == "easy":
            trio = random.sample(shapes, 3)
            seq, answer, distractors = ChallengeService._cycle_pattern(trio)
            distractors = distractors + [s for s in shapes + filled if s not in trio]

        elif difficulty == "medium":
            # Outline → filled pairs cycling: △ ▲ □ ■ …
            pairs = list(zip(["△", "□", "○", "◇"], ["▲", "■", "●", "◆"]))
            chosen = random.sample(pairs, 2)
            stream = []
            for outline, solid in chosen:
                stream.extend([outline, solid])
            # Extend by repeating the pair stream
            stream = stream + stream
            seq = stream[:4]
            answer = stream[4]
            distractors = [p[0] for p in pairs] + [p[1] for p in pairs] + shapes

        elif difficulty == "hard":
            token = random.choice(["△", "□", "○", "◇"])
            seq, answer, distractors = ChallengeService._growing_token_pattern(token)
            distractors = distractors + shapes + filled

        else:  # expert — skip through shape ring
            ring = shapes[:]
            start = random.randint(0, len(ring) - 1)
            step = random.choice([2, 3])
            idxs = [(start + step * i) % len(ring) for i in range(5)]
            seq = [ring[i] for i in idxs[:4]]
            answer = ring[idxs[4]]
            distractors = [s for s in ring + filled if s != answer]

        return ChallengeService._pattern_result(seq, answer, distractors)

    @staticmethod
    def _pattern_letters(difficulty: str) -> Dict[str, Any]:
        """Alphabetic letter sequences."""
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        def letter_distractors(correct: str, step: int = 1) -> list:
            idx = alphabet.index(correct)
            candidates = []
            for offset in (-3, -2, -1, 1, 2, 3, step, -step, step + 1):
                candidates.append(alphabet[(idx + offset) % 26])
            # Also sprinkle random letters
            candidates.extend(random.sample(list(alphabet), 4))
            return candidates

        if difficulty == "beginner":
            start = random.randint(0, 21)
            seq = [alphabet[start + i] for i in range(4)]
            answer = alphabet[start + 4]
            distractors = letter_distractors(answer)

        elif difficulty == "easy":
            if random.choice(["forward_skip", "reverse"]) == "forward_skip":
                start = random.randint(0, 16)
                step = 2
                seq = [alphabet[start + step * i] for i in range(4)]
                answer = alphabet[start + step * 4]
            else:
                start = random.randint(4, 25)
                seq = [alphabet[start - i] for i in range(4)]
                answer = alphabet[start - 4]
            distractors = letter_distractors(answer, step=2)

        elif difficulty == "medium":
            step = random.choice([2, 3])
            max_start = 25 - step * 4
            start = random.randint(0, max_start)
            seq = [alphabet[start + step * i] for i in range(4)]
            answer = alphabet[start + step * 4]
            distractors = letter_distractors(answer, step=step)

        elif difficulty == "hard":
            # Triangular steps: +2, +3, +4, +5
            start = random.randint(0, 10)
            seq = [alphabet[start]]
            pos = start
            for delta in (2, 3, 4):
                pos += delta
                seq.append(alphabet[pos])
            answer = alphabet[pos + 5]
            distractors = letter_distractors(answer, step=5)

        else:  # expert — interleaved rising + falling: A, Z, B, Y, C
            a = random.randint(0, 10)
            b = random.randint(15, 25)
            stream = []
            for i in range(5):
                if i % 2 == 0:
                    stream.append(alphabet[a + i // 2])
                else:
                    stream.append(alphabet[b - i // 2])
            seq = stream[:4]
            answer = stream[4]
            distractors = letter_distractors(answer) + [
                alphabet[a + 2], alphabet[b - 2], alphabet[(a + b) // 2]
            ]

        return ChallengeService._pattern_result(seq, answer, distractors)

    @staticmethod
    def _pattern_colors(difficulty: str) -> Dict[str, Any]:
        """Color-circle / color-name sequences."""
        rainbow = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣"]
        names = ["Red", "Orange", "Yellow", "Green", "Blue", "Purple"]
        use_emoji = random.choice([True, False])
        items = rainbow if use_emoji else names

        if difficulty == "beginner":
            pair = random.sample(items, 2)
            seq, answer, distractors = ChallengeService._cycle_pattern(pair)
            distractors = distractors + [c for c in items if c not in pair]

        elif difficulty == "easy":
            start = random.randint(0, len(items) - 1)
            seq = [items[(start + i) % len(items)] for i in range(4)]
            answer = items[(start + 4) % len(items)]
            distractors = [c for c in items if c != answer]

        elif difficulty == "medium":
            start = random.randint(0, len(items) - 1)
            step = 2
            seq = [items[(start + step * i) % len(items)] for i in range(4)]
            answer = items[(start + step * 4) % len(items)]
            distractors = [c for c in items if c != answer]

        elif difficulty == "hard":
            # Reverse rainbow walk
            start = random.randint(0, len(items) - 1)
            seq = [items[(start - i) % len(items)] for i in range(4)]
            answer = items[(start - 4) % len(items)]
            distractors = [c for c in items if c != answer]

        else:  # expert — two interleaved color tracks: A1 B1 A2 B2 A3
            a, b = random.sample(range(len(items)), 2)
            stream = []
            for i in range(5):
                if i % 2 == 0:
                    stream.append(items[(a + i // 2) % len(items)])
                else:
                    stream.append(items[(b + i // 2) % len(items)])
            seq = stream[:4]
            answer = stream[4]
            distractors = [c for c in items if c != answer]

        return ChallengeService._pattern_result(seq, answer, distractors)

    @staticmethod
    def _pattern_visual_logic(difficulty: str) -> Dict[str, Any]:
        """Other visual/logical patterns: arrows, sizes, roman numerals, dots."""
        arrows = ["↑", "→", "↓", "←"]
        sizes = ["Tiny", "Small", "Medium", "Large", "Huge"]
        romans = [
            "I", "II", "III", "IV", "V", "VI",
            "VII", "VIII", "IX", "X", "XI", "XII",
        ]
        dots = ["·", "··", "···", "····", "·····", "······"]

        if difficulty == "beginner":
            kind = random.choice(["arrows", "sizes", "dots"])
            if kind == "arrows":
                start = random.randint(0, 3)
                seq = [arrows[(start + i) % 4] for i in range(4)]
                answer = arrows[(start + 4) % 4]
                distractors = [a for a in arrows if a != answer]
            elif kind == "sizes":
                seq = sizes[:4]
                answer = sizes[4]
                distractors = [s for s in sizes if s != answer] + ["Micro", "Giant"]
            else:
                seq = dots[:4]
                answer = dots[4]
                distractors = dots[:]

        elif difficulty == "easy":
            kind = random.choice(["arrows_rev", "romans", "dots"])
            if kind == "arrows_rev":
                start = random.randint(0, 3)
                seq = [arrows[(start - i) % 4] for i in range(4)]
                answer = arrows[(start - 4) % 4]
                distractors = list(arrows)
            elif kind == "romans":
                start = random.randint(0, 3)
                seq = romans[start:start + 4]
                answer = romans[start + 4]
                distractors = romans[:]
            else:
                start = random.randint(0, 1)
                seq = dots[start:start + 4]
                answer = dots[start + 4]
                distractors = dots[:]

        elif difficulty == "medium":
            # Compass skip: every other direction
            start = random.randint(0, 3)
            seq = [arrows[(start + 2 * i) % 4] for i in range(4)]
            answer = arrows[(start + 8) % 4]
            distractors = list(arrows) + ["↗", "↘", "↙", "↖"]

        elif difficulty == "hard":
            # Roman numerals with skip of 1
            start = random.randint(0, 2)
            seq = [romans[start + i * 2] for i in range(4)]
            answer = romans[start + 8]
            distractors = romans[:]

        else:  # expert — size words skipping one each time
            # Tiny, Medium, Huge from sizes[0], sizes[2], sizes[4] then wrap logic:
            # show Tiny, Medium, Huge, Small → Large  (odds then evens)
            odd = sizes[0::2]   # Tiny, Medium, Huge
            even = sizes[1::2]  # Small, Large
            stream = odd + even  # Tiny, Medium, Huge, Small, Large
            seq = stream[:4]
            answer = stream[4]
            distractors = sizes[:] + ["Micro", "Giant", "Normal"]

        return ChallengeService._pattern_result(seq, answer, distractors)

    # ── MEMORY generator (difficulty-aware) ──────────────────────────

    @staticmethod
    def _generate_memory(difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate a memory sequence challenge scaled to difficulty.

        Difficulty mapping:
            beginner : 3-4 digits
            easy     : 4-5 digits
            medium   : 5-6 digits
            hard     : 6-7 digits
            expert   : 8-10 digits
        """
        difficulty = _clamp_difficulty(difficulty)

        length_map = {
            "beginner": random.randint(3, 4),
            "easy": random.randint(4, 5),
            "medium": random.randint(5, 6),
            "hard": random.randint(6, 7),
            "expert": random.randint(8, 10),
        }
        length = length_map.get(difficulty, 5)
        sequence = "".join([str(random.randint(0, 9)) for _ in range(length)])

        return {
            "type": "MEMORY",
            "prompt": sequence,
            "answer": sequence,
            "options": None,  # Memory is typed input, not multiple choice
        }

    # ── RIDDLE generator (difficulty-aware) ──────────────────────────

    @staticmethod
    def _riddle_banks() -> Dict[str, list]:
        """
        Curated riddles with one universally accepted answer each.

        Distractors are plausible but definitively incorrect (no near-synonyms
        or alternate classic answers that would also fit the wording).
        """
        easy = [
            {
                "q": "What has hands but cannot clap?",
                "a": "A clock",
                "opts": ["A clock", "A book", "A wall", "A window"],
            },
            {
                "q": "What must be broken before you can use it?",
                "a": "An egg",
                "opts": ["An egg", "A spoon", "A chair", "A shoe"],
            },
            {
                "q": "What gets wetter the more it dries?",
                "a": "A towel",
                "opts": ["A towel", "Soap", "A brush", "A comb"],
            },
            {
                "q": "What has a head and a tail but no body?",
                "a": "A coin",
                "opts": ["A coin", "A person", "A snake", "A bird"],
            },
            {
                "q": "What has keys but cannot open a lock?",
                "a": "A piano",
                "opts": ["A piano", "A door", "A chest", "A safe"],
            },
            {
                "q": "What has four legs but cannot walk?",
                "a": "A table",
                "opts": ["A table", "A dog", "A cat", "A horse"],
            },
            {
                "q": "What has one eye but cannot see?",
                "a": "A needle",
                "opts": ["A needle", "A button", "A hook", "A thread"],
            },
            {
                "q": "What goes up but never comes down?",
                "a": "Your age",
                "opts": ["Your age", "A ball", "An elevator", "An airplane"],
            },
            {
                "q": "What has words but never speaks?",
                "a": "A book",
                "opts": ["A book", "A radio", "A phone", "A parrot"],
            },
            {
                "q": "What has a face and two hands but no arms or legs?",
                "a": "A clock",
                "opts": ["A clock", "A doll", "A statue", "A robot"],
            },
            {
                "q": "What runs but never walks?",
                "a": "Water",
                "opts": ["Water", "A car", "A horse", "Wind"],
            },
        ]

        medium = [
            {
                "q": "I have cities but no houses, and mountains but no trees. What am I?",
                "a": "A map",
                "opts": ["A map", "A novel", "A movie", "A song"],
            },
            {
                "q": "What can you catch but not throw?",
                "a": "A cold",
                "opts": ["A cold", "A ball", "A frisbee", "A rock"],
            },
            {
                "q": "What can travel around the world while staying in a corner?",
                "a": "A stamp",
                "opts": ["A stamp", "An airplane", "A suitcase", "A tourist"],
            },
            {
                "q": "What has a neck but no head?",
                "a": "A bottle",
                "opts": ["A bottle", "A cup", "A bowl", "A plate"],
            },
            {
                "q": "What has a bed but never sleeps?",
                "a": "A river",
                "opts": ["A river", "A hotel", "A tent", "A pillow"],
            },
            {
                "q": "What is full of holes but still holds water?",
                "a": "A sponge",
                "opts": ["A sponge", "A net", "A fence", "A screen"],
            },
            {
                "q": "I am not alive, but I grow; I have no lungs, but I need air. What am I?",
                "a": "Fire",
                "opts": ["Fire", "A rock", "Metal", "Plastic"],
            },
            {
                "q": "What common invention lets you look through a wall?",
                "a": "A window",
                "opts": ["A window", "A door", "A curtain", "A roof"],
            },
            {
                "q": "What has teeth but never bites?",
                "a": "A comb",
                "opts": ["A comb", "A brush", "Soap", "A mirror"],
            },
            {
                "q": "What kind of room has no doors or windows?",
                "a": "A mushroom",
                "opts": ["A mushroom", "A cellar", "A cave", "A vault"],
            },
        ]

        hard = [
            {
                "q": "What comes once in a minute, twice in a moment, but never in a thousand years?",
                "a": "The letter M",
                "opts": ["The letter M", "A second", "An hour", "A day"],
            },
            {
                "q": "What has four legs in the morning, two at noon, and three in the evening?",
                "a": "A human",
                "opts": ["A human", "A dog", "A cat", "A chair"],
            },
            {
                "q": "What begins with T, ends with T, and has T in it?",
                "a": "A teapot",
                "opts": ["A teapot", "Toast", "A tent", "Trust"],
            },
            {
                "q": "What word is spelled incorrectly in every dictionary?",
                "a": "Incorrectly",
                "opts": ["Incorrectly", "Dictionary", "Spelling", "Error"],
            },
            {
                "q": "What can you hold in your left hand but not in your right hand?",
                "a": "Your right elbow",
                "opts": ["Your right elbow", "Your left hand", "Your heart", "Your breath"],
            },
            {
                "q": "What is always ahead of you but can never be seen?",
                "a": "The future",
                "opts": ["The future", "An echo", "A dream", "A wish"],
            },
            {
                "q": "I have branches, but no fruit, trunk, or leaves. What am I?",
                "a": "A bank",
                "opts": ["A bank", "A tree", "A river", "A family"],
            },
            {
                "q": "The more you take of them, the more you leave behind. What are they?",
                "a": "Footsteps",
                "opts": ["Footsteps", "Coins", "Words", "Shadows"],
            },
            {
                "q": "What building has the most stories?",
                "a": "A library",
                "opts": ["A library", "A skyscraper", "A hotel", "A school"],
            },
            {
                "q": "I fly without wings and cry without eyes. Whenever I go, darkness flies. What am I?",
                "a": "A cloud",
                "opts": ["A cloud", "An airplane", "A bird", "A kite"],
            },
            {
                "q": "What has 13 hearts but no other organs?",
                "a": "A deck of cards",
                "opts": ["A deck of cards", "A calendar", "A clock", "A tree"],
            },
            {
                "q": "Forward I am heavy, but backward I am not. What am I?",
                "a": "A ton",
                "opts": ["A ton", "A pound", "Lead", "Stone"],
            },
        ]

        return {"easy": easy, "medium": medium, "hard": hard}

    @staticmethod
    def _generate_riddle(
        difficulty: str = "medium",
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Generate a riddle scaled to difficulty.

        Only curated riddles with one clear, universally accepted answer are used.
        Each item is validated so distractors cannot also be correct.
        """
        difficulty = _clamp_difficulty(difficulty)
        banks = ChallengeService._riddle_banks()

        if difficulty in ("beginner", "easy"):
            pool = banks["easy"]
        elif difficulty == "medium":
            pool = banks["easy"] + banks["medium"]
        elif difficulty == "hard":
            pool = banks["medium"] + banks["hard"]
        else:  # expert
            pool = banks["hard"]

        return ChallengeService._pick_mcq_from_bank(
            pool, "RIDDLE", exclude_prompts=exclude_prompts
        )

    # ── LOGIC generator (difficulty-aware) ───────────────────────────

    @staticmethod
    def _logic_banks() -> Dict[str, list]:
        """Curated logic items with one objectively correct answer each."""
        easy = [
            {
                "q": "Which number does not belong with the even numbers? 2, 4, 6, 9, 8",
                "a": "9",
                "opts": ["9", "2", "6", "8"],
            },
            {
                "q": "If all roses are flowers, which statement must be true?",
                "a": "All roses are flowers",
                "opts": [
                    "All roses are flowers",
                    "All flowers are roses",
                    "No roses are flowers",
                    "Some flowers are not plants",
                ],
            },
            {
                "q": "Complete the analogy: Cat is to Kitten as Dog is to ?",
                "a": "Puppy",
                "opts": ["Puppy", "Cub", "Foal", "Calf"],
            },
            {
                "q": "Which word does not belong? Apple, Banana, Carrot, Mango",
                "a": "Carrot",
                "opts": ["Carrot", "Apple", "Banana", "Mango"],
            },
            {
                "q": "If today is Wednesday, what day will it be in 4 days?",
                "a": "Sunday",
                "opts": ["Sunday", "Saturday", "Monday", "Friday"],
            },
            {
                "q": "A is taller than B. B is taller than C. Who is shortest?",
                "a": "C",
                "opts": ["C", "A", "B", "Cannot tell"],
            },
            {
                "q": "Which number comes next? 5, 10, 15, 20, ?",
                "a": "25",
                "opts": ["25", "22", "30", "24"],
            },
            {
                "q": "If the statement 'all birds can fly' is false, which could still be true?",
                "a": "Some birds can fly",
                "opts": [
                    "Some birds can fly",
                    "No birds can fly",
                    "All birds can fly",
                    "Birds are not animals",
                ],
            },
        ]

        medium = [
            {
                "q": "All A are B. Some B are C. Which statement is correct?",
                "a": "We cannot be sure whether any A are C",
                "opts": [
                    "We cannot be sure whether any A are C",
                    "All A are C",
                    "No A are C",
                    "All C are A",
                ],
            },
            {
                "q": "Find the odd one out: Square, Circle, Triangle, Cube",
                "a": "Cube",
                "opts": ["Cube", "Square", "Circle", "Triangle"],
            },
            {
                "q": "If each pen costs $2, how many pens can you buy for exactly $20?",
                "a": "10",
                "opts": ["10", "9", "12", "8"],
            },
            {
                "q": "Book is to Reading as Fork is to ?",
                "a": "Eating",
                "opts": ["Eating", "Cooking", "Spoon", "Kitchen"],
            },
            {
                "q": "Which letter comes next in the series? A, C, F, J, ?",
                "a": "O",
                "opts": ["O", "N", "M", "P"],
            },
            {
                "q": "Tom is older than Sue. Sue is older than Mia. Who is the youngest?",
                "a": "Mia",
                "opts": ["Mia", "Sue", "Tom", "Cannot tell"],
            },
            {
                "q": "Exactly one statement is true: "
                     "(1) The answer is 12  (2) The answer is 15  "
                     "(3) The answer is not 12. What is the answer?",
                "a": "12",
                "opts": ["12", "15", "Neither", "Both 12 and 15"],
            },
        ]

        hard = [
            {
                "q": "In a race, Amy finished before Ben. Ben finished before "
                     "Cara. Dana finished after Cara. Who finished last?",
                "a": "Dana",
                "opts": ["Dana", "Cara", "Ben", "Amy"],
            },
            {
                "q": "If no heroes are cowards and some soldiers are cowards, "
                     "which must be true?",
                "a": "Some soldiers are not heroes",
                "opts": [
                    "Some soldiers are not heroes",
                    "All soldiers are heroes",
                    "No soldiers are heroes",
                    "All heroes are soldiers",
                ],
            },
            {
                "q": "Which number completes the series? 2, 6, 12, 20, 30, ?",
                "a": "42",
                "opts": ["42", "40", "36", "48"],
            },
            {
                "q": "Five seats in a row: Cara sits at the right end. "
                     "Ava is not at either end. Ben sits immediately left of Ava. "
                     "Who cannot sit at the left end?",
                "a": "Ava",
                "opts": ["Ava", "Ben", "Dan", "Eve"],
            },
            {
                "q": "If RED = 27 and BLUE = 37, what is GREEN equal to? "
                     "(A=1 … Z=26, sum of letter values)",
                "a": "49",
                "opts": ["49", "47", "52", "44"],
            },
            {
                "q": "A clock shows 3:15. What is the angle between the hour "
                     "and minute hands?",
                "a": "7.5°",
                "opts": ["7.5°", "0°", "15°", "30°"],
            },
        ]

        expert = [
            {
                "q": "Exactly one of these is true: "
                     "(A) The answer is 8  (B) The answer is 11  "
                     "(C) The answer is not 8  (D) The answer is 14. "
                     "What is the answer?",
                "a": "8",
                "opts": ["8", "11", "14", "Cannot determine"],
            },
            {
                "q": "Three boxes: one has apples, one has oranges, one has both. "
                     "All labels are wrong. The box labeled 'Apples' has oranges. "
                     "What is in the box labeled 'Both'?",
                "a": "Apples",
                "opts": ["Apples", "Oranges", "Both", "Empty"],
            },
            {
                "q": "Which letter comes next? Z, X, U, Q, L, ?",
                "a": "F",
                "opts": ["F", "G", "E", "H"],
            },
            {
                "q": "If P ⇒ Q and ¬Q, what follows?",
                "a": "¬P",
                "opts": ["¬P", "P", "Q", "Nothing"],
            },
            {
                "q": "A farmer has chickens and cows. Together they have 30 heads "
                     "and 86 legs. How many chickens are there?",
                "a": "17",
                "opts": ["17", "13", "15", "20"],
            },
        ]

        return {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "expert": expert,
        }

    @staticmethod
    def _generate_logic(
        difficulty: str = "medium",
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Generate a logic puzzle scaled to difficulty.

        Variants: odd-one-out, analogies, syllogisms, and ranking puzzles.
        Every item is validated for a single unambiguous correct option.
        """
        difficulty = _clamp_difficulty(difficulty)
        banks = ChallengeService._logic_banks()

        if difficulty in ("beginner", "easy"):
            pool = banks["easy"]
        elif difficulty == "medium":
            pool = banks["easy"] + banks["medium"]
        elif difficulty == "hard":
            pool = banks["medium"] + banks["hard"]
        else:
            pool = banks["hard"] + banks["expert"]

        return ChallengeService._pick_mcq_from_bank(
            pool, "LOGIC", exclude_prompts=exclude_prompts
        )

    # ── WORD GAME generator (difficulty-aware) ───────────────────────

    @staticmethod
    def _generate_word_game(
        difficulty: str = "medium",
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Generate a word puzzle: unscramble, missing letter, or odd-word-out.
        """
        difficulty = _clamp_difficulty(difficulty)

        # (word, distractors for multiple choice)
        easy_words = [
            ("CAT", ["ACT", "TAC", "CTA"]),
            ("DOG", ["GOD", "ODG", "DGO"]),
            ("SUN", ["NUS", "USN", "NSU"]),
            ("BOOK", ["KOOB", "OBOK", "BOKO"]),
            ("TREE", ["REET", "ETER", "ERTE"]),
            ("FISH", ["HSIF", "SIHF", "IFHS"]),
            ("MOON", ["NOOM", "OMON", "ONOM"]),
            ("STAR", ["RATS", "TARS", "ARST"]),
        ]

        medium_words = [
            ("APPLE", ["PAPLE", "ALPEP", "PELPA"]),
            ("HOUSE", ["SEUOH", "HUOSE", "OSEUH"]),
            ("WATER", ["RETAW", "TAWER", "AWRET"]),
            ("LIGHT", ["THGIL", "GLITH", "LGIHT"]),
            ("MUSIC", ["CISUM", "MUISC", "SICUM"]),
            ("BRAIN", ["NIARB", "RABIN", "AIRBN"]),
            ("CLOCK", ["KCOLC", "COLCK", "LCOKC"]),
            ("PLANT", ["TNALP", "LAPTN", "NAPLT"]),
        ]

        hard_words = [
            ("PUZZLE", ["ZELPUP", "PUZZEL", "ZLPEUZ"]),
            ("ORANGE", ["EGNARO", "ORGNAE", "NAROGE"]),
            ("PLANET", ["TENALP", "PLENTA", "NEPTAL"]),
            ("GUITAR", ["RATIUG", "GIUTAR", "TARIGU"]),
            ("BRIDGE", ["EGDIRB", "BRIDEG", "DIRBGE"]),
            ("CASTLE", ["ELTASC", "CASLTE", "TLECAS"]),
            ("WINTER", ["RETNIW", "WINTRE", "TINWER"]),
            ("SILVER", ["REVILS", "SILVRE", "VILSER"]),
        ]

        expert_words = [
            ("MYSTERY", ["YRETSMY", "MYSETRY", "TERYSMY"]),
            ("JOURNEY", ["YENRUOJ", "JOURENY", "RUOJNEY"]),
            ("FREEDOM", ["MODEERF", "FREDEOM", "EDOMERF"]),
            ("CRYSTAL", ["LATSYRC", "CRYSTLA", "STYRALC"]),
            ("PHANTOM", ["MOTNAHP", "PHANTMO", "THANPOM"]),
            ("WHISPER", ["REPSIHW", "WHISPRE", "SIPREHW"]),
            ("GALAXY", ["YXALAG", "AXALGY", "GLAXAY"]),
            ("ECLIPSE", ["ESPILCE", "ECLISPE", "CLIPSEE"]),
        ]

        if difficulty in ("beginner", "easy"):
            word_pool = easy_words
            variant_weights = ["unscramble", "unscramble", "odd_out"]
        elif difficulty == "medium":
            word_pool = medium_words
            variant_weights = ["unscramble", "missing", "odd_out"]
        elif difficulty == "hard":
            word_pool = hard_words
            variant_weights = ["unscramble", "missing", "anagram_hint"]
        else:
            word_pool = expert_words
            variant_weights = ["unscramble", "anagram_hint", "missing"]

        variant = random.choice(variant_weights)

        if variant == "odd_out":
            odd_sets = [
                {
                    "q": "Which word does not belong? Blue, Red, Green, Chair",
                    "a": "Chair",
                    "opts": ["Chair", "Blue", "Red", "Green"],
                },
                {
                    "q": "Which word does not belong? Dog, Cat, Bird, Banana",
                    "a": "Banana",
                    "opts": ["Banana", "Dog", "Cat", "Bird"],
                },
                {
                    "q": "Which word does not belong? Car, Bus, Train, Shoe",
                    "a": "Shoe",
                    "opts": ["Shoe", "Car", "Bus", "Train"],
                },
                {
                    "q": "Which word does not belong? Apple, Orange, Grape, Pencil",
                    "a": "Pencil",
                    "opts": ["Pencil", "Apple", "Orange", "Grape"],
                },
                {
                    "q": "Which word does not belong? Table, Chair, Desk, Happy",
                    "a": "Happy",
                    "opts": ["Happy", "Table", "Chair", "Desk"],
                },
                {
                    "q": "Which word does not belong? Run, Jump, Walk, Cloud",
                    "a": "Cloud",
                    "opts": ["Cloud", "Run", "Jump", "Walk"],
                },
                {
                    "q": "Which word does not belong? Monday, Friday, Sunday, Winter",
                    "a": "Winter",
                    "opts": ["Winter", "Monday", "Friday", "Sunday"],
                },
            ]
            return ChallengeService._pick_mcq_from_bank(
                odd_sets, "WORD_GAME", exclude_prompts=exclude_prompts
            )

        word, distractors = random.choice(word_pool)
        scrambled = "".join(random.sample(list(word), len(word)))
        # Ensure scramble is actually different when possible
        for _ in range(10):
            if scrambled != word:
                break
            scrambled = "".join(random.sample(list(word), len(word)))

        if variant == "missing":
            idx = random.randint(0, len(word) - 1)
            blanked = word[:idx] + "_" + word[idx + 1 :]
            answer = word[idx]
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            # Prefer nearby letters as believable distractors
            ans_pos = alphabet.index(answer) if answer in alphabet else 0
            candidates = []
            for offset in (1, -1, 2, -2, 3, -3, 4, -4):
                candidates.append(alphabet[(ans_pos + offset) % len(alphabet)])
            random.shuffle(candidates)
            wrong: list[str] = []
            seen = {_option_key(answer)}
            for ch in candidates:
                if _option_key(ch) not in seen:
                    wrong.append(ch)
                    seen.add(_option_key(ch))
                if len(wrong) == 3:
                    break
            while len(wrong) < 3:
                ch = random.choice(alphabet)
                if _option_key(ch) not in seen:
                    wrong.append(ch)
                    seen.add(_option_key(ch))
            return ChallengeService._finalize_mcq(
                "WORD_GAME",
                f"Fill in the missing letter: {blanked}",
                answer,
                [answer] + wrong,
            )

        if variant == "anagram_hint":
            hint = f"(starts with {word[0]}, {len(word)} letters)"
            prompt = f"Unscramble: {scrambled} {hint}"
        else:
            prompt = f"Unscramble the word: {scrambled}"

        options = [word]
        seen = {_option_key(word)}
        for decoy in distractors:
            key = _option_key(decoy)
            if key not in seen and decoy != word:
                options.append(decoy)
                seen.add(key)
            if len(options) == 4:
                break
        # Pad with letter-swapped decoys that are not the real word
        attempts = 0
        while len(options) < 4 and attempts < 20:
            attempts += 1
            chars = list(word)
            i, j = random.sample(range(len(chars)), 2)
            chars[i], chars[j] = chars[j], chars[i]
            decoy = "".join(chars)
            key = _option_key(decoy)
            if key not in seen:
                options.append(decoy)
                seen.add(key)

        return ChallengeService._finalize_mcq("WORD_GAME", prompt, word, options)

    # ── QUIZ generator (difficulty-aware) ────────────────────────────

    @staticmethod
    def _quiz_banks() -> Dict[str, list]:
        """Curated quiz items with one factual correct answer each."""
        easy = [
            {"q": "How many days are in a week?", "a": "7", "opts": ["7", "5", "6", "8"]},
            {"q": "What color do you get by mixing red and white?", "a": "Pink", "opts": ["Pink", "Purple", "Orange", "Brown"]},
            {"q": "How many continents are commonly taught in school geography?", "a": "7", "opts": ["7", "5", "6", "8"]},
            {"q": "What is the capital of France?", "a": "Paris", "opts": ["Paris", "London", "Rome", "Berlin"]},
            {"q": "How many sides does a triangle have?", "a": "3", "opts": ["3", "4", "5", "2"]},
            {"q": "Which planet is known as the Red Planet?", "a": "Mars", "opts": ["Mars", "Venus", "Jupiter", "Mercury"]},
            {"q": "What sweet food do bees produce from nectar?", "a": "Honey", "opts": ["Honey", "Milk", "Silk", "Butter"]},
            {"q": "How many hours are in a day?", "a": "24", "opts": ["24", "12", "48", "60"]},
            {"q": "How many months are in a year?", "a": "12", "opts": ["12", "10", "11", "13"]},
            {"q": "What process do plants use to make food from sunlight?", "a": "Photosynthesis", "opts": ["Photosynthesis", "Digestion", "Respiration", "Evaporation"]},
        ]

        medium = [
            {"q": "What is the chemical formula for water?", "a": "H2O", "opts": ["H2O", "CO2", "O2", "NaCl"]},
            {"q": "Who painted the Mona Lisa?", "a": "Leonardo da Vinci", "opts": ["Leonardo da Vinci", "Michelangelo", "Picasso", "Van Gogh"]},
            {"q": "What is the largest ocean on Earth?", "a": "Pacific", "opts": ["Pacific", "Atlantic", "Indian", "Arctic"]},
            {"q": "How many bones are in the adult human body?", "a": "206", "opts": ["206", "198", "250", "180"]},
            {"q": "What gas do plants absorb from the air for photosynthesis?", "a": "Carbon dioxide", "opts": ["Carbon dioxide", "Oxygen", "Nitrogen", "Helium"]},
            {"q": "Which country is home to the kangaroo?", "a": "Australia", "opts": ["Australia", "Brazil", "India", "South Africa"]},
            {"q": "What is the positive square root of 81?", "a": "9", "opts": ["9", "8", "7", "10"]},
            {"q": "In which sport is the term 'love' used for a score of zero?", "a": "Tennis", "opts": ["Tennis", "Golf", "Soccer", "Cricket"]},
        ]

        hard = [
            {"q": "In what year did World War II end?", "a": "1945", "opts": ["1945", "1944", "1939", "1948"]},
            {"q": "What is the hardest natural substance on Earth?", "a": "Diamond", "opts": ["Diamond", "Gold", "Iron", "Quartz"]},
            {"q": "Which element has the chemical symbol Au?", "a": "Gold", "opts": ["Gold", "Silver", "Aluminum", "Argon"]},
            {"q": "What is the smallest prime number?", "a": "2", "opts": ["2", "1", "3", "0"]},
            {"q": "Who developed the theory of relativity?", "a": "Albert Einstein", "opts": ["Albert Einstein", "Newton", "Tesla", "Hawking"]},
            {"q": "What is the capital of Canada?", "a": "Ottawa", "opts": ["Ottawa", "Toronto", "Vancouver", "Montreal"]},
            {"q": "How many chambers does a human heart have?", "a": "4", "opts": ["4", "2", "3", "5"]},
            {"q": "Which planet is famous for its prominent ring system?", "a": "Saturn", "opts": ["Saturn", "Jupiter", "Uranus", "Neptune"]},
        ]

        expert = [
            {"q": "What is commonly called the powerhouse of the cell?", "a": "Mitochondria", "opts": ["Mitochondria", "Nucleus", "Ribosome", "Chloroplast"]},
            {"q": "What is the approximate speed of light in a vacuum?", "a": "300,000 km/s", "opts": ["300,000 km/s", "150,000 km/s", "30,000 km/s", "3,000 km/s"]},
            {"q": "Which mathematician invented calculus independently of Newton?", "a": "Leibniz", "opts": ["Leibniz", "Euler", "Gauss", "Pascal"]},
            {"q": "What is the chemical formula for table salt?", "a": "NaCl", "opts": ["NaCl", "KCl", "NaOH", "CaCO3"]},
            {"q": "In which year did the Titanic sink?", "a": "1912", "opts": ["1912", "1910", "1914", "1905"]},
            {"q": "What is the largest internal organ in the human body?", "a": "Liver", "opts": ["Liver", "Lungs", "Brain", "Stomach"]},
            {"q": "Which composer wrote 'The Four Seasons'?", "a": "Vivaldi", "opts": ["Vivaldi", "Bach", "Mozart", "Beethoven"]},
            {"q": "What does DNA stand for?", "a": "Deoxyribonucleic acid", "opts": ["Deoxyribonucleic acid", "Dinucleic acid", "Deoxyribose acid", "Dual nucleic acid"]},
        ]

        return {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "expert": expert,
        }

    @staticmethod
    def _generate_quiz(
        difficulty: str = "medium",
        exclude_prompts: Optional[set] = None,
    ) -> Dict[str, Any]:
        """Generate a quick general-knowledge quiz with one factual answer."""
        difficulty = _clamp_difficulty(difficulty)
        banks = ChallengeService._quiz_banks()

        if difficulty in ("beginner", "easy"):
            pool = banks["easy"]
        elif difficulty == "medium":
            pool = banks["easy"] + banks["medium"]
        elif difficulty == "hard":
            pool = banks["medium"] + banks["hard"]
        else:
            pool = banks["hard"] + banks["expert"]

        return ChallengeService._pick_mcq_from_bank(
            pool, "QUIZ", exclude_prompts=exclude_prompts
        )

    # ── Options generator ────────────────────────────────────────────

    @staticmethod
    def _generate_options(correct_answer: str) -> list[str]:
        """Generate 3 unique, incorrect numeric distractors plus the correct answer."""
        answer_text = str(correct_answer).strip()
        try:
            ans_val = int(answer_text)
        except ValueError:
            # Non-numeric answers need an explicit distractor list from the caller
            return ChallengeService.validate_mcq_item(
                "options",
                answer_text,
                [answer_text, f"{answer_text}?", f"Not {answer_text}", "None"],
            )

        options = {ans_val}
        # Prefer small near-miss offsets so distractors look believable
        preferred_offsets = [-3, -2, -1, 1, 2, 3, -4, 4, -5, 5, -6, 6, -8, 8, -10, 10]
        random.shuffle(preferred_offsets)
        for offset in preferred_offsets:
            options.add(ans_val + offset)
            if len(options) >= 4:
                break
        guard = 0
        while len(options) < 4 and guard < 40:
            guard += 1
            offset = random.randint(-12, 12)
            if offset != 0:
                options.add(ans_val + offset)

        opts = [str(x) for x in options]
        # Keep correct answer + 3 distractors only
        distractors = [o for o in opts if o != answer_text][:3]
        return ChallengeService.validate_mcq_item(
            "options", answer_text, [answer_text] + distractors
        )

    # ── Active challenge sessions (DB-backed) ─────────────────────────

    @staticmethod
    def _session_to_dict(row) -> Dict[str, Any]:
        """Serialize a ChallengeSession ORM row to a plain dict."""
        issued_at = row.issued_at
        if issued_at is not None and issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        started = getattr(row, "session_started_at", None) or issued_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return {
            "answer": row.answer,
            "prompt": row.prompt or "",
            "challenge_type": (getattr(row, "challenge_type", None) or "math").lower(),
            "difficulty": row.difficulty or "medium",
            "time_limit_seconds": int(row.time_limit_seconds or 30),
            "issued_at": issued_at,
            "consecutive_correct": int(getattr(row, "consecutive_correct", 0) or 0),
            "required_correct": int(getattr(row, "required_correct", 1) or 1),
            "total_failed_attempts": int(
                getattr(row, "total_failed_attempts", 0) or 0
            ),
            "escalation_level": int(getattr(row, "escalation_level", 0) or 0),
            "verification_token": getattr(row, "verification_token", None),
            "wake_confirmed": bool(getattr(row, "wake_confirmed", False)),
            "session_started_at": started,
        }

    @staticmethod
    def store_challenge_session(
        user_id: int,
        alarm_id: int,
        challenge: Dict[str, Any],
        db: "Session",
        *,
        required_correct: Optional[int] = None,
        escalation_level: Optional[int] = None,
        reset_progress: bool = False,
    ) -> Dict[str, Any]:
        """Persist the issued challenge so verify can trust server state.

        Preserves consecutive-correct progress across puzzle refreshes unless
        ``reset_progress`` is True (e.g. new ring cycle after snooze).
        """
        from app.models.challenge_session import ChallengeSession

        row = (
            db.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == user_id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        issued_at = datetime.now(timezone.utc)
        puzzle = {
            "answer": str(challenge.get("answer", "")),
            "prompt": challenge.get("prompt") or "",
            "challenge_type": str(
                challenge.get("type") or challenge.get("challenge_type") or "math"
            ).lower(),
            "difficulty": challenge.get("difficulty") or "medium",
            "time_limit_seconds": int(challenge.get("time_limit_seconds") or 30),
            "issued_at": issued_at,
            # New puzzle invalidates any prior dismiss token
            "verification_token": None,
            "wake_confirmed": False,
        }
        if row:
            for key, value in puzzle.items():
                setattr(row, key, value)
            if required_correct is not None:
                row.required_correct = max(1, int(required_correct))
            if escalation_level is not None:
                row.escalation_level = max(0, int(escalation_level))
            if reset_progress:
                row.consecutive_correct = 0
                row.total_failed_attempts = 0
                row.session_started_at = issued_at
        else:
            db.add(
                ChallengeSession(
                    user_id=user_id,
                    alarm_id=alarm_id,
                    consecutive_correct=0,
                    required_correct=max(1, int(required_correct or 1)),
                    total_failed_attempts=0,
                    escalation_level=max(0, int(escalation_level or 0)),
                    session_started_at=issued_at,
                    **puzzle,
                )
            )
        db.commit()
        row = (
            db.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == user_id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        return ChallengeService._session_to_dict(row)

    @staticmethod
    def get_challenge_session(
        user_id: int, alarm_id: int, db: "Session"
    ) -> Optional[Dict[str, Any]]:
        """Return the active challenge session, if any."""
        from app.models.challenge_session import ChallengeSession

        row = (
            db.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == user_id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        if not row:
            return None
        return ChallengeService._session_to_dict(row)

    @staticmethod
    def clear_puzzle_fields(user_id: int, alarm_id: int, db: "Session") -> None:
        """Invalidate the active puzzle answer while keeping verification progress."""
        from app.models.challenge_session import ChallengeSession

        row = (
            db.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == user_id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        if not row:
            return
        row.answer = ""
        row.prompt = ""
        row.issued_at = datetime.now(timezone.utc)
        db.commit()

    @staticmethod
    def record_correct_step(
        user_id: int, alarm_id: int, db: "Session"
    ) -> Dict[str, Any]:
        """Increment consecutive-correct progress after a verified correct answer."""
        from app.models.challenge_session import ChallengeSession
        import secrets

        row = (
            db.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == user_id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active challenge session.",
            )
        row.consecutive_correct = int(row.consecutive_correct or 0) + 1
        # Consume puzzle so it cannot be replayed
        row.answer = ""
        row.prompt = ""
        required = max(1, int(row.required_correct or 1))
        if row.consecutive_correct >= required:
            row.verification_token = secrets.token_urlsafe(24)
            row.wake_confirmed = True
        db.commit()
        return ChallengeService._session_to_dict(row)

    @staticmethod
    def record_failed_attempt(
        user_id: int, alarm_id: int, db: "Session", *, reset_streak: bool = True
    ) -> Dict[str, Any]:
        """Record a wrong/timeout attempt and reset consecutive streak."""
        from app.models.challenge_session import ChallengeSession

        row = (
            db.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == user_id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        if not row:
            return {
                "consecutive_correct": 0,
                "required_correct": 1,
                "total_failed_attempts": 1,
            }
        row.total_failed_attempts = int(row.total_failed_attempts or 0) + 1
        if reset_streak:
            row.consecutive_correct = 0
        row.answer = ""
        row.prompt = ""
        row.verification_token = None
        row.wake_confirmed = False
        db.commit()
        return ChallengeService._session_to_dict(row)

    @staticmethod
    def clear_challenge_session(
        user_id: int, alarm_id: int, db: "Session"
    ) -> None:
        """Drop the active challenge session for this alarm."""
        from app.models.challenge_session import ChallengeSession

        db.query(ChallengeSession).filter(
            ChallengeSession.user_id == user_id,
            ChallengeSession.alarm_id == alarm_id,
        ).delete()
        db.commit()

    @staticmethod
    def escalate_difficulty(base_difficulty: str, escalation_level: int) -> str:
        """Raise difficulty by one level per snooze (capped at expert)."""
        idx = _difficulty_index(base_difficulty)
        idx = min(len(DIFFICULTY_LEVELS) - 1, idx + max(0, int(escalation_level or 0)))
        return DIFFICULTY_LEVELS[idx]

    @staticmethod
    def assess_wakefulness(
        *,
        consecutive_correct: int,
        required_correct: int,
        failed_attempts: int,
        time_taken_seconds: int,
        time_limit_seconds: int,
        recent_accuracy: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Score cognitive wakefulness from verification performance (0–100)."""
        required = max(1, int(required_correct or 1))
        consecutive = max(0, int(consecutive_correct or 0))
        failed = max(0, int(failed_attempts or 0))
        limit = max(1, int(time_limit_seconds or 30))
        taken = max(0, int(time_taken_seconds or 0))

        completion_ratio = min(1.0, consecutive / required)
        speed_ratio = max(0.0, min(1.0, (limit - taken) / limit))
        fail_penalty = min(40.0, failed * 8.0)
        accuracy_bonus = 0.0
        if recent_accuracy is not None:
            accuracy_bonus = max(0.0, min(15.0, (float(recent_accuracy) - 50.0) * 0.3))

        score = (
            completion_ratio * 55.0
            + speed_ratio * 30.0
            + accuracy_bonus
            - fail_penalty
        )
        score = round(max(0.0, min(100.0, score)), 1)

        if score >= 80:
            level = "sharp"
        elif score >= 55:
            level = "alert"
        elif score >= 30:
            level = "groggy"
        else:
            level = "drowsy"

        return {
            "score": score,
            "level": level,
            "factors": {
                "completion_ratio": round(completion_ratio, 2),
                "speed_ratio": round(speed_ratio, 2),
                "failed_attempts": failed,
                "fail_penalty": fail_penalty,
                "accuracy_bonus": round(accuracy_bonus, 1),
            },
        }

    @staticmethod
    def public_challenge_payload(
        challenge: Dict[str, Any],
        *,
        consecutive_correct: int = 0,
        required_correct: int = 1,
        escalation_level: int = 0,
    ) -> Dict[str, Any]:
        """Return challenge data safe for clients (no answer)."""
        payload = {k: v for k, v in challenge.items() if k != "answer"}
        payload["current_step"] = int(consecutive_correct) + 1
        payload["total_steps"] = max(1, int(required_correct or 1))
        payload["consecutive_correct"] = int(consecutive_correct)
        payload["required_correct"] = max(1, int(required_correct or 1))
        payload["escalation_level"] = int(escalation_level or 0)
        payload["requires_consecutive"] = True
        return payload

    # ── Answer verification ──────────────────────────────────────────

    @staticmethod
    def verify_answer(expected_answer: str, user_answer: str) -> bool:
        """
        Verify if the user's provided answer matches the expected answer.
        Case insensitive, trims whitespace, and treats numeric values equally
        (e.g. "38" == "38.0").
        """
        if expected_answer is None or user_answer is None:
            return False
        exp = str(expected_answer).strip().lower()
        usr = str(user_answer).strip().lower()
        if not exp or not usr:
            return False
        if exp == usr:
            return True
        try:
            return float(exp) == float(usr)
        except ValueError:
            return False

    # ── Scoring engine ───────────────────────────────────────────────

    @staticmethod
    def calculate_score(
        challenge_type: str,
        difficulty: str,
        time_taken_seconds: int,
        is_correct: bool,
    ) -> dict:
        """
        Calculate points earned for a challenge attempt.

        Scoring formula:
            base_points  = type_weight × difficulty_multiplier
            time_bonus   = max(0, (time_limit - time_taken) / time_limit) × base × 0.5
            total        = base_points + time_bonus   (if correct, else 0)

        Args:
            challenge_type: e.g. "math", "riddle", "pattern", "memory"
            difficulty: beginner / easy / medium / hard / expert
            time_taken_seconds: how long the user took
            is_correct: whether the answer was right

        Returns:
            Dict with base_points, time_bonus, total_points, and breakdown.
        """
        if not is_correct:
            return {
                "base_points": 0,
                "time_bonus": 0,
                "total_points": 0,
                "is_correct": False,
                "breakdown": "Incorrect answer — no points awarded.",
            }

        # ── Per-type base weights ──
        type_weights = {
            "math": 10,
            "pattern": 15,
            "memory": 12,
            "riddle": 10,
            "logic": 18,
            "word_game": 14,
            "quiz": 10,
        }
        base = type_weights.get(challenge_type.lower(), 10)

        # ── Difficulty multiplier ──
        diff_multipliers = {
            "beginner": 1.0,
            "easy": 1.5,
            "medium": 2.0,
            "hard": 3.0,
            "expert": 5.0,
        }
        multiplier = diff_multipliers.get(difficulty.lower(), 2.0)

        base_points = round(base * multiplier)

        # ── Time bonus (faster = more points, up to +50% of base) ──
        time_limits = {
            "beginner": 60, "easy": 45, "medium": 30, "hard": 20, "expert": 15,
        }
        time_limit = time_limits.get(difficulty.lower(), 30)
        remaining_ratio = max(0, (time_limit - time_taken_seconds) / time_limit)
        time_bonus = round(base_points * 0.5 * remaining_ratio)

        total = base_points + time_bonus

        return {
            "base_points": base_points,
            "time_bonus": time_bonus,
            "total_points": total,
            "is_correct": True,
            "breakdown": (
                f"{base} (type:{challenge_type}) × {multiplier} (diff:{difficulty}) "
                f"= {base_points} base + {time_bonus} time bonus = {total} total"
            ),
        }

