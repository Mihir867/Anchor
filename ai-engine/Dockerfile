FROM python:3.12-slim

WORKDIR /app

# System deps for Playwright chromium + Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation libnss3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium browser (fixed path; anchor/crawl.py honours PLAYWRIGHT_BROWSERS_PATH)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium

# Copy application code
COPY . .

# Port (Render injects $PORT)
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
