from functools import wraps
import textwrap

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from jose import jwt, JWTError

from .config import settings

ALGORITHM = "RS256"


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


def must_be_logged_in(route):
    @wraps(route)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if request is None or not isinstance(request, Request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Petición invalida.",
            )

        authorization = request.headers.get("Authorization")
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Formato de encabezado de autorización inválido",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extrae el token de "Bearer <token>"
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Formato de encabezado de autorización inválido",
            )

        token = parts[1]
        try:
            public_key = _wrap_pem(settings.public_key, "PUBLIC KEY")
            payload = jwt.decode(token, public_key, algorithms=[ALGORITHM])
            username = payload.get("sub")
            phone_number = payload.get("phone_number")
            role = payload.get("role")
            request.state.auth_headers = {"Authorization": authorization}
            request.state.username = username
            request.state.phone_number = phone_number
            request.state.role = role
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El token no es válido",
            )

        return await route(*args, **kwargs)

    return wrapper


def must_be_admin(route):
    @wraps(route)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if request is None or not isinstance(request, Request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Petición invalida."
            )

        authorization = request.headers.get("Authorization")
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Formato de encabezado de autorización inválido",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extrae el token de "Bearer <token>"
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Formato de encabezado de autorización inválido",
            )

        token = parts[1]
        try:
            public_key = _wrap_pem(settings.public_key, "PUBLIC KEY")
            payload = jwt.decode(token, public_key, algorithms=[ALGORITHM])
            username = payload.get("sub")
            phone_number = payload.get("phone_number")
            role = payload.get("role")
            request.state.auth_headers = {"Authorization": authorization}
            request.state.username = username
            request.state.phone_number = phone_number
            request.state.role = role
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El token no es válido",
            )
        if role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Fallo de permisos.",
            )
        return await route(*args, **kwargs)

    return wrapper


bearer_scheme = HTTPBearer()
