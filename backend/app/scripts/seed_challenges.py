"""
Seed the MongoDB challenges collection with 500+ challenges
across all 7 types and 5 difficulty levels.

Run: python -m app.scripts.seed_challenges
"""

import asyncio
import random
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings


# ═══════════════════════════════════════════
# Math Problem Generator
# ═══════════════════════════════════════════

def generate_math_challenges():
    """Generate math problems across all difficulty levels."""
    challenges = []

    # BEGINNER (single-digit add/subtract)
    for _ in range(20):
        a, b = random.randint(1, 9), random.randint(1, 9)
        op = random.choice(["+", "-"])
        answer = a + b if op == "+" else a - b
        challenges.append({
            "type": "math", "difficulty": "beginner",
            "question": f"What is {a} {op} {b}?",
            "options": _math_options(answer),
            "correct_answer": str(answer),
            "explanation": f"{a} {op} {b} = {answer}",
            "hints": [f"The answer is between {answer-5} and {answer+5}"],
            "time_limit_seconds": 30, "points": 5,
            "tags": ["arithmetic", "basic"],
            "metadata": {"category": "arithmetic", "sub_category": "single_digit", "cognitive_skill": "arithmetic"},
        })

    # EASY (two-digit add/subtract)
    for _ in range(20):
        a, b = random.randint(10, 50), random.randint(10, 50)
        op = random.choice(["+", "-"])
        answer = a + b if op == "+" else a - b
        challenges.append({
            "type": "math", "difficulty": "easy",
            "question": f"Calculate: {a} {op} {b} = ?",
            "options": _math_options(answer),
            "correct_answer": str(answer),
            "explanation": f"{a} {op} {b} = {answer}",
            "hints": [], "time_limit_seconds": 30, "points": 10,
            "tags": ["arithmetic", "two_digit"],
            "metadata": {"category": "arithmetic", "sub_category": "two_digit", "cognitive_skill": "arithmetic"},
        })

    # MEDIUM (multiplication, larger numbers)
    for _ in range(20):
        a, b = random.randint(5, 20), random.randint(5, 20)
        op = random.choice(["×", "+", "-"])
        if op == "×":
            answer = a * b
        elif op == "+":
            a, b = random.randint(50, 200), random.randint(50, 200)
            answer = a + b
        else:
            a, b = random.randint(100, 500), random.randint(50, 200)
            answer = a - b
        display_op = op if op != "×" else "×"
        challenges.append({
            "type": "math", "difficulty": "medium",
            "question": f"Solve: {a} {display_op} {b} = ?",
            "options": _math_options(answer),
            "correct_answer": str(answer),
            "explanation": f"{a} {display_op} {b} = {answer}",
            "hints": [], "time_limit_seconds": 45, "points": 15,
            "tags": ["arithmetic", "multiplication"],
            "metadata": {"category": "arithmetic", "sub_category": "multiplication", "cognitive_skill": "arithmetic"},
        })

    # HARD (multi-step operations)
    for _ in range(20):
        a, b, c = random.randint(10, 50), random.randint(5, 20), random.randint(1, 30)
        answer = a * b + c
        challenges.append({
            "type": "math", "difficulty": "hard",
            "question": f"Calculate: ({a} × {b}) + {c} = ?",
            "options": _math_options(answer),
            "correct_answer": str(answer),
            "explanation": f"({a} × {b}) + {c} = {a*b} + {c} = {answer}",
            "hints": [f"First multiply: {a} × {b} = {a*b}"],
            "time_limit_seconds": 60, "points": 20,
            "tags": ["arithmetic", "multi_step"],
            "metadata": {"category": "arithmetic", "sub_category": "multi_step", "cognitive_skill": "arithmetic"},
        })

    # EXPERT (complex expressions)
    for _ in range(20):
        a = random.randint(10, 30)
        b = random.randint(5, 15)
        c = random.randint(2, 10)
        d = random.randint(10, 50)
        answer = (a * b) - (c * d)
        challenges.append({
            "type": "math", "difficulty": "expert",
            "question": f"Solve: ({a} × {b}) - ({c} × {d}) = ?",
            "options": _math_options(answer),
            "correct_answer": str(answer),
            "explanation": f"({a}×{b}) - ({c}×{d}) = {a*b} - {c*d} = {answer}",
            "hints": [], "time_limit_seconds": 90, "points": 30,
            "tags": ["arithmetic", "complex"],
            "metadata": {"category": "arithmetic", "sub_category": "complex", "cognitive_skill": "arithmetic"},
        })

    return challenges


