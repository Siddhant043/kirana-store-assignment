"""SQLAlchemy ORM models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

UnitType = Literal["packaged", "loose"]
StockLedgerReason = Literal["stock_in", "sale", "adjustment"]
DraftBillStatus = Literal["open", "finalized"]
PaymentMode = Literal["cash", "upi", "card", "khata"]
KhataEntryType = Literal["charge", "payment"]


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


class DraftBill(Base):
    __tablename__ = "draft_bills"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'finalized')",
            name="ck_draft_bills_status",
        ),
    )

    draft_bill_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="open"
    )
    bill_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bills.bill_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lines: Mapped[list["DraftLine"]] = relationship(back_populates="draft_bill")


class DraftLine(Base):
    __tablename__ = "draft_lines"
    __table_args__ = (
        UniqueConstraint(
            "draft_bill_id",
            "product_id",
            name="uq_draft_lines_draft_product",
        ),
    )

    draft_line_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    draft_bill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("draft_bills.draft_bill_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.product_id"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    draft_bill: Mapped[DraftBill] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        CheckConstraint(
            "payment_mode IN ('cash', 'upi', 'card', 'khata')",
            name="ck_bills_payment_mode",
        ),
    )

    bill_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    draft_bill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("draft_bills.draft_bill_id"),
        nullable=False,
        unique=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    payment_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    subtotal_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    cgst_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    sgst_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    round_off_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    draft_bill: Mapped[DraftBill] = relationship(
        foreign_keys=[draft_bill_id],
    )
    lines: Mapped[list["BillLine"]] = relationship(back_populates="bill")


class BillLine(Base):
    __tablename__ = "bill_lines"

    bill_line_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    bill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bills.bill_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.product_id"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    mrp_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_slab: Mapped[int] = mapped_column(Integer, nullable=False)
    hsn_code: Mapped[str] = mapped_column(String(16), nullable=False)
    line_total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    taxable_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    cgst_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    sgst_paise: Mapped[int] = mapped_column(Integer, nullable=False)

    bill: Mapped[Bill] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class InvoiceCounter(Base):
    __tablename__ = "invoice_counters"

    counter_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    khata_entries: Mapped[list["KhataEntry"]] = relationship(
        back_populates="customer",
    )


class KhataEntry(Base):
    __tablename__ = "khata_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('charge', 'payment')",
            name="ck_khata_entries_entry_type",
        ),
        CheckConstraint(
            "amount_paise > 0",
            name="ck_khata_entries_amount_positive",
        ),
    )

    khata_entry_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
    )
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    bill_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("bills.bill_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    customer: Mapped[Customer] = relationship(back_populates="khata_entries")
    bill: Mapped[Bill | None] = relationship()


class ShopProfile(Base):
    __tablename__ = "shop_profile"

    owner_telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )
    shop_name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    gstin: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Preference(Base):
    __tablename__ = "preferences"

    owner_telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    preference_key: Mapped[str] = mapped_column(Text, primary_key=True)
    preference_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SentJob(Base):
    __tablename__ = "sent_jobs"

    owner_telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_key: Mapped[str] = mapped_column(Text, primary_key=True)
    period_key: Mapped[str] = mapped_column(Text, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
