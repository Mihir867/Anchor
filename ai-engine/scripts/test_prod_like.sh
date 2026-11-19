#!/usr/bin/env bash
# Run the real-browser crawl tests inside the production image, with production's limits:
# 512 MB RAM, no swap, half a CPU, and the Linux Chromium flags from anchor/crawl.py.
#
#   scripts/test_prod_like.sh                      # hostile local test site (deterministic)
#   scripts/test_prod_like.sh https://zendesk.com  # ...then also a live crawl of that URL
#
# Env: ANCHOR_TEST_MEMORY (default 512m), ANCHOR_TEST_CPUS (default 0.5).
set -euo pipefail
cd "$(dirname "$0")/.."
MEM="${ANCHOR_TEST_MEMORY:-512m}"
CPUS="${ANCHOR_TEST_CPUS:-0.5}"
IMAGE=anchor-engine:prod-like

docker build -q -t "$IMAGE" . >/dev/null
# tests/ is in .dockerignore (not shipped), so mount it read-only.
LIMITS=(--rm --memory="$MEM" --memory-swap="$MEM" --cpus="$CPUS" -v "$PWD/tests:/app/tests:ro"
        -e PYTHONDONTWRITEBYTECODE=1)

echo "== hostile local site, $MEM / $CPUS CPU"
docker run "${LIMITS[@]}" "$IMAGE" python -m pytest -p no:cacheprovider -m browser -v tests/

if [[ $# -gt 0 ]]; then
  echo "== live crawl of $1, $MEM / $CPUS CPU"
  docker run "${LIMITS[@]}" "$IMAGE" python scripts/crawl_smoke.py "$1"
fi