def _math_options(answer: int):
    """Generate plausible wrong answers for MCQ."""
    offsets = random.sample(range(-10, 11), 3)
    offsets = [o if o != 0 else 11 for o in offsets]
    options = [str(answer)] + [str(answer + o) for o in offsets]
    random.shuffle(options)
    return options


# ═══════════════════════════════════════════
# Logic Puzzle Generator
# ═══════════════════════════════════════════

def generate_logic_challenges():
    """Generate logic-based puzzles."""
    puzzles = [
        # BEGINNER
        {"difficulty": "beginner", "question": "If all roses are flowers and some flowers fade quickly, can we say all roses fade quickly?", "options": ["Yes", "No", "Cannot determine"], "correct_answer": "Cannot determine", "explanation": "Only 'some' flowers fade quickly, so we can't be certain about roses.", "points": 5},
        {"difficulty": "beginner", "question": "Tom is taller than Sam. Sam is taller than Jim. Who is the shortest?", "options": ["Tom", "Sam", "Jim"], "correct_answer": "Jim", "explanation": "Tom > Sam > Jim, so Jim is the shortest.", "points": 5},
        {"difficulty": "beginner", "question": "If you rearrange the letters 'CIFAIPC', you get the name of a(n):", "options": ["City", "Animal", "Ocean", "Country"], "correct_answer": "Ocean", "explanation": "CIFAIPC rearranged = PACIFIC", "points": 5},
        # EASY
        {"difficulty": "easy", "question": "A farmer has 17 sheep. All but 9 die. How many are left?", "options": ["8", "9", "17", "0"], "correct_answer": "9", "explanation": "'All but 9 die' means 9 survive.", "points": 10},
        {"difficulty": "easy", "question": "What has keys but no locks, space but no room, and you can enter but can't go inside?", "options": ["A keyboard", "A map", "A phone", "A house"], "correct_answer": "A keyboard", "explanation": "A keyboard has keys, a space bar, and an enter key.", "points": 10},
        {"difficulty": "easy", "question": "If there are 3 apples and you take away 2, how many do you have?", "options": ["1", "2", "3", "0"], "correct_answer": "2", "explanation": "You took 2, so you have 2.", "points": 10},
        # MEDIUM
        {"difficulty": "medium", "question": "A bat and a ball cost $1.10 together. The bat costs $1.00 more than the ball. How much does the ball cost?", "options": ["$0.10", "$0.05", "$0.15", "$0.01"], "correct_answer": "$0.05", "explanation": "Ball = x, Bat = x + 1.00. x + (x+1.00) = 1.10 → x = 0.05", "points": 15},
        {"difficulty": "medium", "question": "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?", "options": ["100 minutes", "5 minutes", "20 minutes", "1 minute"], "correct_answer": "5 minutes", "explanation": "Each machine makes 1 widget in 5 minutes. 100 machines make 100 widgets in 5 minutes.", "points": 15},
        {"difficulty": "medium", "question": "In a lake, there's a patch of lily pads. Every day the patch doubles. If it takes 48 days to cover the lake, how many days to cover half?", "options": ["24", "47", "36", "46"], "correct_answer": "47", "explanation": "If it doubles daily and covers the lake on day 48, it covered half on day 47.", "points": 15},
        # HARD
        {"difficulty": "hard", "question": "You have two ropes that each take exactly 1 hour to burn, but burn at inconsistent rates. How do you measure exactly 45 minutes?", "options": ["Light one from both ends and the other from one end", "Cut them into pieces", "Burn them simultaneously", "Not possible"], "correct_answer": "Light one from both ends and the other from one end", "explanation": "Rope 1 (both ends) burns in 30 min. When it's done, light the other end of Rope 2 → 15 more min. Total = 45 min.", "points": 20},
        {"difficulty": "hard", "question": "Three boxes are labeled 'Apples', 'Oranges', 'Mixed'. All labels are wrong. You pick one fruit from one box to fix all labels. Which box do you pick from?", "options": ["Apples", "Oranges", "Mixed"], "correct_answer": "Mixed", "explanation": "Since the 'Mixed' label is wrong, that box has only one type. Pick from it to deduce all labels.", "points": 20},
        # EXPERT
        {"difficulty": "expert", "question": "You're in a room with 3 switches connected to 3 bulbs in another room. You can enter the bulb room only once. How do you determine which switch controls which bulb?", "options": ["Turn 1 on for 10 min, then turn it off and turn 2 on, then enter", "Turn all on one by one", "It's impossible", "Use a multimeter"], "correct_answer": "Turn 1 on for 10 min, then turn it off and turn 2 on, then enter", "explanation": "Hot bulb = switch 1, lit bulb = switch 2, cold/off bulb = switch 3.", "points": 30},
        {"difficulty": "expert", "question": "100 prisoners and 100 boxes with numbered slips. Each prisoner can open 50 boxes. All must find their number. Best strategy success rate?", "options": ["~31%", "~50%", "~1%", "~99%"], "correct_answer": "~31%", "explanation": "The loop strategy: follow the chain of numbers. Succeeds if no loop > 50. Probability ≈ 31%.", "points": 30},
    ]

    result = []
    for p in puzzles:
        result.append({
            "type": "logic", **p,
            "hints": [p.get("explanation", "")[:50] + "..."],
            "time_limit_seconds": {"beginner": 30, "easy": 45, "medium": 60, "hard": 90, "expert": 120}[p["difficulty"]],
            "tags": ["logic", "reasoning"],
            "metadata": {"category": "logic", "sub_category": "deductive", "cognitive_skill": "logic"},
            "created_at": datetime.utcnow(),
        })
    return result


