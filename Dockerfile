# 필수 조건 2 — 채점자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY mcp_server/ ./mcp_server/
COPY docs/domains/illustration-reference/term-cards/ ./term-cards/
COPY prompts/uhkegryo-interpreter-v0.md /app/prompts/uhkegryo-interpreter-v0.md
COPY prompts/uhkegryo-interpreter-v1.md /app/prompts/uhkegryo-interpreter-v1.md
COPY prompts/uhkegryo-interpreter-v4.md /app/prompts/uhkegryo-interpreter-v4.md
COPY skills/structured-output/SKILL.md /app/skills/structured-output/SKILL.md

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
