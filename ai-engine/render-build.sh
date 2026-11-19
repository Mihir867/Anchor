#!/usr/bin/env bash
# Render build command (native Python runtime): ./render-build.sh
# Installs Playwright's chromium inside the project so it is still there at runtime
# (Render does not keep ~/.cache between the build and the running service).
set -euo pipefail
cd "$(dirname "$0")"
pip install -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$PWD/.playwright}"
python -m playwright install chromium