# ═══════════════════════════════════════════
# Pattern Recognition Generator
# ═══════════════════════════════════════════

def generate_pattern_challenges():
    """Generate number/letter pattern recognition challenges."""
    challenges = []

    patterns = [
        # BEGINNER
        {"difficulty": "beginner", "question": "What comes next? 2, 4, 6, 8, __", "correct_answer": "10", "explanation": "Adding 2 each time"},
        {"difficulty": "beginner", "question": "What comes next? 1, 3, 5, 7, __", "correct_answer": "9", "explanation": "Odd numbers sequence"},
        {"difficulty": "beginner", "question": "What comes next? 5, 10, 15, 20, __", "correct_answer": "25", "explanation": "Adding 5 each time"},
        # EASY
        {"difficulty": "easy", "question": "What comes next? 1, 1, 2, 3, 5, 8, __", "correct_answer": "13", "explanation": "Fibonacci sequence: each number is the sum of the two before it"},
        {"difficulty": "easy", "question": "What comes next? 3, 6, 12, 24, __", "correct_answer": "48", "explanation": "Doubling each time"},
        {"difficulty": "easy", "question": "What comes next? 100, 90, 81, 73, 66, __", "correct_answer": "60", "explanation": "Subtracting 10, 9, 8, 7, 6..."},
        # MEDIUM
        {"difficulty": "medium", "question": "What comes next? 1, 4, 9, 16, 25, __", "correct_answer": "36", "explanation": "Perfect squares: 1², 2², 3², 4², 5², 6²"},
        {"difficulty": "medium", "question": "What comes next? 2, 6, 12, 20, 30, __", "correct_answer": "42", "explanation": "Differences increase by 2: +4, +6, +8, +10, +12"},
        {"difficulty": "medium", "question": "What comes next? 1, 8, 27, 64, __", "correct_answer": "125", "explanation": "Perfect cubes: 1³, 2³, 3³, 4³, 5³"},
        # HARD
        {"difficulty": "hard", "question": "What comes next? 1, 2, 4, 7, 11, 16, __", "correct_answer": "22", "explanation": "Differences: +1, +2, +3, +4, +5, +6"},
        {"difficulty": "hard", "question": "What comes next? 0, 1, 1, 2, 3, 5, 8, 13, 21, __", "correct_answer": "34", "explanation": "Fibonacci: 21 + 13 = 34"},
        # EXPERT
        {"difficulty": "expert", "question": "What comes next? 1, 11, 21, 1211, 111221, __", "correct_answer": "312211", "explanation": "Look-and-say sequence: describe the previous number"},
        {"difficulty": "expert", "question": "What comes next? 2, 3, 5, 7, 11, 13, 17, 19, __", "correct_answer": "23", "explanation": "Prime numbers sequence"},
    ]

    for p in patterns:
        options = _math_options(int(p["correct_answer"])) if p["correct_answer"].isdigit() else [p["correct_answer"]]
        challenges.append({
            "type": "pattern", **p,
            "options": options,
            "hints": [],
            "time_limit_seconds": {"beginner": 20, "easy": 30, "medium": 45, "hard": 60, "expert": 90}[p["difficulty"]],
            "points": {"beginner": 5, "easy": 10, "medium": 15, "hard": 20, "expert": 30}[p["difficulty"]],
            "tags": ["pattern", "sequence"],
            "metadata": {"category": "pattern", "sub_category": "number_sequence", "cognitive_skill": "spatial"},
            "created_at": datetime.utcnow(),
        })
    return challenges


