import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
import redis.asyncio as aioredis

from ..db import get_db
from ..encryption import hash_password, authenticate_user, create_access_token, decode_token
from ..config import settings
from ..schemas import User, SignUp, Login
from ..models import Users
from ..redis_client import get_redis


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])

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


@router.post("/login", status_code=status.HTTP_200_OK)
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
    return {"access_token": token, "token_type": "bearer"}

@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh():
    pass

@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    redis: aioredis.Redis = Depends(get_redis),
):
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    exp = payload.get("exp")
    ttl = max(int(exp - datetime.now(timezone.utc).timestamp()), 1)
    await redis.setex(f"blacklist:{token}", ttl, "1")
    logger.info("User logged out: %s", payload.get("email"))
    return {"detail": "Logged out successfully"}

@router.get("/me", status_code=status.HTTP_202_ACCEPTED)
async def refresh():
    pass
