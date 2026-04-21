FROM python:3.9-slim


WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
COPY uv.lock .

RUN uv sync --no-dev

COPY . .
EXPOSE 8000

CMD ["uv", "run", "main:app", "--host", "0.0.0", "--port", "8000"]
