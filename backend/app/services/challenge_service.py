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

# Network / UI grace added on top of the published time limit (seconds)
VERIFY_TIME_GRACE_SECONDS = 5


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
    def generate_challenge(
        challenge_type: ChallengeType,
        difficulty: str = "medium",
        current_hour: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate a cognitive puzzle personalized by difficulty and time.

        Args:
            challenge_type: The requested category of puzzle.
            difficulty: User's difficulty preference
                        (beginner / easy / medium / hard / expert).
            current_hour: Current hour (0-23) for time-of-day adjustment.
                          If None, the system clock is used.

        Returns:
            A dictionary with the challenge prompt, type, correct answer,
            the effective difficulty applied, and a time_limit_seconds hint.
        """
        # Resolve effective difficulty (profile pref + time adjustment)
        effective = _adjust_for_time(difficulty, current_hour)

        # Handle RANDOM type
        if challenge_type == ChallengeType.RANDOM:
            challenge_type = random.choice([
                ChallengeType.MATH,
                ChallengeType.PATTERN,
                ChallengeType.MEMORY,
                ChallengeType.RIDDLE,
            ])

        # Normalize frontend alias
        if challenge_type == ChallengeType.WORD:
            challenge_type = ChallengeType.WORD_GAME

        # Dispatch to the appropriate generator
        generators = {
            ChallengeType.MATH: ChallengeService._generate_math,
            ChallengeType.PATTERN: ChallengeService._generate_pattern,
            ChallengeType.MEMORY: ChallengeService._generate_memory,
            ChallengeType.RIDDLE: ChallengeService._generate_riddle,
        }

        generator = generators.get(challenge_type)
        if generator:
            result = generator(effective)
        else:
            # Logic, Word Game, Quiz → AI or fallback
            result = ChallengeService._generate_ai_challenge(
                challenge_type, effective
            )

        # Attach metadata about the personalization applied
        result["difficulty"] = effective
        result["time_limit_seconds"] = ChallengeService._time_limit_for(effective)
        return result

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
        if challenge_type == ChallengeType.RIDDLE:
            return ChallengeService._generate_riddle(difficulty)
        else:
            return ChallengeService._generate_math(difficulty)

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
    def store_challenge_session(
        user_id: int,
        alarm_id: int,
        challenge: Dict[str, Any],
        db: "Session",
    ) -> None:
        """Persist the issued challenge so verify can trust server state."""
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
        payload = {
            "answer": str(challenge.get("answer", "")),
            "prompt": challenge.get("prompt") or "",
            "difficulty": challenge.get("difficulty") or "medium",
            "time_limit_seconds": int(challenge.get("time_limit_seconds") or 30),
            "issued_at": issued_at,
        }
        if row:
            for key, value in payload.items():
                setattr(row, key, value)
        else:
            db.add(
                ChallengeSession(
                    user_id=user_id,
                    alarm_id=alarm_id,
                    **payload,
                )
            )
        db.commit()

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
        issued_at = row.issued_at
        if issued_at is not None and issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        return {
            "answer": row.answer,
            "prompt": row.prompt or "",
            "difficulty": row.difficulty or "medium",
            "time_limit_seconds": int(row.time_limit_seconds or 30),
            "issued_at": issued_at,
        }

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

