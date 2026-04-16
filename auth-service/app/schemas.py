from pydantic import BaseModel

class SignUp(BaseModel):
    name: str
    email: str
    phone_number: str
    password: str

class Login(BaseModel):
    email: str
    password: str

class User(BaseModel):
    name: str
    email: str
    phone_number: str
    password: str
    role: str


