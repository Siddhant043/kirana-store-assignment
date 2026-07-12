"""Owner Preferences: durable defaults keyed by Telegram user id."""

from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PaymentMode, Preference, Product

DEFAULT_PAYMENT_MODE_KEY = "default_payment_mode"
PREFERRED_PRODUCT_PREFIX = "preferred_product:"
VALID_DEFAULT_PAYMENT_MODES = frozenset({"cash", "upi", "card", "khata"})


@dataclass(frozen=True)
class PreferenceView:
    preference_key: str
    preference_value: str


@dataclass(frozen=True)
class SetPreferenceResult:
    status: Literal["ok"]
    preference_key: str
    preference_value: str


@dataclass(frozen=True)
class GetPreferenceResult:
    status: Literal["ok"]
    preference_key: str
    preference_value: str


@dataclass(frozen=True)
class PreferenceMissingResult:
    status: Literal["refused"]
    reason: Literal["preference_missing"]
    preference_key: str


@dataclass(frozen=True)
class ListPreferencesResult:
    status: Literal["ok"]
    preferences: list[PreferenceView]


@dataclass(frozen=True)
class PreferenceRefusedResult:
    status: Literal["refused"]
    reason: str
    details: dict[str, object]


class PreferencesService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_preference(
        self,
        owner_telegram_user_id: int,
        preference_key: str,
        preference_value: str,
    ) -> SetPreferenceResult | PreferenceRefusedResult:
        key = preference_key.strip()
        value = preference_value.strip()
        if not key:
            return PreferenceRefusedResult(
                status="refused",
                reason="invalid_preference_key",
                details={"preference_key": preference_key},
            )
        if not value:
            return PreferenceRefusedResult(
                status="refused",
                reason="invalid_preference_value",
                details={"preference_value": preference_value},
            )

        validation_error = await self._validate(key, value)
        if validation_error is not None:
            return validation_error

        if key == DEFAULT_PAYMENT_MODE_KEY:
            value = value.lower()

        existing = await self._load(owner_telegram_user_id, key)
        if existing is None:
            self._session.add(
                Preference(
                    owner_telegram_user_id=owner_telegram_user_id,
                    preference_key=key,
                    preference_value=value,
                )
            )
        else:
            existing.preference_value = value

        await self._session.flush()
        return SetPreferenceResult(
            status="ok",
            preference_key=key,
            preference_value=value,
        )

    async def get_preference(
        self,
        owner_telegram_user_id: int,
        preference_key: str,
    ) -> GetPreferenceResult | PreferenceMissingResult:
        key = preference_key.strip()
        row = await self._load(owner_telegram_user_id, key)
        if row is None:
            return PreferenceMissingResult(
                status="refused",
                reason="preference_missing",
                preference_key=key,
            )
        return GetPreferenceResult(
            status="ok",
            preference_key=row.preference_key,
            preference_value=row.preference_value,
        )

    async def list_preferences(
        self,
        owner_telegram_user_id: int,
    ) -> ListPreferencesResult:
        result = await self._session.execute(
            select(Preference)
            .where(Preference.owner_telegram_user_id == owner_telegram_user_id)
            .order_by(Preference.preference_key)
        )
        rows = result.scalars().all()
        return ListPreferencesResult(
            status="ok",
            preferences=[
                PreferenceView(
                    preference_key=row.preference_key,
                    preference_value=row.preference_value,
                )
                for row in rows
            ],
        )

    async def get_default_payment_mode(
        self,
        owner_telegram_user_id: int,
    ) -> PaymentMode | None:
        row = await self._load(owner_telegram_user_id, DEFAULT_PAYMENT_MODE_KEY)
        if row is None:
            return None
        value = row.preference_value.lower()
        if value not in VALID_DEFAULT_PAYMENT_MODES:
            return None
        return cast(PaymentMode, value)

    async def _validate(
        self,
        preference_key: str,
        preference_value: str,
    ) -> PreferenceRefusedResult | None:
        if preference_key == DEFAULT_PAYMENT_MODE_KEY:
            mode = preference_value.lower()
            if mode not in VALID_DEFAULT_PAYMENT_MODES:
                return PreferenceRefusedResult(
                    status="refused",
                    reason="invalid_payment_mode",
                    details={"preference_value": preference_value},
                )
            # Store canonical lowercase Payment Mode.
            return None

        if preference_key.startswith(PREFERRED_PRODUCT_PREFIX):
            query_label = preference_key[len(PREFERRED_PRODUCT_PREFIX) :]
            if not query_label:
                return PreferenceRefusedResult(
                    status="refused",
                    reason="invalid_preference_key",
                    details={"preference_key": preference_key},
                )
            if not preference_value.isdigit():
                return PreferenceRefusedResult(
                    status="refused",
                    reason="invalid_product_id",
                    details={"preference_value": preference_value},
                )
            product_id = int(preference_value)
            product = await self._session.get(Product, product_id)
            if product is None:
                return PreferenceRefusedResult(
                    status="refused",
                    reason="product_not_found",
                    details={"product_id": product_id},
                )
            return None

        return PreferenceRefusedResult(
            status="refused",
            reason="unknown_preference_key",
            details={"preference_key": preference_key},
        )

    async def _load(
        self,
        owner_telegram_user_id: int,
        preference_key: str,
    ) -> Preference | None:
        result = await self._session.execute(
            select(Preference).where(
                Preference.owner_telegram_user_id == owner_telegram_user_id,
                Preference.preference_key == preference_key,
            )
        )
        return result.scalar_one_or_none()


def preferred_product_key(normalized_query: str) -> str:
    return f"{PREFERRED_PRODUCT_PREFIX}{normalized_query.strip().lower()}"


def serialize_set_preference_result(result: SetPreferenceResult) -> dict[str, object]:
    return {
        "status": result.status,
        "preference_key": result.preference_key,
        "preference_value": result.preference_value,
    }


def serialize_get_preference_result(result: GetPreferenceResult) -> dict[str, object]:
    return {
        "status": result.status,
        "preference_key": result.preference_key,
        "preference_value": result.preference_value,
    }


def serialize_preference_missing_result(
    result: PreferenceMissingResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "preference_key": result.preference_key,
    }


def serialize_list_preferences_result(
    result: ListPreferencesResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "preferences": [
            {
                "preference_key": item.preference_key,
                "preference_value": item.preference_value,
            }
            for item in result.preferences
        ],
    }


def serialize_preference_refused_result(
    result: PreferenceRefusedResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "details": result.details,
    }
