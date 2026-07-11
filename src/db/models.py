"""SQLAlchemy ORM models."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

UnitType = Literal["packaged", "loose"]
StockLedgerReason = Literal["stock_in", "sale", "adjustment"]


class Base(DeclarativeBase):
    pass


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "gst_slab IN (0, 5, 12, 18)",
            name="ck_products_gst_slab",
        ),
        CheckConstraint(
            "unit_type IN ('packaged', 'loose')",
            name="ck_products_unit_type",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    mrp_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_slab: Mapped[int] = mapped_column(Integer, nullable=False)
    hsn_code: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
        server_default="0",
    )
    reorder_level: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    aliases: Mapped[list["Alias"]] = relationship(back_populates="product")
    stock_ledger_entries: Mapped[list["StockLedger"]] = relationship(
        back_populates="product",
    )


class Alias(Base):
    __tablename__ = "aliases"

    alias_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.product_id", ondelete="CASCADE"),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)

    product: Mapped[Product] = relationship(back_populates="aliases")


class StockLedger(Base):
    __tablename__ = "stock_ledger"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('stock_in', 'sale', 'adjustment')",
            name="ck_stock_ledger_reason",
        ),
    )

    ledger_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.product_id", ondelete="CASCADE"),
        nullable=False,
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped[Product] = relationship(back_populates="stock_ledger_entries")
