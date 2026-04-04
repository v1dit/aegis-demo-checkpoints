# PantherHacks Track A

Backend, simulation, training, replay, and API implementation for the PantherHacks adaptive cyber defense demo.

## Quick Start

```bash
uv sync --extra dev
uv run uvicorn backend.app.main:app --reload --port 8000
```

## PPO Training

Training now uses RLlib PPO end-to-end (no simulated trainer fallback).

```bash
uv sync --extra rl --extra dev
uv run python -m backend.app.cli train --fresh-start --seed 1337
```

If `--seed` is omitted, the CLI will generate a random seed per run.

## Tests

```bash
uv run pytest
```
