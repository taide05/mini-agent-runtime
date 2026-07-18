FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy psycopg2-binary alembic redis httpx pydantic pydantic-settings python-dotenv sse-starlette

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
