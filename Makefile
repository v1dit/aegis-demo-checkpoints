.PHONY: bootstrap up train eval package-replays demo down test

bootstrap:
	@echo "Checking local prerequisites"
	@command -v uv >/dev/null || (echo "uv is required locally" && exit 1)
	@python3 -c "import sys; assert sys.version_info.major >= 3" \
		|| (echo "Python is required" && exit 1)
	@docker --version >/dev/null || (echo "Docker is required" && exit 1)
	@echo "Installing dependencies"
	uv sync --extra dev

up:
	docker compose -f infra/compose/docker-compose.yml up -d --build

train:
	uv run python -m backend.app.cli train

eval:
	uv run python -m backend.app.cli eval

package-replays:
	uv run python -m backend.app.cli package-replays

demo:
	uv run python -m backend.app.cli demo

down:
	docker compose -f infra/compose/docker-compose.yml down

test:
	uv run pytest