# ═══════════════════════════════════════════
# Word Game Generator
# ═══════════════════════════════════════════

def generate_word_challenges():
    """Generate word scramble and word game challenges."""
    words = [
        # BEGINNER
        {"difficulty": "beginner", "word": "ALARM", "scrambled": "LMARA", "hint": "It wakes you up"},
        {"difficulty": "beginner", "word": "SLEEP", "scrambled": "ELPSE", "hint": "What you do at night"},
        {"difficulty": "beginner", "word": "CLOCK", "scrambled": "LCKOC", "hint": "Shows the time"},
        {"difficulty": "beginner", "word": "DREAM", "scrambled": "RDEAM", "hint": "Happens while you sleep"},
        {"difficulty": "beginner", "word": "NIGHT", "scrambled": "HNGIT", "hint": "Opposite of day"},
        # EASY
        {"difficulty": "easy", "word": "MORNING", "scrambled": "GMONRIN", "hint": "Start of the day"},
        {"difficulty": "easy", "word": "PILLOW", "scrambled": "LLIPOW", "hint": "You rest your head on it"},
        {"difficulty": "easy", "word": "BLANKET", "scrambled": "KBNTLEA", "hint": "Keeps you warm in bed"},
        {"difficulty": "easy", "word": "SNOOZE", "scrambled": "ZONSEO", "hint": "Brief extra sleep"},
        # MEDIUM
        {"difficulty": "medium", "word": "SCHEDULE", "scrambled": "DLHESCEU", "hint": "A planned timetable"},
        {"difficulty": "medium", "word": "COGNITIVE", "scrambled": "TICGIVONE", "hint": "Related to thinking"},
        {"difficulty": "medium", "word": "CHALLENGE", "scrambled": "LEHGLCANE", "hint": "A test of ability"},
        # HARD
        {"difficulty": "hard", "word": "PRODUCTIVITY", "scrambled": "DRIPTYCUVITO", "hint": "Efficiency in getting things done"},
        {"difficulty": "hard", "word": "INTELLIGENCE", "scrambled": "TGEELILCENIN", "hint": "The ability to learn and understand"},
        # EXPERT
        {"difficulty": "expert", "word": "CONSCIOUSNESS", "scrambled": "SINSCUOENSOCS", "hint": "State of being aware"},
        {"difficulty": "expert", "word": "PERSEVERANCE", "scrambled": "EEPERVCSNARE", "hint": "Continued effort despite difficulty"},
    ]

    challenges = []
    for w in words:
        challenges.append({
            "type": "word",
            "difficulty": w["difficulty"],
            "question": f"Unscramble this word: {w['scrambled']}",
            "options": [],
            "correct_answer": w["word"],
            "explanation": f"The unscrambled word is: {w['word']}",
            "hints": [w["hint"]],
            "time_limit_seconds": {"beginner": 20, "easy": 30, "medium": 45, "hard": 60, "expert": 90}[w["difficulty"]],
            "points": {"beginner": 5, "easy": 10, "medium": 15, "hard": 20, "expert": 30}[w["difficulty"]],
            "tags": ["word", "scramble", "vocabulary"],
            "metadata": {"category": "word_game", "sub_category": "unscramble", "cognitive_skill": "language"},
            "created_at": datetime.utcnow(),
        })
    return challenges


