FROM python:3.11-slim

WORKDIR /workspace
LABEL project=pantherhacks
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-cache-dir .[rl]

CMD ["python", "-m", "backend.app.cli", "train"]
