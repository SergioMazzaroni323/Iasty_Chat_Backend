from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PlanType, User
from app.schemas import UserResponse

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        return int(user_id) if user_id else None
    except JWTError:
        return None


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_tier(user: User | None, guest: bool = False) -> str:
    if guest or user is None:
        return "basic"
    if user.plan == PlanType.PLUS:
        return "plus"
    return "free"


def get_token_limit(tier: str) -> int:
    from app.constants import BASIC_TOKEN_LIMIT, FREE_TOKEN_LIMIT, PLUS_TOKEN_LIMIT

    if tier == "plus":
        return PLUS_TOKEN_LIMIT
    if tier == "free":
        return FREE_TOKEN_LIMIT
    return BASIC_TOKEN_LIMIT


def get_allowed_models(tier: str) -> list[str]:
    from app.constants import AVAILABLE_MODELS, BASIC_MODEL

    if tier == "basic":
        return [BASIC_MODEL]
    return [m["id"] for m in AVAILABLE_MODELS]


def user_to_response(user: User | None) -> UserResponse | None:
    if not user:
        return None
    tier = get_tier(user)
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        plan=user.plan.value,
        tier=tier,
        token_limit=get_token_limit(tier),
        is_admin=user.is_admin,
        email_verified=user.email_verified,
    )