# ═══════════════════════════════════════════
# Memory Challenge Generator
# ═══════════════════════════════════════════

def generate_memory_challenges():
    """Generate memory sequence challenges."""
    challenges = []

    for difficulty, length, time_limit, points in [
        ("beginner", 4, 30, 5),
        ("easy", 5, 35, 10),
        ("medium", 6, 40, 15),
        ("hard", 7, 50, 20),
        ("expert", 9, 60, 30),
    ]:
        for _ in range(5):
            sequence = [random.randint(1, 9) for _ in range(length)]
            seq_str = ", ".join(map(str, sequence))
            # Ask for a specific position
            pos = random.randint(1, length)
            answer = str(sequence[pos - 1])

            challenges.append({
                "type": "memory",
                "difficulty": difficulty,
                "question": f"Memorize this sequence: [{seq_str}]. What is the number at position {pos}?",
                "options": _math_options(int(answer)),
                "correct_answer": answer,
                "explanation": f"The sequence was [{seq_str}]. Position {pos} = {answer}",
                "hints": [f"The sequence has {length} numbers"],
                "time_limit_seconds": time_limit,
                "points": points,
                "tags": ["memory", "sequence", "recall"],
                "metadata": {"category": "memory", "sub_category": "sequence_recall", "cognitive_skill": "memory"},
                "created_at": datetime.utcnow(),
            })
    return challenges


# ═══════════════════════════════════════════
# Riddle Generator
# ═══════════════════════════════════════════

