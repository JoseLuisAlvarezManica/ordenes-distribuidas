from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Users(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(150), nullable=False)
    email : Mapped[str] = mapped_column(String(150), nullable=False, primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(16))
    password: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    
