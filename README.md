# Supermarket Ops Agent

A conversational Telegram agent that runs an Indian kirana store end-to-end. See `CONTEXT.md` for domain vocabulary and `docs/adr/` for architectural decisions.

## Walking skeleton (ticket #2)

Live bot with Telegram long-polling, Postgres persistence, and transport-level idempotency via `processed_updates`.

### Prerequisites

- Docker and Docker Compose
- A Telegram bot token (`@BotFather`)
- An Anthropic API key

### Run locally

```bash
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY

docker compose up --build
```

### Development

```bash
uv sync --group dev
uv run ruff check .
uv run mypy src
uv run pytest
```
