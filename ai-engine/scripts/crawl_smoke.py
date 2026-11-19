"""Live crawl smoke test: home page + subpages for a real URL, timed, no LLM or storage.

    python scripts/crawl_smoke.py https://www.zendesk.com/in/

Run it through scripts/test_prod_like.sh to get production's memory/CPU limits. Every run uses a
fresh Chromium profile, so nothing a previous visit cached on this machine affects the result.
"""
import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup  # noqa: E402

from anchor import crawl, extract, harness  # noqa: E402
from anchor.config import settings  # noqa: E402
from anchor.prepare import classify, normalize_url  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(url: str) -> int:
    cfg = settings()
    url = normalize_url(url)
    t0 = time.monotonic()
    home = asyncio.run(crawl.crawl_home(url, Path(tempfile.mkdtemp()) / "assets"))
    h = harness.load(cfg.harness_dir)
    text = " ".join([home.tokens.get("title", ""), home.tokens.get("description", ""),
                     extract.clean(BeautifulSoup(home.home.html, "html.parser").get_text(" "))[:6000]])
    industry, _ = classify(h, text, set(), cfg)
    urls = crawl.candidate_urls(home, h.skills[industry].list_meta("crawl_paths"), cfg.max_pages)
    pages = asyncio.run(crawl.crawl_pages(urls, cfg.max_pages, budget=cfg.subpage_budget))
    total = time.monotonic() - t0
    print(f"\nOK  {home.url}: logo={'yes' if home.logo_path else 'no'}, colors={home.tokens.get('ranked_colors')}, "
          f"{len(pages)} subpages, {total:.0f}s total (subpage budget {cfg.subpage_budget:.0f}s)")
    return 0 if total < cfg.subpage_budget + 240 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://www.zendesk.com/in/"))
