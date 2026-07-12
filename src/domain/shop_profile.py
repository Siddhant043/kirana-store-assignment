"""Shop Profile domain service for invoice header identity and branding."""

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ShopProfile

# Sentinel: omit means "leave existing value unchanged" on update.
_UNSET = object()

ACCENT_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class ShopProfileResult:
    status: Literal["ok"]
    owner_telegram_user_id: int
    shop_name: str
    address: str | None
    gstin: str | None
    logo_url: str | None
    accent_color: str | None


@dataclass(frozen=True)
class ShopProfileMissingResult:
    status: Literal["refused"]
    reason: Literal["shop_profile_missing"]
    owner_telegram_user_id: int


@dataclass(frozen=True)
class ShopProfileRefusedResult:
    status: Literal["refused"]
    reason: str
    details: dict[str, object]


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
        logo_url: object = _UNSET,
        accent_color: object = _UNSET,
    ) -> ShopProfileResult | ShopProfileRefusedResult:
        normalized_name = shop_name.strip()
        if not normalized_name:
            return ShopProfileRefusedResult(
                status="refused",
                reason="invalid_shop_name",
                details={"shop_name": shop_name},
            )
        normalized_address = address.strip() if address else None
        normalized_gstin = gstin.strip() if gstin else None

        branding = self._normalize_branding(logo_url, accent_color)
        if isinstance(branding, ShopProfileRefusedResult):
            return branding
        normalized_logo_url, normalized_accent_color = branding

        profile = await self._load(owner_telegram_user_id)
        if profile is None:
            profile = ShopProfile(
                owner_telegram_user_id=owner_telegram_user_id,
                shop_name=normalized_name,
                address=normalized_address,
                gstin=normalized_gstin,
                logo_url=normalized_logo_url if logo_url is not _UNSET else None,
                accent_color=normalized_accent_color
                if accent_color is not _UNSET
                else None,
            )
            self._session.add(profile)
        else:
            profile.shop_name = normalized_name
            profile.address = normalized_address
            profile.gstin = normalized_gstin
            if logo_url is not _UNSET:
                profile.logo_url = normalized_logo_url
            if accent_color is not _UNSET:
                profile.accent_color = normalized_accent_color

        await self._session.flush()
        return self._to_result(profile)

    def _normalize_branding(
        self,
        logo_url: object,
        accent_color: object,
    ) -> tuple[str | None, str | None] | ShopProfileRefusedResult:
        normalized_logo: str | None = None
        if logo_url is not _UNSET:
            if logo_url is None:
                normalized_logo = None
            else:
                stripped = str(logo_url).strip()
                normalized_logo = stripped or None

        normalized_accent: str | None = None
        if accent_color is not _UNSET:
            if accent_color is None:
                normalized_accent = None
            else:
                stripped_color = str(accent_color).strip()
                if not stripped_color:
                    normalized_accent = None
                elif not ACCENT_COLOR_PATTERN.fullmatch(stripped_color):
                    return ShopProfileRefusedResult(
                        status="refused",
                        reason="invalid_accent_color",
                        details={"accent_color": stripped_color},
                    )
                else:
                    normalized_accent = stripped_color.upper()

        return normalized_logo, normalized_accent

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
            logo_url=profile.logo_url,
            accent_color=profile.accent_color,
        )


def serialize_shop_profile_result(result: ShopProfileResult) -> dict[str, object]:
    return {
        "status": result.status,
        "owner_telegram_user_id": result.owner_telegram_user_id,
        "shop_name": result.shop_name,
        "address": result.address,
        "gstin": result.gstin,
        "logo_url": result.logo_url,
        "accent_color": result.accent_color,
    }


def serialize_shop_profile_missing_result(
    result: ShopProfileMissingResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "owner_telegram_user_id": result.owner_telegram_user_id,
    }


def serialize_shop_profile_refused_result(
    result: ShopProfileRefusedResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "details": result.details,
    }
