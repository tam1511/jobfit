FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JOBFIT_DATA_DIR=/data \
    JOBFIT_FRONTEND_DIR=/app/frontend/out \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

WORKDIR /app

# OS packages: dumb-init so browser subprocess zombies get reaped under
# uvicorn (PID 1), and the Chromium runtime deps Playwright needs.
RUN apt-get update && apt-get install --no-install-recommends -y \
        dumb-init \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpangocairo-1.0-0 \
        libpango-1.0-0 \
        libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt
RUN playwright install chromium

COPY backend/ ./backend/
COPY rubric.json ./rubric.json
COPY --from=frontend /build/out ./frontend/out

RUN mkdir -p ${JOBFIT_DATA_DIR}
VOLUME ["/data"]

EXPOSE 8000

ENTRYPOINT ["dumb-init", "--"]
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
