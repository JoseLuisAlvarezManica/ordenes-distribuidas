import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
import redis.asyncio as aioredis

from ..db import get_db
from ..encryption import hash_password, authenticate_user, create_access_token, decode_token
from ..config import settings
from ..schemas import SignUp, Login, TokenResponse, MeResponse
from ..models import Users
from ..redis_client import get_redis


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()


def _get_required_claim(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return value


async def _validate_bearer_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    redis: aioredis.Redis = Depends(get_redis),
) -> tuple[dict[str, Any], str]:
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError as exc:
        logger.warning("Token validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    is_revoked = await redis.get(f"blacklist:{token}")
    if is_revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    return payload, token


async def _blacklist_token(token: str, payload: dict[str, Any], redis: aioredis.Redis) -> None:
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    ttl = max(int(exp - datetime.now(timezone.utc).timestamp()), 1)
    await redis.setex(f"blacklist:{token}", ttl, "1")

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignUp, db: AsyncSession = Depends(get_db)):

    logger.info("Signup attempt for email: %s", body.email)

    result = await db.execute(select(Users).where(Users.email == body.email))
    existing = result.scalar_one_or_none()
    
    if existing:
        logger.warning("Signup rejected, email already exists: %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    new_user = Users(
        username=body.name,
        email=body.email,
        phone_number=body.phone_number,
        password=hash_password(body.password),
        role="user",
    )

    db.add(new_user)
    try:
        await db.commit()
    except Exception as exc:
        logger.error("Failed to create user %s: %s", body.email, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create user")
    logger.info("User created successfully: %s", body.email)
    return {"detail": "User created successfully"}


@router.post("/login", status_code=status.HTTP_200_OK, response_model=TokenResponse)
async def login(body: Login, db: AsyncSession = Depends(get_db)):
    logger.info("Login attempt for email: %s", body.email)

    user = await authenticate_user(body.email, body.password, db)
    if not user:
        logger.warning("Login failed for email: %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        username=user.username,
        email=user.email,
        role=user.role,
        phone_number=user.phone_number,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    logger.info("Login successful for email: %s", body.email)
    return TokenResponse(access_token=token)

@router.post("/refresh", status_code=status.HTTP_200_OK, response_model=TokenResponse)
async def refresh(
    token_context: tuple[dict[str, Any], str] = Depends(_validate_bearer_token),
    redis: aioredis.Redis = Depends(get_redis),
):
    payload, token = token_context

    username = _get_required_claim(payload, "sub")
    email = _get_required_claim(payload, "email")
    role = _get_required_claim(payload, "role")
    phone_number = payload.get("phone_number")
    if not isinstance(phone_number, str):
        phone_number = ""

    renewed_token = create_access_token(
        username=username,
        email=email,
        role=role,
        phone_number=phone_number,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    # Invalida el token anterior para evitar sesiones paralelas con el mismo JWT.
    await _blacklist_token(token, payload, redis)
    logger.info("Token refreshed for email: %s; previous token revoked", email)
    return TokenResponse(access_token=renewed_token)

@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    token_context: tuple[dict[str, Any], str] = Depends(_validate_bearer_token),
    redis: aioredis.Redis = Depends(get_redis),
):
    payload, token = token_context

    await _blacklist_token(token, payload, redis)
    logger.info("User logged out: %s", payload.get("email"))
    return {"detail": "Logged out successfully"}

@router.get("/me", status_code=status.HTTP_200_OK, response_model=MeResponse)
async def me(
    token_context: tuple[dict[str, Any], str] = Depends(_validate_bearer_token),
    db: AsyncSession = Depends(get_db),
):
    payload, _ = token_context
    email = _get_required_claim(payload, "email")

    result = await db.execute(select(Users).where(Users.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return MeResponse(
        username=user.username,
        email=user.email,
        phone_number=user.phone_number,
        role=user.role,
    )
