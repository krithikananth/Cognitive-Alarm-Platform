"""
Cognitive Challenge Engine.

Generates and verifies different types of cognitive challenges to wake up users.
"""

import random
from typing import Dict, Any

from fastapi import HTTPException, status
from app.models.alarm import ChallengeType


class ChallengeService:
    """Generates and verifies cognitive challenges for alarms."""

    @staticmethod
    def generate_challenge(challenge_type: ChallengeType) -> Dict[str, Any]:
        """
        Generate a cognitive puzzle payload based on the requested type.
        
        Args:
            challenge_type: The requested category of puzzle.
            
        Returns:
            A dictionary containing the challenge prompt, type, and the correct answer.
        """
        if challenge_type == ChallengeType.RANDOM:
            # Pick a random type that is actually implemented with dynamic logic
            challenge_type = random.choice([
                ChallengeType.MATH, 
                ChallengeType.PATTERN, 
                ChallengeType.MEMORY,
                ChallengeType.RIDDLE
            ])

        if challenge_type == ChallengeType.MATH:
            return ChallengeService._generate_math()
        elif challenge_type == ChallengeType.PATTERN:
            return ChallengeService._generate_pattern()
        elif challenge_type == ChallengeType.MEMORY:
            return ChallengeService._generate_memory()
        elif challenge_type == ChallengeType.RIDDLE:
            return ChallengeService._generate_ai_challenge(challenge_type)
        else:
            # Fallback for Logic, Word Game, Quiz
            return ChallengeService._generate_ai_challenge(challenge_type)

    @staticmethod
    def _generate_ai_challenge(challenge_type: ChallengeType) -> Dict[str, Any]:
        """Generate a challenge dynamically using Google Gemini AI, with fallback to hardcoded logic."""
        from app.core.config import settings
        import json
        
        # If API key is missing, fallback immediately
        if not settings.GEMINI_API_KEY:
            return ChallengeService._fallback_challenge(challenge_type)
            
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # Use gemini-1.5-flash for fast responses
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            prompt = f"""
            Generate a completely original cognitive puzzle of type: {challenge_type.value}.
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
            
            # Clean up markdown formatting if the model accidentally included it
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
                
            data = json.loads(text.strip())
            
            # Validate structure
            if "prompt" not in data or "answer" not in data or "options" not in data:
                raise ValueError("Missing required keys in AI response")
                
            # Ensure options are randomized so answer isn't always at same index
            random.shuffle(data["options"])
                
            return {
                "type": challenge_type.value.upper(),
                "prompt": data["prompt"],
                "answer": str(data["answer"]),
                "options": [str(o) for o in data["options"]]
            }
            
        except Exception as e:
            print(f"⚠️ AI Generation Failed: {e}. Falling back to procedurally generated puzzle.")
            return ChallengeService._fallback_challenge(challenge_type)

    @staticmethod
    def _fallback_challenge(challenge_type: ChallengeType) -> Dict[str, Any]:
        """Fallback to algorithmic generation if AI fails or key is missing."""
        if challenge_type == ChallengeType.RIDDLE:
            return ChallengeService._generate_riddle()
        else:
            return ChallengeService._generate_math()

    @staticmethod
    def _generate_math() -> Dict[str, Any]:
        """Generate a random math equation with varying complexity."""
        complexity = random.choice(["simple", "medium", "hard"])
        
        if complexity == "simple":
            # 2-operand basic arithmetic
            ops = ['+', '-', '*']
            op = random.choice(ops)
            if op == '*':
                a = random.randint(2, 12)
                b = random.randint(2, 9)
            else:
                a = random.randint(15, 99)
                b = random.randint(10, 40)
            if op == '-' and b > a:
                a, b = b, a
            equation = f"{a} {op} {b}"
            answer = str(eval(equation))
            
        elif complexity == "medium":
            # 3-operand arithmetic
            a = random.randint(5, 30)
            b = random.randint(2, 15)
            c = random.randint(1, 10)
            ops = ['+', '-']
            op1 = random.choice(ops)
            op2 = random.choice(ops)
            equation = f"{a} {op1} {b} {op2} {c}"
            answer = str(eval(equation))
            if int(answer) < 0:
                return ChallengeService._generate_math()  # retry for positive answer
                
        else:
            # Parenthesized equation
            a = random.randint(2, 15)
            b = random.randint(2, 10)
            c = random.randint(2, 5)
            style = random.choice(["add_mul", "sub_mul", "mul_add"])
            if style == "add_mul":
                equation = f"({a} + {b}) × {c}"
                answer = str((a + b) * c)
            elif style == "sub_mul":
                if b > a:
                    a, b = b, a
                equation = f"({a} - {b}) × {c}"
                answer = str((a - b) * c)
            else:
                equation = f"{a} × {b} + {c}"
                answer = str(a * b + c)
        
        return {
            "type": "MATH",
            "prompt": f"Solve: {equation} = ?",
            "answer": answer,
            "options": ChallengeService._generate_options(answer)
        }

    @staticmethod
    def _generate_pattern() -> Dict[str, Any]:
        """Generate a number sequence pattern with multiple pattern types."""
        pattern_type = random.choice(["arithmetic", "geometric", "fibonacci", "squares"])
        
        if pattern_type == "arithmetic":
            start = random.randint(2, 20)
            step = random.randint(2, 8)
            seq = [start + (step * i) for i in range(4)]
            answer = str(start + (step * 4))
            
        elif pattern_type == "geometric":
            start = random.randint(2, 5)
            factor = random.choice([2, 3])
            seq = [start * (factor ** i) for i in range(4)]
            answer = str(start * (factor ** 4))
            
        elif pattern_type == "fibonacci":
            a = random.randint(1, 5)
            b = random.randint(1, 5)
            seq = [a, b]
            for _ in range(2):
                seq.append(seq[-1] + seq[-2])
            answer = str(seq[-1] + seq[-2])
            
        else:  # squares
            start_n = random.randint(1, 5)
            seq = [(start_n + i) ** 2 for i in range(4)]
            answer = str((start_n + 4) ** 2)
        
        return {
            "type": "PATTERN",
            "prompt": f"What comes next? {seq[0]}, {seq[1]}, {seq[2]}, {seq[3]}, ...?",
            "answer": answer,
            "options": ChallengeService._generate_options(answer)
        }

    @staticmethod
    def _generate_memory() -> Dict[str, Any]:
        """Generate a memory sequence challenge with variable length."""
        length = random.randint(4, 8)
        sequence = "".join([str(random.randint(0, 9)) for _ in range(length)])
        
        return {
            "type": "MEMORY",
            "prompt": sequence,  # The frontend will flash this and then hide it
            "answer": sequence,
            "options": None  # Memory is typed input, not multiple choice
        }

    @staticmethod
    def _generate_riddle() -> Dict[str, Any]:
        """Generate a random riddle from an expanded bank of 25+ riddles."""
        riddles = [
            {"q": "What has keys but can't open locks?", "a": "Piano", "opts": ["Piano", "Keyboard", "Door", "Map"]},
            {"q": "I have cities, but no houses. I have mountains, but no trees. What am I?", "a": "Map", "opts": ["Map", "Globe", "Atlas", "Painting"]},
            {"q": "What has to be broken before you can use it?", "a": "Egg", "opts": ["Egg", "Glass", "Seal", "Lock"]},
            {"q": "What has hands but can't clap?", "a": "Clock", "opts": ["Clock", "Statue", "Robot", "Puppet"]},
            {"q": "What has a head and a tail but no body?", "a": "Coin", "opts": ["Coin", "Snake", "Arrow", "Pin"]},
            {"q": "What can you catch but not throw?", "a": "Cold", "opts": ["Cold", "Ball", "Fish", "Shadow"]},
            {"q": "What gets wetter the more it dries?", "a": "Towel", "opts": ["Towel", "Sponge", "Paper", "Sand"]},
            {"q": "What can travel around the world while staying in a corner?", "a": "Stamp", "opts": ["Stamp", "Spider", "Shadow", "Wind"]},
            {"q": "What has one eye but can't see?", "a": "Needle", "opts": ["Needle", "Cyclops", "Camera", "Storm"]},
            {"q": "What comes once in a minute, twice in a moment, but never in a thousand years?", "a": "Letter M", "opts": ["Letter M", "Time", "Second", "Hour"]},
            {"q": "What has a neck but no head?", "a": "Bottle", "opts": ["Bottle", "Guitar", "Shirt", "Giraffe"]},
            {"q": "What can run but never walks?", "a": "Water", "opts": ["Water", "Wind", "Time", "Horse"]},
            {"q": "I am not alive, but I grow; I don't have lungs, but I need air. What am I?", "a": "Fire", "opts": ["Fire", "Plant", "Cloud", "Balloon"]},
            {"q": "What is full of holes but still holds water?", "a": "Sponge", "opts": ["Sponge", "Net", "Bucket", "Cloud"]},
            {"q": "What goes up but never comes down?", "a": "Age", "opts": ["Age", "Balloon", "Smoke", "Temperature"]},
            {"q": "What invention lets you look right through a wall?", "a": "Window", "opts": ["Window", "X-ray", "Mirror", "Camera"]},
            {"q": "What has four legs in the morning, two at noon, and three in the evening?", "a": "Human", "opts": ["Human", "Dog", "Cat", "Chair"]},
            {"q": "What begins with T, ends with T, and has T in it?", "a": "Teapot", "opts": ["Teapot", "Toast", "Tent", "Trust"]},
            {"q": "What word is spelled incorrectly in every dictionary?", "a": "Incorrectly", "opts": ["Incorrectly", "Dictionary", "Spelling", "Error"]},
            {"q": "I have teeth but cannot eat. What am I?", "a": "Comb", "opts": ["Comb", "Saw", "Zipper", "Gear"]},
            {"q": "What has legs but doesn't walk?", "a": "Table", "opts": ["Table", "Chair", "Bed", "Desk"]},
            {"q": "What can you hold in your left hand but not your right?", "a": "Right elbow", "opts": ["Right elbow", "Left hand", "Heart", "Breath"]},
            {"q": "What is always in front of you but can't be seen?", "a": "Future", "opts": ["Future", "Air", "Shadow", "Nose"]},
            {"q": "I have branches but no fruit, no trunk, no leaves. What am I?", "a": "Bank", "opts": ["Bank", "Tree", "River", "Family"]},
            {"q": "The more you take, the more you leave behind. What are they?", "a": "Footsteps", "opts": ["Footsteps", "Memories", "Photos", "Breaths"]},
            {"q": "What building has the most stories?", "a": "Library", "opts": ["Library", "Skyscraper", "Hotel", "School"]},
            {"q": "I fly without wings. I cry without eyes. What am I?", "a": "Cloud", "opts": ["Cloud", "Wind", "Ghost", "Onion"]},
            {"q": "What has 13 hearts but no other organs?", "a": "Deck of cards", "opts": ["Deck of cards", "Calendar", "Clock", "Tree"]},
        ]
        chosen = random.choice(riddles)
        
        # Shuffle the options so the correct answer isn't always first
        options = chosen["opts"][:]
        random.shuffle(options)
        
        return {
            "type": "RIDDLE",
            "prompt": chosen["q"],
            "answer": chosen["a"],
            "options": options
        }
        
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

    @staticmethod
    def verify_answer(expected_answer: str, user_answer: str) -> bool:
        """
        Verify if the user's provided answer matches the expected answer.
        Case insensitive and ignores surrounding whitespace.
        """
        if not expected_answer or not user_answer:
            return False
        return expected_answer.strip().lower() == user_answer.strip().lower()