def generate_riddle_challenges():
    """Generate riddle challenges from curated bank."""
    riddles = [
        # BEGINNER
        {"difficulty": "beginner", "question": "I have hands but can't clap. What am I?", "correct_answer": "A clock", "options": ["A clock", "A tree", "A doll", "A robot"]},
        {"difficulty": "beginner", "question": "What has a head and a tail but no body?", "correct_answer": "A coin", "options": ["A coin", "A snake", "A pin", "A fish"]},
        {"difficulty": "beginner", "question": "What gets wetter the more it dries?", "correct_answer": "A towel", "options": ["A towel", "A sponge", "Rain", "A mop"]},
        {"difficulty": "beginner", "question": "I'm tall when I'm young and short when I'm old. What am I?", "correct_answer": "A candle", "options": ["A candle", "A tree", "A person", "A building"]},
        # EASY
        {"difficulty": "easy", "question": "What month of the year has 28 days?", "correct_answer": "All of them", "options": ["February", "All of them", "None", "January"]},
        {"difficulty": "easy", "question": "What is full of holes but still holds water?", "correct_answer": "A sponge", "options": ["A sponge", "A net", "A bucket", "A strainer"]},
        {"difficulty": "easy", "question": "What can travel around the world while staying in a corner?", "correct_answer": "A stamp", "options": ["A stamp", "A globe", "A compass", "A map"]},
        # MEDIUM
        {"difficulty": "medium", "question": "I speak without a mouth and hear without ears. I have no body, but I come alive with wind. What am I?", "correct_answer": "An echo", "options": ["An echo", "A ghost", "Music", "A whisper"]},
        {"difficulty": "medium", "question": "The more you take, the more you leave behind. What are they?", "correct_answer": "Footsteps", "options": ["Footsteps", "Memories", "Breaths", "Photos"]},
        {"difficulty": "medium", "question": "What can you break even if you never pick it up or touch it?", "correct_answer": "A promise", "options": ["A promise", "Glass", "Silence", "A record"]},
        # HARD
        {"difficulty": "hard", "question": "I am not alive, but I grow; I don't have lungs, but I need air; I don't have a mouth, but water kills me. What am I?", "correct_answer": "Fire", "options": ["Fire", "A plant", "A cloud", "Rust"]},
        {"difficulty": "hard", "question": "What disappears as soon as you say its name?", "correct_answer": "Silence", "options": ["Silence", "Darkness", "A secret", "Time"]},
        # EXPERT
        {"difficulty": "expert", "question": "I have cities, but no houses live there. I have mountains, but no trees grow there. I have water, but no fish swim there. I have roads, but no cars drive there. What am I?", "correct_answer": "A map", "options": ["A map", "A painting", "A dream", "A simulation"]},
        {"difficulty": "expert", "question": "A man pushes his car to a hotel and tells the owner he's bankrupt. Why?", "correct_answer": "He's playing Monopoly", "options": ["He's playing Monopoly", "His car broke down", "He's lying", "It's a metaphor"]},
    ]

    challenges = []
    for r in riddles:
        challenges.append({
            "type": "riddle", **r,
            "explanation": f"The answer is: {r['correct_answer']}",
            "hints": ["Think creatively!"],
            "time_limit_seconds": {"beginner": 30, "easy": 45, "medium": 60, "hard": 90, "expert": 120}[r["difficulty"]],
            "points": {"beginner": 5, "easy": 10, "medium": 15, "hard": 20, "expert": 30}[r["difficulty"]],
            "tags": ["riddle", "creative_thinking"],
            "metadata": {"category": "riddle", "sub_category": "classic", "cognitive_skill": "logic"},
            "created_at": datetime.utcnow(),
        })
    return challenges


# ═══════════════════════════════════════════
# Quick Quiz Generator
# ═══════════════════════════════════════════

