# ── Stage 1: Build React frontend ──
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ── Stage 2: Python API + serve built frontend ──
FROM python:3.11-slim
WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ .

# Copy built frontend into location the API expects
COPY --from=frontend-build /build/dist /app/frontend/dist

# Create DB directory for persistent volume
RUN mkdir -p /data/db

# Set DB path to persistent volume
ENV DB_PATH=/data/db/cyberscreener.db

EXPOSE 8000

# Run scheduler in background + API server
CMD sh -c "python scheduler.py --daemon --interval 7200 & uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
