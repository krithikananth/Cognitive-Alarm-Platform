# Models package - import all models so Alembic can detect them
from app.models.user import User, UserProfile
from app.models.alarm import Alarm, AlarmEvent
from app.models.habit import HabitScore
from app.models.notification import Notification, Recommendation

__all__ = [
    "User", "UserProfile",
    "Alarm", "AlarmEvent",
    "HabitScore",
    "Notification", "Recommendation",
]
