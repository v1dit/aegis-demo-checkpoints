# PantherHacks Track A

Backend, simulation, training, replay, and API implementation for the PantherHacks adaptive cyber defense demo.

## Quick Start

```bash
uv sync --extra dev
uv run uvicorn backend.app.main:app --reload --port 8000
```

## Tests

```bash
uv run pytest
```
