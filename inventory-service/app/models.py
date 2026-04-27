from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
    )

    sku: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    stock: Mapped[int] = mapped_column(nullable=False, default=0)
