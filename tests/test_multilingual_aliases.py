"""Native/transliterated Alias resolution for multilingual grounding."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.inventory import InventoryService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("chini", "Sugar"),
        ("चीनी", "Sugar"),
        ("சர்க்கரை", "Sugar"),
        ("namak", "Tata Salt 1kg"),
        ("नमक", "Tata Salt 1kg"),
        ("உப்பு", "Tata Salt 1kg"),
        ("chawal", "Rice"),
        ("चावल", "Rice"),
        ("அரிசி", "Rice"),
    ],
)
async def test_find_product_resolves_seeded_native_and_transliterated_aliases(
    inventory_session: AsyncSession,
    query: str,
    expected_name: str,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product(query)

    assert result.status == "ok"
    assert result.ambiguous is False
    assert len(result.candidates) == 1
    assert result.candidates[0].name == expected_name


@pytest.mark.asyncio
async def test_find_product_atta_remains_ambiguous(
    inventory_session: AsyncSession,
) -> None:
    service = InventoryService(inventory_session)
    result = await service.find_product("atta")

    assert result.status == "ambiguous"
    assert result.ambiguous is True
    names = {candidate.name for candidate in result.candidates}
    assert "Aashirvaad Atta 5kg" in names
    assert "Loose Atta" in names
