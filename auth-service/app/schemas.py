from pydantic import BaseModel, EmailStr


class SignUp(BaseModel):
    name: str
    email: str
    phone_number: str
    password: str


class Login(BaseModel):
    email: str
    password: str


class User(BaseModel):
    username: str
    email: EmailStr
    phone_number: str | None = None
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    username: str
    email: EmailStr
    phone_number: str | None = None
    role: str
