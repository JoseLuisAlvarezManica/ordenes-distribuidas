from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Order(Base):

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer: Mapped[str] = mapped_column(String(255), nullable=False)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:  
        return f"<Order order_id={self.order_id!r} customer={self.customer!r}>"

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),)

    sku: Mapped[str] = mapped_column(String(40), primary_key=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    stock: Mapped[int] = mapped_column(nullable=False, default=0)

