"""System prompt construction for multilingual mirroring."""

from src.agent.harness import BASE_SYSTEM_PROMPT, load_base_system_prompt


def test_base_system_prompt_instructs_language_mirroring() -> None:
    assert "Hindi" in BASE_SYSTEM_PROMPT
    assert "Tamil" in BASE_SYSTEM_PROMPT
    assert "Hinglish" in BASE_SYSTEM_PROMPT
    lowered = BASE_SYSTEM_PROMPT.lower()
    assert "reply in the same language" in lowered or "same language" in lowered


def test_assembled_system_prompt_includes_language_mirroring() -> None:
    prompt = load_base_system_prompt()
    assert "Hindi" in prompt
    assert "Tamil" in prompt
    assert "Hinglish" in prompt
