"""Shop Profile domain service for invoice header identity."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ShopProfile


@dataclass(frozen=True)
class ShopProfileResult:
    status: Literal["ok"]
    owner_telegram_user_id: int
    shop_name: str
    address: str | None
    gstin: str | None


@dataclass(frozen=True)
class ShopProfileMissingResult:
    status: Literal["refused"]
    reason: Literal["shop_profile_missing"]
    owner_telegram_user_id: int


class ShopProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_shop_profile(
        self,
        owner_telegram_user_id: int,
    ) -> ShopProfileResult | ShopProfileMissingResult:
        profile = await self._load(owner_telegram_user_id)
        if profile is None:
            return ShopProfileMissingResult(
                status="refused",
                reason="shop_profile_missing",
                owner_telegram_user_id=owner_telegram_user_id,
            )
        return self._to_result(profile)

    async def set_shop_profile(
        self,
        owner_telegram_user_id: int,
        *,
        shop_name: str,
        address: str | None = None,
        gstin: str | None = None,
    ) -> ShopProfileResult:
        normalized_name = shop_name.strip()
        normalized_address = address.strip() if address else None
        normalized_gstin = gstin.strip() if gstin else None

        profile = await self._load(owner_telegram_user_id)
        if profile is None:
            profile = ShopProfile(
                owner_telegram_user_id=owner_telegram_user_id,
                shop_name=normalized_name,
                address=normalized_address,
                gstin=normalized_gstin,
            )
            self._session.add(profile)
        else:
            profile.shop_name = normalized_name
            profile.address = normalized_address
            profile.gstin = normalized_gstin

        await self._session.flush()
        return self._to_result(profile)

    async def _load(self, owner_telegram_user_id: int) -> ShopProfile | None:
        result = await self._session.execute(
            select(ShopProfile).where(
                ShopProfile.owner_telegram_user_id == owner_telegram_user_id
            )
        )
        return result.scalar_one_or_none()

    def _to_result(self, profile: ShopProfile) -> ShopProfileResult:
        return ShopProfileResult(
            status="ok",
            owner_telegram_user_id=profile.owner_telegram_user_id,
            shop_name=profile.shop_name,
            address=profile.address,
            gstin=profile.gstin,
        )


def serialize_shop_profile_result(result: ShopProfileResult) -> dict[str, object]:
    return {
        "status": result.status,
        "owner_telegram_user_id": result.owner_telegram_user_id,
        "shop_name": result.shop_name,
        "address": result.address,
        "gstin": result.gstin,
    }


def serialize_shop_profile_missing_result(
    result: ShopProfileMissingResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "owner_telegram_user_id": result.owner_telegram_user_id,
    }
