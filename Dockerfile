FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen

COPY backend/ ./backend/

RUN uv run --no-sync python -c "import backend.app, backend.data_pipeline"

CMD ["uv", "run", "--no-sync", "python", "-m", "backend.app"]
