# Supermarket Ops Agent

A conversational Telegram agent that runs an Indian kirana store end-to-end, built on the Claude Agent SDK (Python). See `CONTEXT.md` for the domain glossary and `docs/adr/` for architectural decisions.

## Agent skills

### Issue tracker

Issues live as GitHub issues on `Siddhant043/kirana-store-assignment`, driven via the `gh` CLI. External PRs are **not** a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles map to identically-named GitHub labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Coding standards

Python and SQL conventions, hard rules, and planned tooling. See [`docs/coding-standards.md`](docs/coding-standards.md).
