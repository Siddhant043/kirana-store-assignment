"""Cross-session Preferences and standing-memory tests against Postgres."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.harness import ClaudeAgentHarness, render_standing_memory
from src.db.models import Product
from src.domain.billing import BillingService, FinalizeBillResult, RefusedResult
from src.domain.inventory import InventoryService
from src.domain.invoice import InvoiceService
from src.domain.preferences import (
    DEFAULT_PAYMENT_MODE_KEY,
    GetPreferenceResult,
    PreferencesService,
    preferred_product_key,
)
from src.domain.shop_profile import ShopProfileResult, ShopProfileService

OWNER_ID = 8801
CHAT_ID = 8801


async def _find_product_id(session: AsyncSession, query: str) -> int:
    service = InventoryService(session)
    result = await service.find_product(query)
    assert result.candidates
    return result.candidates[0].product_id


async def _set_product_quantity(
    session: AsyncSession,
    product_id: int,
    quantity: Decimal,
) -> None:
    product = await session.get(Product, product_id)
    assert product is not None
    product.quantity = quantity
    await session.flush()


@pytest.mark.asyncio
async def test_set_preference_persists_default_payment_mode(
    inventory_session: AsyncSession,
) -> None:
    service = PreferencesService(inventory_session)
    set_result = await service.set_preference(
        OWNER_ID,
        DEFAULT_PAYMENT_MODE_KEY,
        "upi",
    )
    assert set_result.status == "ok"
    await inventory_session.flush()

    reread = PreferencesService(inventory_session)
    mode = await reread.get_default_payment_mode(OWNER_ID)
    assert mode == "upi"

    listed = await reread.list_preferences(OWNER_ID)
    assert any(
        item.preference_key == DEFAULT_PAYMENT_MODE_KEY
        and item.preference_value == "upi"
        for item in listed.preferences
    )


@pytest.mark.asyncio
async def test_set_preferred_product_atta_persists_product_id(
    inventory_session: AsyncSession,
) -> None:
    inventory = InventoryService(inventory_session)
    find_result = await inventory.find_product("atta")
    assert find_result.candidates
    atta_id = next(
        candidate.product_id
        for candidate in find_result.candidates
        if "Aashirvaad" in candidate.name
    )

    service = PreferencesService(inventory_session)
    key = preferred_product_key("atta")
    result = await service.set_preference(OWNER_ID, key, str(atta_id))
    assert result.status == "ok"
    await inventory_session.flush()

    got = await service.get_preference(OWNER_ID, key)
    assert isinstance(got, GetPreferenceResult)
    assert got.preference_value == str(atta_id)


@pytest.mark.asyncio
async def test_shop_profile_matches_invoice_header_source(
    inventory_session: AsyncSession,
) -> None:
    shop = ShopProfileService(inventory_session)
    await shop.set_shop_profile(
        OWNER_ID,
        shop_name="Memory Kirana",
        address="1 Preference Lane",
        gstin="27BBBBB1111B1Z5",
    )
    await inventory_session.flush()

    profile = await shop.get_shop_profile(OWNER_ID)
    assert isinstance(profile, ShopProfileResult)

    # InvoiceService loads Shop Profile from the same table for PDF headers.
    invoice_shop = await ShopProfileService(inventory_session).get_shop_profile(
        OWNER_ID
    )
    assert isinstance(invoice_shop, ShopProfileResult)
    assert invoice_shop.shop_name == "Memory Kirana"
    assert invoice_shop.gstin == "27BBBBB1111B1Z5"
    assert invoice_shop.shop_name == profile.shop_name
    assert invoice_shop.gstin == profile.gstin
    # Guard: InvoiceService still wires ShopProfileService (same source).
    assert hasattr(InvoiceService(inventory_session), "generate_invoice_pdf")


@pytest.mark.asyncio
async def test_finalize_uses_stored_default_payment_mode_when_omitted(
    inventory_session: AsyncSession,
) -> None:
    sugar_id = await _find_product_id(inventory_session, "sugar")
    await _set_product_quantity(inventory_session, sugar_id, Decimal("10"))

    prefs = PreferencesService(inventory_session)
    await prefs.set_preference(OWNER_ID, DEFAULT_PAYMENT_MODE_KEY, "upi")

    billing = BillingService(inventory_session, chat_id=CHAT_ID)
    await billing.open_draft_bill()
    await billing.add_line(sugar_id, Decimal("1"))
    result = await billing.finalize_bill(
        None,
        owner_telegram_user_id=OWNER_ID,
    )
    assert isinstance(result, FinalizeBillResult)
    assert result.payment_mode == "upi"


@pytest.mark.asyncio
async def test_finalize_refuses_when_payment_mode_omitted_and_no_default(
    inventory_session: AsyncSession,
) -> None:
    sugar_id = await _find_product_id(inventory_session, "sugar")
    await _set_product_quantity(inventory_session, sugar_id, Decimal("10"))

    billing = BillingService(inventory_session, chat_id=CHAT_ID + 2)
    await billing.open_draft_bill()
    await billing.add_line(sugar_id, Decimal("1"))
    result = await billing.finalize_bill(
        None,
        owner_telegram_user_id=OWNER_ID + 99,
    )
    assert isinstance(result, RefusedResult)
    assert result.reason == "payment_mode_required"


@pytest.mark.asyncio
async def test_explicit_cash_overrides_default_without_mutating_preference(
    inventory_session: AsyncSession,
) -> None:
    sugar_id = await _find_product_id(inventory_session, "sugar")
    await _set_product_quantity(inventory_session, sugar_id, Decimal("20"))

    prefs = PreferencesService(inventory_session)
    await prefs.set_preference(OWNER_ID, DEFAULT_PAYMENT_MODE_KEY, "upi")

    billing = BillingService(inventory_session, chat_id=CHAT_ID + 1)
    await billing.open_draft_bill()
    await billing.add_line(sugar_id, Decimal("1"))
    cash_result = await billing.finalize_bill(
        "cash",
        owner_telegram_user_id=OWNER_ID,
    )
    assert isinstance(cash_result, FinalizeBillResult)
    assert cash_result.payment_mode == "cash"

    mode_after = await prefs.get_default_payment_mode(OWNER_ID)
    assert mode_after == "upi"

    await billing.open_draft_bill()
    await billing.add_line(sugar_id, Decimal("1"))
    default_result = await billing.finalize_bill(
        None,
        owner_telegram_user_id=OWNER_ID,
    )
    assert isinstance(default_result, FinalizeBillResult)
    assert default_result.payment_mode == "upi"


@pytest.mark.asyncio
async def test_new_clears_session_and_prompt_still_has_preferences(
    inventory_session: AsyncSession,
) -> None:
    prefs = PreferencesService(inventory_session)
    await prefs.set_preference(OWNER_ID, DEFAULT_PAYMENT_MODE_KEY, "upi")
    await inventory_session.flush()

    class _SessionScope:
        async def __aenter__(self) -> AsyncSession:
            return inventory_session

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _SessionFactory:
        def __call__(self) -> _SessionScope:
            return _SessionScope()

    harness = ClaudeAgentHarness(
        model_id="test-model",
        anthropic_api_key="test-key",
        session_factory=_SessionFactory(),  # type: ignore[arg-type]
    )
    harness._session_ids[CHAT_ID] = "session-before-new"
    harness.clear_session(CHAT_ID)
    assert CHAT_ID not in harness._session_ids

    prompt = await harness._build_system_prompt(OWNER_ID)
    assert "upi" in prompt
    assert "Default Payment Mode" in prompt
    assert "Standing Preferences" in prompt

    memory = await render_standing_memory(inventory_session, OWNER_ID)
    assert "upi" in memory
