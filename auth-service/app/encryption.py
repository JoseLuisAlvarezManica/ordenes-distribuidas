from datetime import datetime, timedelta, timezone
import textwrap
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .config import settings
from .models import Users

ALGORITHM = "RS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _wrap_pem(key: str, key_type: str) -> str:
    """Envuelve una llave base64 sin headers en formato PEM completo."""
    # Railway (y otros CIs) pueden almacenar \n como literales; los convertimos primero
    key = key.replace("\\n", "\n").strip()
    if key.startswith("-----"):
        return key
    # Eliminar cualquier espacio/newline del cuerpo base64 para reformatearlo limpiamente
    body_raw = key.replace("\n", "").replace(" ", "")
    body = "\n".join(textwrap.wrap(body_raw, 64))
    return f"-----BEGIN {key_type}-----\n{body}\n-----END {key_type}-----"


_PRIVATE_KEY = _wrap_pem(settings.encryption_key, "PRIVATE KEY")
_PUBLIC_KEY = _wrap_pem(settings.public_key, "PUBLIC KEY")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def authenticate_user(email: str, password: str, db: AsyncSession):
    result = await db.execute(select(Users).where(Users.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def create_access_token(username: str, email: str, role: str, phone_number: str, expires_delta: timedelta) -> str:
    issued_at = datetime.now(timezone.utc)
    expires = issued_at + expires_delta
    payload = {
        "sub": username,
        "email": email,
        "role": role,
        "phone_number": phone_number,
        "iat": issued_at,
        "exp": expires,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, _PRIVATE_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _PUBLIC_KEY, algorithms=[ALGORITHM])

