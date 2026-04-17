import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..services.auth_client import AuthClient, get_auth_client
from ..schemas import SignUpRequest, LoginRequest, TokenResponse, MessageResponse, MeResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

auth_dependency = Annotated[AuthClient, Depends(get_auth_client)]


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=MessageResponse)
async def signup(body: SignUpRequest, auth_client: auth_dependency):
    code, data = await auth_client.post("/auth/signup", body.model_dump())
    if code != status.HTTP_201_CREATED:
        raise HTTPException(status_code=code, detail=data)
    return data


@router.post("/login", status_code=status.HTTP_200_OK, response_model=TokenResponse)
async def login(body: LoginRequest, auth_client: auth_dependency):
    code, data = await auth_client.post("/auth/login", body.model_dump())
    if code != status.HTTP_200_OK:
        raise HTTPException(status_code=code, detail=data)
    return data


@router.post("/refresh", status_code=status.HTTP_200_OK, response_model=TokenResponse)
async def refresh(request: Request, auth_client: auth_dependency):
    authorization = request.headers.get("Authorization")
    headers = {"Authorization": authorization} if authorization else {}
    code, data = await auth_client.post("/auth/refresh", {}, headers=headers)
    if code != status.HTTP_200_OK:
        raise HTTPException(status_code=code, detail=data)
    return data


@router.post("/logout", status_code=status.HTTP_200_OK, response_model=MessageResponse)
async def logout(request: Request, auth_client: auth_dependency):
    authorization = request.headers.get("Authorization")
    headers = {"Authorization": authorization} if authorization else {}
    code, data = await auth_client.post("/auth/logout", {}, headers=headers)
    if code != status.HTTP_200_OK:
        raise HTTPException(status_code=code, detail=data)
    return data


@router.get("/me", status_code=status.HTTP_200_OK, response_model=MeResponse)
async def me(request: Request, auth_client: auth_dependency):
    authorization = request.headers.get("Authorization")
    headers = {"Authorization": authorization} if authorization else {}
    code, data = await auth_client.get("/auth/me", headers=headers)
    if code != status.HTTP_200_OK:
        raise HTTPException(status_code=code, detail=data)
    return data
