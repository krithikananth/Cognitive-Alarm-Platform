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
        - RANDOM (or equivalent) picks from the user's preferred types,
          weighted toward weaker types so practice stays personalized.
        """
        requested = ChallengeService._normalize_type(requested)
        if requested != ChallengeType.RANDOM:
            return requested

        pool = ChallengeService._parse_preferred_types(preferred_types)

        # Weight by weakness: lower accuracy → higher selection weight
        weights = []
        by_type: Dict[str, Dict[str, int]] = {}
        for log in recent_logs or []:
            ct = (getattr(log, "challenge_type", None) or "").lower()
            if ct in ("random", "word", ""):
                continue
            if ct == "word_game" or ct.startswith("word"):
                ct = "word_game"
            if ct not in by_type:
                by_type[ct] = {"total": 0, "correct": 0}
            by_type[ct]["total"] += 1
            if getattr(log, "is_correct", False):
                by_type[ct]["correct"] += 1

        for ct in pool:
            stats = by_type.get(ct.value, {"total": 0, "correct": 0})
            if stats["total"] < 3:
                # Unexplored preferred types get a healthy chance
                weights.append(2.5)
            else:
                accuracy = stats["correct"] / stats["total"]
                # Invert accuracy: 0% → weight 3.0, 100% → weight 0.5
                weights.append(max(0.5, 3.0 - (accuracy * 2.5)))

        return random.choices(pool, weights=weights, k=1)[0]

    @staticmethod
    def adapt_difficulty(
        base_difficulty: str,
        recent_logs: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Adjust difficulty from recent performance before time-of-day softening.

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

        Returns:
            A dictionary with the challenge prompt, type, correct answer,
            the effective difficulty applied, and a time_limit_seconds hint.
        """
        # 1) Personalized type selection (RANDOM → preferred + weak-type bias)
        resolved_type = ChallengeService.select_challenge_type(
            challenge_type, preferred_types, recent_logs
        )

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

        # Dispatch to the appropriate generator
        generators = {
            ChallengeType.MATH: ChallengeService._generate_math,
            ChallengeType.LOGIC: ChallengeService._generate_logic,
            ChallengeType.PATTERN: ChallengeService._generate_pattern,
            ChallengeType.MEMORY: ChallengeService._generate_memory,
            ChallengeType.WORD_GAME: ChallengeService._generate_word_game,
            ChallengeType.RIDDLE: ChallengeService._generate_riddle,
            ChallengeType.QUIZ: ChallengeService._generate_quiz,
        }

        generator = generators.get(resolved_type)
        if generator:
            result = generator(effective)
        else:
            result = ChallengeService._generate_ai_challenge(
                resolved_type, effective
            )

        result["difficulty"] = effective
        result["time_limit_seconds"] = ChallengeService._time_limit_for(effective)
        result["requested_type"] = challenge_type.value
        result["selection_reason"] = (
            "Preferred types + performance weighting"
            if challenge_type == ChallengeType.RANDOM
            or ChallengeService._normalize_type(challenge_type) == ChallengeType.RANDOM
            else "Alarm-configured challenge type"
        )
        result["adaptive_difficulty"] = adaptation
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

            random.shuffle(data["options"])

            return {
                "type": challenge_type.value.upper(),
                "prompt": data["prompt"],
                "answer": str(data["answer"]),
                "options": [str(o) for o in data["options"]],
            }

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

        return {
            "type": "MATH",
            "prompt": f"Solve: {equation} = ?",
            "answer": answer,
            "options": ChallengeService._generate_options(answer),
        }

    # ── PATTERN generator (difficulty-aware) ─────────────────────────

    @staticmethod
    def _generate_pattern(difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate a number sequence pattern scaled to difficulty.

        Difficulty mapping:
            beginner : simple arithmetic sequence, small numbers
            easy     : arithmetic with moderate step
            medium   : geometric or fibonacci
            hard     : squares or cubes
            expert   : mixed operations or alternating sequences
        """
        difficulty = _clamp_difficulty(difficulty)

        if difficulty == "beginner":
            start = random.randint(1, 5)
            step = random.randint(1, 3)
            seq = [start + step * i for i in range(4)]
            answer = str(start + step * 4)

        elif difficulty == "easy":
            start = random.randint(2, 15)
            step = random.randint(2, 6)
            seq = [start + step * i for i in range(4)]
            answer = str(start + step * 4)

        elif difficulty == "medium":
            pattern_type = random.choice(["geometric", "fibonacci"])
            if pattern_type == "geometric":
                start = random.randint(2, 5)
                factor = random.choice([2, 3])
                seq = [start * (factor ** i) for i in range(4)]
                answer = str(start * (factor ** 4))
            else:
                a = random.randint(1, 5)
                b = random.randint(1, 5)
                seq = [a, b]
                for _ in range(2):
                    seq.append(seq[-1] + seq[-2])
                answer = str(seq[-1] + seq[-2])

        elif difficulty == "hard":
            pattern_type = random.choice(["squares", "cubes"])
            if pattern_type == "squares":
                start_n = random.randint(2, 7)
                seq = [(start_n + i) ** 2 for i in range(4)]
                answer = str((start_n + 4) ** 2)
            else:
                start_n = random.randint(1, 4)
                seq = [(start_n + i) ** 3 for i in range(4)]
                answer = str((start_n + 4) ** 3)

        else:  # expert
            # Alternating operation: +a, ×b, +a, ×b …
            start = random.randint(1, 5)
            add_val = random.randint(2, 5)
            mul_val = random.choice([2, 3])
            seq = [start]
            for i in range(4):
                if i % 2 == 0:
                    seq.append(seq[-1] + add_val)
                else:
                    seq.append(seq[-1] * mul_val)
            # seq has 5 elements; show first 4, answer is 5th
            answer = str(seq[4])
            seq = seq[:4]

        return {
            "type": "PATTERN",
            "prompt": f"What comes next? {seq[0]}, {seq[1]}, {seq[2]}, {seq[3]}, ...?",
            "answer": answer,
            "options": ChallengeService._generate_options(answer),
        }

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
    def _generate_riddle(difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate a riddle scaled to difficulty.

        Easier riddles use common, well-known riddles.
        Harder riddles use more abstract and tricky ones.
        """
        difficulty = _clamp_difficulty(difficulty)

        # Riddles grouped by difficulty tier
        easy_riddles = [
            {"q": "What has hands but can't clap?", "a": "Clock", "opts": ["Clock", "Statue", "Robot", "Puppet"]},
            {"q": "What has to be broken before you can use it?", "a": "Egg", "opts": ["Egg", "Glass", "Seal", "Lock"]},
            {"q": "What gets wetter the more it dries?", "a": "Towel", "opts": ["Towel", "Sponge", "Paper", "Sand"]},
            {"q": "What has a head and a tail but no body?", "a": "Coin", "opts": ["Coin", "Snake", "Arrow", "Pin"]},
            {"q": "What has keys but can't open locks?", "a": "Piano", "opts": ["Piano", "Keyboard", "Door", "Map"]},
            {"q": "What has legs but doesn't walk?", "a": "Table", "opts": ["Table", "Chair", "Bed", "Desk"]},
            {"q": "What has one eye but can't see?", "a": "Needle", "opts": ["Needle", "Cyclops", "Camera", "Storm"]},
            {"q": "What goes up but never comes down?", "a": "Age", "opts": ["Age", "Balloon", "Smoke", "Temperature"]},
        ]

        medium_riddles = [
            {"q": "I have cities, but no houses. I have mountains, but no trees. What am I?", "a": "Map", "opts": ["Map", "Globe", "Atlas", "Painting"]},
            {"q": "What can you catch but not throw?", "a": "Cold", "opts": ["Cold", "Ball", "Fish", "Shadow"]},
            {"q": "What can travel around the world while staying in a corner?", "a": "Stamp", "opts": ["Stamp", "Spider", "Shadow", "Wind"]},
            {"q": "What has a neck but no head?", "a": "Bottle", "opts": ["Bottle", "Guitar", "Shirt", "Giraffe"]},
            {"q": "What can run but never walks?", "a": "Water", "opts": ["Water", "Wind", "Time", "Horse"]},
            {"q": "What is full of holes but still holds water?", "a": "Sponge", "opts": ["Sponge", "Net", "Bucket", "Cloud"]},
            {"q": "I am not alive, but I grow; I don't have lungs, but I need air. What am I?", "a": "Fire", "opts": ["Fire", "Plant", "Cloud", "Balloon"]},
            {"q": "What invention lets you look right through a wall?", "a": "Window", "opts": ["Window", "X-ray", "Mirror", "Camera"]},
            {"q": "I have teeth but cannot eat. What am I?", "a": "Comb", "opts": ["Comb", "Saw", "Zipper", "Gear"]},
        ]

        hard_riddles = [
            {"q": "What comes once in a minute, twice in a moment, but never in a thousand years?", "a": "Letter M", "opts": ["Letter M", "Time", "Second", "Hour"]},
            {"q": "What has four legs in the morning, two at noon, and three in the evening?", "a": "Human", "opts": ["Human", "Dog", "Cat", "Chair"]},
            {"q": "What begins with T, ends with T, and has T in it?", "a": "Teapot", "opts": ["Teapot", "Toast", "Tent", "Trust"]},
            {"q": "What word is spelled incorrectly in every dictionary?", "a": "Incorrectly", "opts": ["Incorrectly", "Dictionary", "Spelling", "Error"]},
            {"q": "What can you hold in your left hand but not your right?", "a": "Right elbow", "opts": ["Right elbow", "Left hand", "Heart", "Breath"]},
            {"q": "What is always in front of you but can't be seen?", "a": "Future", "opts": ["Future", "Air", "Shadow", "Nose"]},
            {"q": "I have branches but no fruit, no trunk, no leaves. What am I?", "a": "Bank", "opts": ["Bank", "Tree", "River", "Family"]},
            {"q": "The more you take, the more you leave behind. What are they?", "a": "Footsteps", "opts": ["Footsteps", "Memories", "Photos", "Breaths"]},
            {"q": "What building has the most stories?", "a": "Library", "opts": ["Library", "Skyscraper", "Hotel", "School"]},
            {"q": "I fly without wings. I cry without eyes. What am I?", "a": "Cloud", "opts": ["Cloud", "Wind", "Ghost", "Onion"]},
            {"q": "What has 13 hearts but no other organs?", "a": "Deck of cards", "opts": ["Deck of cards", "Calendar", "Clock", "Tree"]},
        ]

        # Select pool based on difficulty
        if difficulty in ("beginner", "easy"):
            pool = easy_riddles
        elif difficulty == "medium":
            pool = easy_riddles + medium_riddles
        elif difficulty == "hard":
            pool = medium_riddles + hard_riddles
        else:  # expert
            pool = hard_riddles

        chosen = random.choice(pool)
        options = chosen["opts"][:]
        random.shuffle(options)

        return {
            "type": "RIDDLE",
            "prompt": chosen["q"],
            "answer": chosen["a"],
            "options": options,
        }

    # ── LOGIC generator (difficulty-aware) ───────────────────────────

    @staticmethod
    def _generate_logic(difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate a logic puzzle scaled to difficulty.

        Variants: odd-one-out, analogies, syllogisms, and ranking puzzles.
        """
        difficulty = _clamp_difficulty(difficulty)

        easy = [
            {
                "q": "Which number does not belong? 2, 4, 6, 9, 8",
                "a": "9",
                "opts": ["9", "2", "6", "8"],
            },
            {
                "q": "If all roses are flowers and some flowers fade quickly, "
                     "which statement must be true?",
                "a": "Some roses may fade quickly",
                "opts": [
                    "Some roses may fade quickly",
                    "All flowers are roses",
                    "No roses fade",
                    "All roses fade quickly",
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
        ]

        medium = [
            {
                "q": "All A are B. Some B are C. Which conclusion follows?",
                "a": "Some A may be C",
                "opts": [
                    "Some A may be C",
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
                "q": "If 3 pens cost $6, how many pens can you buy for $20?",
                "a": "10",
                "opts": ["10", "9", "12", "8"],
            },
            {
                "q": "Book is to Reading as Fork is to ?",
                "a": "Eating",
                "opts": ["Eating", "Cooking", "Spoon", "Kitchen"],
            },
            {
                "q": "Which comes next in the letter series? A, C, F, J, ?",
                "a": "O",
                "opts": ["O", "N", "M", "P"],
            },
            {
                "q": "Tom is older than Sue. Sue is older than Mia. "
                     "Who is the youngest?",
                "a": "Mia",
                "opts": ["Mia", "Sue", "Tom", "Cannot tell"],
            },
            {
                "q": "If only one statement is true: "
                     "(1) The answer is 12  (2) The answer is 15  "
                     "(3) The answer is not 12  — which is correct?",
                "a": "15",
                "opts": ["15", "12", "Neither", "Both 12 and 15"],
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
                "q": "Five friends sit in a row. Ava is not at either end. "
                     "Ben sits to the immediate left of Ava. "
                     "Cara sits at the right end. Who can sit at the left end?",
                "a": "Dan or Eve",
                "opts": ["Dan or Eve", "Ava", "Ben", "Cara"],
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
                     "(A) Answer is 8  (B) Answer is 11  "
                     "(C) Answer is not 8  (D) Answer is 14. What is the answer?",
                "a": "11",
                "opts": ["11", "8", "14", "Cannot determine"],
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
                     "and 86 legs. How many chickens?",
                "a": "17",
                "opts": ["17", "13", "15", "20"],
            },
        ]

        if difficulty in ("beginner", "easy"):
            pool = easy
        elif difficulty == "medium":
            pool = easy + medium
        elif difficulty == "hard":
            pool = medium + hard
        else:
            pool = hard + expert

        chosen = random.choice(pool)
        options = chosen["opts"][:]
        random.shuffle(options)

        return {
            "type": "LOGIC",
            "prompt": chosen["q"],
            "answer": chosen["a"],
            "options": options,
        }

    # ── WORD GAME generator (difficulty-aware) ───────────────────────

    @staticmethod
    def _generate_word_game(difficulty: str = "medium") -> Dict[str, Any]:
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
                ("Which word does not belong?", "Blue", ["Blue", "Red", "Green", "Chair"]),
                ("Which word does not belong?", "Banana", ["Dog", "Cat", "Bird", "Banana"]),
                ("Which word does not belong?", "Shoe", ["Shoe", "Car", "Bus", "Train"]),
                ("Which word does not belong?", "Pencil", ["Apple", "Orange", "Grape", "Pencil"]),
                ("Which word does not belong?", "Happy", ["Happy", "Table", "Chair", "Desk"]),
            ]
            prompt, answer, options = random.choice(odd_sets)
            opts = options[:]
            random.shuffle(opts)
            return {
                "type": "WORD_GAME",
                "prompt": prompt + " " + ", ".join(options),
                "answer": answer,
                "options": opts,
            }

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
            # Letter options including correct
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            wrong = set()
            while len(wrong) < 3:
                ch = random.choice(alphabet)
                if ch != answer:
                    wrong.add(ch)
            options = [answer] + list(wrong)
            random.shuffle(options)
            return {
                "type": "WORD_GAME",
                "prompt": f"Fill in the missing letter: {blanked}",
                "answer": answer,
                "options": options,
            }

        if variant == "anagram_hint":
            hint = f"(starts with {word[0]}, {len(word)} letters)"
            prompt = f"Unscramble: {scrambled} {hint}"
        else:
            prompt = f"Unscramble the word: {scrambled}"

        options = [word] + distractors[:3]
        # Ensure unique options
        options = list(dict.fromkeys(options))
        while len(options) < 4:
            # pad with letter-swapped decoys
            chars = list(word)
            i, j = random.sample(range(len(chars)), 2)
            chars[i], chars[j] = chars[j], chars[i]
            decoy = "".join(chars)
            if decoy != word and decoy not in options:
                options.append(decoy)
        options = options[:4]
        random.shuffle(options)

        return {
            "type": "WORD_GAME",
            "prompt": prompt,
            "answer": word,
            "options": options,
        }

    # ── QUIZ generator (difficulty-aware) ────────────────────────────

    @staticmethod
    def _generate_quiz(difficulty: str = "medium") -> Dict[str, Any]:
        """Generate a quick general-knowledge quiz question."""
        difficulty = _clamp_difficulty(difficulty)

        easy = [
            {"q": "How many days are in a week?", "a": "7", "opts": ["7", "5", "6", "8"]},
            {"q": "What color do you get by mixing red and white?", "a": "Pink", "opts": ["Pink", "Purple", "Orange", "Brown"]},
            {"q": "How many continents are there?", "a": "7", "opts": ["7", "5", "6", "8"]},
            {"q": "What is the capital of France?", "a": "Paris", "opts": ["Paris", "London", "Rome", "Berlin"]},
            {"q": "How many sides does a triangle have?", "a": "3", "opts": ["3", "4", "5", "2"]},
            {"q": "Which planet is known as the Red Planet?", "a": "Mars", "opts": ["Mars", "Venus", "Jupiter", "Mercury"]},
            {"q": "What do bees produce?", "a": "Honey", "opts": ["Honey", "Milk", "Silk", "Wax only"]},
            {"q": "How many hours are in a day?", "a": "24", "opts": ["24", "12", "48", "60"]},
        ]

        medium = [
            {"q": "What is the chemical symbol for water?", "a": "H2O", "opts": ["H2O", "CO2", "O2", "NaCl"]},
            {"q": "Who painted the Mona Lisa?", "a": "Leonardo da Vinci", "opts": ["Leonardo da Vinci", "Michelangelo", "Picasso", "Van Gogh"]},
            {"q": "What is the largest ocean on Earth?", "a": "Pacific", "opts": ["Pacific", "Atlantic", "Indian", "Arctic"]},
            {"q": "How many bones are in the adult human body?", "a": "206", "opts": ["206", "198", "250", "180"]},
            {"q": "What gas do plants absorb from the air?", "a": "Carbon dioxide", "opts": ["Carbon dioxide", "Oxygen", "Nitrogen", "Helium"]},
            {"q": "Which country is home to the kangaroo?", "a": "Australia", "opts": ["Australia", "Brazil", "India", "South Africa"]},
            {"q": "What is the square root of 81?", "a": "9", "opts": ["9", "8", "7", "10"]},
            {"q": "In which sport is the term 'love' used for a score of zero?", "a": "Tennis", "opts": ["Tennis", "Golf", "Soccer", "Cricket"]},
        ]

        hard = [
            {"q": "What year did World War II end?", "a": "1945", "opts": ["1945", "1944", "1939", "1948"]},
            {"q": "What is the hardest natural substance on Earth?", "a": "Diamond", "opts": ["Diamond", "Gold", "Iron", "Quartz"]},
            {"q": "Which element has the chemical symbol Au?", "a": "Gold", "opts": ["Gold", "Silver", "Aluminum", "Argon"]},
            {"q": "What is the smallest prime number?", "a": "2", "opts": ["2", "1", "3", "0"]},
            {"q": "Who developed the theory of relativity?", "a": "Albert Einstein", "opts": ["Albert Einstein", "Newton", "Tesla", "Hawking"]},
            {"q": "What is the capital of Canada?", "a": "Ottawa", "opts": ["Ottawa", "Toronto", "Vancouver", "Montreal"]},
            {"q": "How many chambers does a human heart have?", "a": "4", "opts": ["4", "2", "3", "5"]},
            {"q": "Which planet has the most moons?", "a": "Saturn", "opts": ["Saturn", "Jupiter", "Uranus", "Neptune"]},
        ]

        expert = [
            {"q": "What is the powerhouse of the cell?", "a": "Mitochondria", "opts": ["Mitochondria", "Nucleus", "Ribosome", "Chloroplast"]},
            {"q": "What is the speed of light in vacuum (approx.)?", "a": "300,000 km/s", "opts": ["300,000 km/s", "150,000 km/s", "30,000 km/s", "3,000 km/s"]},
            {"q": "Which mathematician invented calculus independently of Newton?", "a": "Leibniz", "opts": ["Leibniz", "Euler", "Gauss", "Pascal"]},
            {"q": "What is the chemical formula for table salt?", "a": "NaCl", "opts": ["NaCl", "KCl", "NaOH", "CaCO3"]},
            {"q": "In which year did the Titanic sink?", "a": "1912", "opts": ["1912", "1910", "1914", "1905"]},
            {"q": "What is the largest internal organ in the human body?", "a": "Liver", "opts": ["Liver", "Lungs", "Brain", "Stomach"]},
            {"q": "Which composer wrote 'The Four Seasons'?", "a": "Vivaldi", "opts": ["Vivaldi", "Bach", "Mozart", "Beethoven"]},
            {"q": "What does DNA stand for?", "a": "Deoxyribonucleic acid", "opts": ["Deoxyribonucleic acid", "Dinucleic acid", "Deoxyribose acid", "Dual nucleic acid"]},
        ]

        if difficulty in ("beginner", "easy"):
            pool = easy
        elif difficulty == "medium":
            pool = easy + medium
        elif difficulty == "hard":
            pool = medium + hard
        else:
            pool = hard + expert

        chosen = random.choice(pool)
        options = chosen["opts"][:]
        random.shuffle(options)

        return {
            "type": "QUIZ",
            "prompt": chosen["q"],
            "answer": chosen["a"],
            "options": options,
        }

    # ── Options generator ────────────────────────────────────────────

    @staticmethod
    def _generate_options(correct_answer: str) -> list[str]:
        """Generate 3 plausible incorrect options alongside the correct one."""
        try:
            ans_val = int(correct_answer)
            options = {ans_val}
            while len(options) < 4:
                offset = random.randint(-10, 10)
                if offset != 0:
                    options.add(ans_val + offset)
            opts = [str(x) for x in options]
            random.shuffle(opts)
            return opts
        except ValueError:
            return [correct_answer]

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