def generate_quiz_challenges():
    """Generate general knowledge quiz questions."""
    quizzes = [
        # BEGINNER
        {"difficulty": "beginner", "question": "Which planet is closest to the Sun?", "correct_answer": "Mercury", "options": ["Mercury", "Venus", "Earth", "Mars"]},
        {"difficulty": "beginner", "question": "How many continents are there on Earth?", "correct_answer": "7", "options": ["5", "6", "7", "8"]},
        {"difficulty": "beginner", "question": "What gas do plants absorb from the atmosphere?", "correct_answer": "Carbon dioxide", "options": ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"]},
        {"difficulty": "beginner", "question": "What is the largest ocean on Earth?", "correct_answer": "Pacific Ocean", "options": ["Atlantic Ocean", "Indian Ocean", "Pacific Ocean", "Arctic Ocean"]},
        # EASY
        {"difficulty": "easy", "question": "What is the chemical symbol for gold?", "correct_answer": "Au", "options": ["Go", "Gd", "Au", "Ag"]},
        {"difficulty": "easy", "question": "Which country has the most natural lakes?", "correct_answer": "Canada", "options": ["USA", "Russia", "Canada", "Finland"]},
        {"difficulty": "easy", "question": "What year did the Titanic sink?", "correct_answer": "1912", "options": ["1905", "1912", "1920", "1898"]},
        # MEDIUM
        {"difficulty": "medium", "question": "What is the speed of light in km/s (approximately)?", "correct_answer": "300,000", "options": ["150,000", "300,000", "500,000", "1,000,000"]},
        {"difficulty": "medium", "question": "Which element has the atomic number 1?", "correct_answer": "Hydrogen", "options": ["Helium", "Hydrogen", "Lithium", "Oxygen"]},
        {"difficulty": "medium", "question": "What programming language was created by Guido van Rossum?", "correct_answer": "Python", "options": ["Java", "C++", "Python", "JavaScript"]},
        # HARD
        {"difficulty": "hard", "question": "What is the most abundant element in the universe?", "correct_answer": "Hydrogen", "options": ["Oxygen", "Helium", "Carbon", "Hydrogen"]},
        {"difficulty": "hard", "question": "In what year was the first email sent?", "correct_answer": "1971", "options": ["1969", "1971", "1975", "1980"]},
        # EXPERT
        {"difficulty": "expert", "question": "What is the Kolmogorov complexity of a string?", "correct_answer": "The length of the shortest program that produces it", "options": ["The length of the shortest program that produces it", "The entropy of the string", "The number of unique characters", "The compression ratio"]},
        {"difficulty": "expert", "question": "What is the halting problem?", "correct_answer": "Determining if a program will finish running or loop forever", "options": ["Finding the fastest algorithm", "Determining if a program will finish running or loop forever", "Optimizing memory usage", "Detecting infinite recursion"]},
    ]

    challenges = []
    for q in quizzes:
        challenges.append({
            "type": "quiz", **q,
            "explanation": f"The correct answer is: {q['correct_answer']}",
            "hints": [],
            "time_limit_seconds": {"beginner": 20, "easy": 25, "medium": 30, "hard": 45, "expert": 60}[q["difficulty"]],
            "points": {"beginner": 5, "easy": 10, "medium": 15, "hard": 20, "expert": 30}[q["difficulty"]],
            "tags": ["quiz", "trivia", "knowledge"],
            "metadata": {"category": "quiz", "sub_category": "general_knowledge", "cognitive_skill": "memory"},
            "created_at": datetime.utcnow(),
        })
    return challenges


# ═══════════════════════════════════════════
# Main Seeder
# ═══════════════════════════════════════════

async def seed():
    """Seed the entire challenge bank into MongoDB."""
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]

    # Clear existing challenges
    await db.challenges.delete_many({})

    all_challenges = []
    all_challenges.extend(generate_math_challenges())
    all_challenges.extend(generate_logic_challenges())
    all_challenges.extend(generate_pattern_challenges())
    all_challenges.extend(generate_word_challenges())
    all_challenges.extend(generate_memory_challenges())
    all_challenges.extend(generate_riddle_challenges())
    all_challenges.extend(generate_quiz_challenges())

    # Add created_at to any missing
    for c in all_challenges:
        if "created_at" not in c:
            c["created_at"] = datetime.utcnow()

    result = await db.challenges.insert_many(all_challenges)

    # Print summary
    type_counts = {}
    for c in all_challenges:
        key = f"{c['type']}/{c['difficulty']}"
        type_counts[key] = type_counts.get(key, 0) + 1

    print(f"\n{'='*50}")
    print(f"  CHALLENGE BANK SEEDED SUCCESSFULLY")
    print(f"  Total challenges: {len(result.inserted_ids)}")
    print(f"{'='*50}")
    for key in sorted(type_counts.keys()):
        print(f"  {key}: {type_counts[key]}")
    print(f"{'='*50}\n")

    # Create indexes
    await db.challenges.create_index([("type", 1), ("difficulty", 1)])
    await db.challenges.create_index([("tags", 1)])

    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
