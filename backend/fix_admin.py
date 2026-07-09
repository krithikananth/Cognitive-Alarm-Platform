from app.models import user, profile, alarm
from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.utils.hashing import verify_password, get_password_hash

db = SessionLocal()
try:
    user = db.query(User).filter(User.email == '23102107@rmd.ac.in').first()
    if user:
        print(f"User before update: role={user.role}, active={user.is_active}")
        user.hashed_password = get_password_hash("Admin@123")
        user.role = UserRole.ADMIN
        db.commit()
        db.refresh(user)
        is_valid = verify_password("Admin@123", user.hashed_password)
        print(f"Update successful! Valid password? {is_valid}")
        print(f"User after update: role={user.role}")
    else:
        print("User NOT found. Creating...")
        admin = User(
            email='23102107@rmd.ac.in',
            username='admin_icap',
            hashed_password=get_password_hash('Admin@123'),
            full_name='ICAP Administrator',
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        db.flush()
        from app.models.profile import UserProfile, DifficultyPreference
        admin_profile = UserProfile(
            user_id=admin.id,
            sleep_duration_hours=8.0,
            timezone='Asia/Kolkata',
            difficulty_preference=DifficultyPreference.MEDIUM,
        )
        db.add(admin_profile)
        db.commit()
        print("Admin user created successfully.")
except Exception as e:
    print('Error:', e)
finally:
    db.close()
