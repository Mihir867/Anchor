# Debian 12 (bookworm): an OS Playwright supports, so `--with-deps` installs the right libraries.
# Plain python:3.12-slim follows the newest Debian, which Playwright may not support yet.
FROM python:3.12-slim-bookworm

WORKDIR /app

# git for git-based pip requirements; libatomic1 for the Playwright driver itself. Chromium's own
# libraries come from `--with-deps` below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates fonts-liberation libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium browser (fixed path; anchor/crawl.py honours PLAYWRIGHT_BROWSERS_PATH)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY scripts/check_browser.py /tmp/check_browser.py
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && python /tmp/check_browser.py

# Copy application code
COPY . .

# Port (Render injects $PORT)
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
