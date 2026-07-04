"""
Challenge Pydantic schemas (for MongoDB documents).
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ChallengeResponse(BaseModel):
    id: str
    type: str
    difficulty: str
    question: str
    options: List[str] = []
    time_limit_seconds: int = 60
    points: int = 10
    hints: List[str] = []
    metadata: Dict[str, Any] = {}


class ChallengeSubmit(BaseModel):
    challenge_id: str
    answer: str
    time_taken_seconds: float
    alarm_event_id: Optional[str] = None


class ChallengeResult(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: Optional[str] = None
    points_earned: int = 0
    time_taken_seconds: float


class ChallengeStatsResponse(BaseModel):
    total_attempts: int
    correct_answers: int
    accuracy_percentage: float
    avg_response_time: float
    by_type: Dict[str, Dict[str, Any]] = {}
    by_difficulty: Dict[str, Dict[str, Any]] = {}


class ChallengeHistoryItem(BaseModel):
    challenge_id: str
    type: str
    difficulty: str
    question: str
    answer_given: str
    is_correct: bool
    time_taken_seconds: float
    created_at: datetime
