"""Anchor AI Engine: evidence-grounded brand content, refined with Harness².

Flow:  prepare (crawl -> extract -> research -> classify)  ->  TaskPack
       generate (executor; reads the harness tree)          ->  posts.md + trajectory
       refine (Harness² Propose-Probe-Compose over the tree) ->  best rollout
       finalize (render posters + publish)                  ->  runs/<run>/output/
"""

import sys as _sys

if _sys.version_info < (3, 12):  # Harness² requires 3.12; older envs also tend to miss brotli
    raise ImportError(
        f"Anchor needs Python >= 3.12 (this is {_sys.version.split()[0]} at {_sys.executable}). "
        "Run it with the project environment: .venv/bin/python run.py <url>  "
        "(create it with: uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt)"
    )

import importlib.util as _ilu

_REQUIRED = {"harness2": "harness2", "brotli": "brotli", "yaml": "pyyaml", "playwright": "playwright",
             "httpx": "httpx", "fontTools": "fonttools", "bs4": "beautifulsoup4", "PIL": "pillow",
             "dotenv": "python-dotenv", "pydantic": "pydantic"}
_missing = [pkg for mod, pkg in _REQUIRED.items() if _ilu.find_spec(mod) is None]
if _missing:
    raise ImportError(
        f"Missing packages in {_sys.executable}: {', '.join(_missing)}. Install them with: "
        f"uv pip install --python {_sys.executable} -r requirements.txt"
    )
