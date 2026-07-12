"""Khata domain logic: Customer resolution, charges, and payments."""

from dataclasses import asdict, dataclass
from typing import Literal

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Customer, KhataEntry

FindCustomerStatus = Literal["ok", "ambiguous", "refused"]
MIN_MATCH_SCORE = 0.25
AMBIGUITY_SCORE_DELTA = 0.08


@dataclass(frozen=True)
class CustomerCandidate:
    customer_id: int
    name: str
    phone: str | None
    match_score: float


@dataclass(frozen=True)
class FindOrCreateCustomerResult:
    status: FindCustomerStatus
    customer_id: int | None
    candidates: list[CustomerCandidate]
    ambiguous: bool


@dataclass(frozen=True)
class RequiresConfirmationResult:
    status: Literal["requires_confirmation"]
    reason: Literal["new_customer", "overpayment"]
    name: str | None = None
    phone: str | None = None
    customer_id: int | None = None
    balance_paise: int | None = None
    payment_paise: int | None = None


@dataclass(frozen=True)
class KhataMutationResult:
    status: Literal["ok"]
    customer_id: int
    khata_entry_id: int
    balance_paise: int


@dataclass(frozen=True)
class KhataBalanceResult:
    status: Literal["ok"]
    customer_id: int
    name: str
    balance_paise: int


@dataclass(frozen=True)
class RefusedResult:
    status: Literal["refused"]
    reason: str
    details: dict[str, object]


class CustomerNotFoundError(Exception):
    pass


FIND_CUSTOMER_SQL = text(
    """
    SELECT
        c.customer_id,
        c.name,
        c.phone,
        GREATEST(
            similarity(lower(c.name), lower(:query)),
            CASE
                WHEN :phone_filter <> '' AND c.phone = :phone_filter THEN 1.0
                ELSE 0.0
            END
        ) AS match_score
    FROM customers c
    WHERE
        similarity(lower(c.name), lower(:query)) >= :min_score
        OR (:phone_filter <> '' AND c.phone = :phone_filter)
    ORDER BY match_score DESC, c.name ASC
    """
)


