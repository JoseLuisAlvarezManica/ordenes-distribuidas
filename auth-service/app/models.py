from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Product(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(150), nullable=False)
    email : Mapped[str] = mapped_column(String(150), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(16), primary_key=True)
    password: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    