class KhataService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_or_create_customer(
        self,
        name: str,
        phone: str | None = None,
        *,
        confirm_create: bool = False,
    ) -> FindOrCreateCustomerResult | RequiresConfirmationResult | RefusedResult:
        normalized_name = name.strip()
        if not normalized_name:
            return RefusedResult(
                status="refused",
                reason="invalid_name",
                details={},
            )

        normalized_phone = phone.strip() if phone else None
        candidates = await self._find_customer_candidates(
            normalized_name,
            normalized_phone,
        )

        if not candidates:
            if not confirm_create:
                return RequiresConfirmationResult(
                    status="requires_confirmation",
                    reason="new_customer",
                    name=normalized_name,
                    phone=normalized_phone,
                )
            customer = Customer(name=normalized_name, phone=normalized_phone)
            self._session.add(customer)
            await self._session.flush()
            return FindOrCreateCustomerResult(
                status="ok",
                customer_id=customer.customer_id,
                candidates=[],
                ambiguous=False,
            )

        ambiguous = _is_ambiguous(candidates)
        if ambiguous:
            return FindOrCreateCustomerResult(
                status="ambiguous",
                customer_id=None,
                candidates=candidates,
                ambiguous=True,
            )

        top_candidate = candidates[0]
        return FindOrCreateCustomerResult(
            status="ok",
            customer_id=top_candidate.customer_id,
            candidates=candidates,
            ambiguous=False,
        )

    async def add_khata_charge(
        self,
        customer_id: int,
        amount_paise: int,
    ) -> KhataMutationResult | RefusedResult:
        if amount_paise <= 0:
            return RefusedResult(
                status="refused",
                reason="invalid_amount",
                details={"amount_paise": amount_paise},
            )

        customer = await lock_customer(self._session, customer_id)
        entry = KhataEntry(
            customer_id=customer.customer_id,
            entry_type="charge",
            amount_paise=amount_paise,
            bill_id=None,
        )
        self._session.add(entry)
        await self._session.flush()
        balance_paise = await self._balance_for_customer(customer_id)
        return KhataMutationResult(
            status="ok",
            customer_id=customer_id,
            khata_entry_id=entry.khata_entry_id,
            balance_paise=balance_paise,
        )

    async def record_payment(
        self,
        customer_id: int,
        amount_paise: int,
        *,
        confirm_overpayment: bool = False,
    ) -> KhataMutationResult | RequiresConfirmationResult | RefusedResult:
        if amount_paise <= 0:
            return RefusedResult(
                status="refused",
                reason="invalid_amount",
                details={"amount_paise": amount_paise},
            )

        customer = await self._get_customer(customer_id)
        if customer is None:
            return RefusedResult(
                status="refused",
                reason="khata_not_found",
                details={"customer_id": customer_id},
            )

        locked_customer = await lock_customer(self._session, customer_id)
        balance_paise = await self._balance_for_customer(customer_id)
        if amount_paise > balance_paise and not confirm_overpayment:
            return RequiresConfirmationResult(
                status="requires_confirmation",
                reason="overpayment",
                customer_id=customer_id,
                name=locked_customer.name,
                balance_paise=balance_paise,
                payment_paise=amount_paise,
            )

        entry = KhataEntry(
            customer_id=customer_id,
            entry_type="payment",
            amount_paise=amount_paise,
            bill_id=None,
        )
        self._session.add(entry)
        await self._session.flush()
        new_balance = await self._balance_for_customer(customer_id)
        return KhataMutationResult(
            status="ok",
            customer_id=customer_id,
            khata_entry_id=entry.khata_entry_id,
            balance_paise=new_balance,
        )

    async def get_khata_balance(
        self,
        customer_id: int,
    ) -> KhataBalanceResult | RefusedResult:
        customer = await self._get_customer(customer_id)
        if customer is None:
            return RefusedResult(
                status="refused",
                reason="khata_not_found",
                details={"customer_id": customer_id},
            )

        balance_paise = await self._balance_for_customer(customer_id)
        return KhataBalanceResult(
            status="ok",
            customer_id=customer_id,
            name=customer.name,
            balance_paise=balance_paise,
        )

    async def append_bill_charge(
        self,
        customer_id: int,
        bill_id: int,
        amount_paise: int,
    ) -> KhataEntry:
        entry = KhataEntry(
            customer_id=customer_id,
            entry_type="charge",
            amount_paise=amount_paise,
            bill_id=bill_id,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def _find_customer_candidates(
        self,
        query: str,
        phone: str | None,
    ) -> list[CustomerCandidate]:
        result = await self._session.execute(
            FIND_CUSTOMER_SQL,
            {
                "query": query,
                "phone_filter": phone or "",
                "min_score": MIN_MATCH_SCORE,
            },
        )
        rows = result.mappings().all()
        return [
            CustomerCandidate(
                customer_id=row["customer_id"],
                name=row["name"],
                phone=row["phone"],
                match_score=float(row["match_score"]),
            )
            for row in rows
        ]

    async def _balance_for_customer(self, customer_id: int) -> int:
        signed_amount = case(
            (KhataEntry.entry_type == "charge", KhataEntry.amount_paise),
            else_=-KhataEntry.amount_paise,
        )
        result = await self._session.execute(
            select(func.coalesce(func.sum(signed_amount), 0)).where(
                KhataEntry.customer_id == customer_id
            )
        )
        balance = result.scalar_one()
        return int(balance)

    async def _get_customer(self, customer_id: int) -> Customer | None:
        result = await self._session.execute(
            select(Customer).where(Customer.customer_id == customer_id)
        )
        return result.scalar_one_or_none()


async def lock_customer(session: AsyncSession, customer_id: int) -> Customer:
    result = await session.execute(
        select(Customer).where(Customer.customer_id == customer_id).with_for_update()
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise CustomerNotFoundError(f"customer_id={customer_id} not found")
    return customer


def _is_ambiguous(candidates: list[CustomerCandidate]) -> bool:
    if len(candidates) < 2:
        return False
    top_score = candidates[0].match_score
    second_score = candidates[1].match_score
    return abs(top_score - second_score) <= AMBIGUITY_SCORE_DELTA


def serialize_find_or_create_customer_result(
    result: FindOrCreateCustomerResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "customer_id": result.customer_id,
        "ambiguous": result.ambiguous,
        "candidates": [asdict(candidate) for candidate in result.candidates],
    }


def serialize_requires_confirmation_result(
    result: RequiresConfirmationResult,
) -> dict[str, object]:
    return asdict(result)


def serialize_khata_mutation_result(
    result: KhataMutationResult,
) -> dict[str, object]:
    return asdict(result)


def serialize_khata_balance_result(result: KhataBalanceResult) -> dict[str, object]:
    return asdict(result)


def serialize_refused_result(result: RefusedResult) -> dict[str, object]:
    return asdict(result)
