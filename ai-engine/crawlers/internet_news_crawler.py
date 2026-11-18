"""
Internet News & Public Milestone Crawler
Discovers live recent company milestones, product launches, enterprise deals,
and funding rounds from the open web (Bing News RSS & Google News RSS)
whenever on-site articles are sparse, archive-only, or low-yield.
"""

import json
import logging
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import unquote, urljoin, urlparse
from bs4 import BeautifulSoup
import requests

from .deep_article_crawler import (
    ScrapedArticle,
    clean_text,
    extract_article_body,
    extract_metrics_with_regex,
    extract_published_date,
)

logger = logging.getLogger("internet_news_crawler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def search_bing_news_rss(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """
    Searches Bing News RSS to retrieve direct media links from major publications
    (Moneycontrol, TechCrunch, Economic Times, Bloomberg, Reuters, etc.).
    """
    encoded_q = urllib.parse.quote(query)
    url = f"https://www.bing.com/news/search?q={encoded_q}&format=rss"
    results: List[Dict[str, str]] = []

    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        for item in items[:max_results]:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")
            desc_el = item.find("description")

            title = title_el.text if title_el is not None else ""
            raw_link = link_el.text if link_el is not None else ""
            pub_date = pub_date_el.text if pub_date_el is not None else ""
            desc = desc_el.text if desc_el is not None else ""

            # Extract the actual destination article URL from Bing's redirect link
            direct_url = raw_link
            if "url=" in raw_link:
                try:
                    parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                    if "url" in parsed_qs:
                        direct_url = parsed_qs["url"][0]
                except Exception:
                    pass

            # Clean HTML description
            snippet_text = ""
            if desc:
                soup = BeautifulSoup(desc, "html.parser")
                snippet_text = clean_text(soup.get_text())

            results.append({
                "title": clean_text(title),
                "url": direct_url,
                "pub_date": pub_date,
                "snippet": snippet_text or title,
            })
    except Exception as e:
        logger.warning(f"[INTERNET CRAWLER] Bing News RSS query error for '{query}': {e}")

    return results


def search_google_news_rss(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """Searches Google News RSS for real-time journalistic headlines and sources."""
    encoded_q = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"
    results: List[Dict[str, str]] = []

    try:
        resp = requests.get(rss_url, headers=BROWSER_HEADERS, timeout=10)
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        for item in items[:max_results]:
            title_el = item.find("title")
            pub_date_el = item.find("pubDate")
            source_el = item.find("source")
            desc_el = item.find("description")

            title = title_el.text if title_el is not None else ""
            pub_date = pub_date_el.text if pub_date_el is not None else ""
            source = source_el.text if source_el is not None else ""
            desc = desc_el.text if desc_el is not None else ""

            snippet_text = ""
            if desc:
                soup = BeautifulSoup(desc, "html.parser")
                snippet_text = clean_text(soup.get_text())

            results.append({
                "title": clean_text(title),
                "url": "",
                "source": source,
                "pub_date": pub_date,
                "snippet": snippet_text or title,
            })
    except Exception as e:
        logger.warning(f"[INTERNET CRAWLER] Google News RSS query error for '{query}': {e}")

    return results


def fetch_and_parse_article_url(url: str, fallback_title: str = "") -> Optional[ScrapedArticle]:
    """Downloads and extracts the clean body, quotes, metrics, and date from a web URL."""
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=12)
        if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
            return None

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title = fallback_title
        h1 = soup.find("h1")
        if h1:
            title = clean_text(h1.get_text())
        elif soup.title and not title:
            title = clean_text(soup.title.get_text().split("|")[0].split("-")[0])

        # Date
        pub_date = extract_published_date(soup, html, url)

        # Body, lead, quotes
        lead_p, full_text, quotes = extract_article_body(soup)
        if len(full_text) < 120 and len(lead_p) < 60:
            return None

        # Metrics
        metrics = extract_metrics_with_regex(full_text + " " + title)

        return ScrapedArticle(
            url=url,
            title=title or "Company Milestone",
            published_date=pub_date,
            lead_paragraph=lead_p,
            full_text=full_text,
            metrics_detected=metrics,
            embedded_images=[],
            key_quotes=quotes,
        )
    except Exception as e:
        logger.debug(f"Failed to fetch web article {url}: {e}")
        return None


def search_internet_company_news(
    brand_name: str,
    brand_url: str,
    max_articles: int = 5,
) -> List[ScrapedArticle]:
    """
    Primary fallback engine: Searches the open web for recent news, product launches,
    and partnerships regarding the brand.
    """
    domain = urlparse(brand_url).netloc.replace("www.", "")
    current_year = datetime.now().year
    logger.info(f"[INTERNET CRAWLER] Querying live web intelligence for: '{brand_name}' ({domain})...")

    discovered_articles: List[ScrapedArticle] = []
    seen_urls: Set[str] = set()

    # Query 1: Bing News Search with direct unquoted links
    query_terms = [
        f'"{brand_name}" (launches OR announced OR partnership OR funding OR acquisition)',
        f'"{brand_name}" AI OR platform OR expansion',
    ]

    candidate_links: List[Dict[str, str]] = []
    for q in query_terms:
        res = search_bing_news_rss(q, max_results=6)
        for r in res:
            u = r.get("url", "")
            if u and u.startswith("http") and u not in seen_urls:
                seen_urls.add(u)
                candidate_links.append(r)

    # Scrape direct articles
    for item in candidate_links:
        u = item.get("url", "")
        logger.info(f"[INTERNET CRAWLER] Scraping verified media report: {u[:80]}...")
        art = fetch_and_parse_article_url(u, fallback_title=item.get("title", ""))
        if art:
            # If quotes were empty, use snippet or lead
            if not art.key_quotes and item.get("snippet"):
                art.key_quotes = [item["snippet"]]
            if not art.published_date and item.get("pub_date"):
                try:
                    dt = datetime.strptime(item["pub_date"][:16], "%a, %d %b %Y")
                    art.published_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    art.published_date = str(current_year)

            discovered_articles.append(art)
            logger.info(
                f"[INTERNET CRAWLER] ✓ Mined: '{art.title[:50]}' ({art.published_date or 'Recent'}) | "
                f"{len(art.metrics_detected)} metrics | {len(art.key_quotes)} quotes"
            )

        if len(discovered_articles) >= max_articles:
            break

    # If still fewer than 2 articles, augment with Google News RSS headlines + snippets
    if len(discovered_articles) < 2:
        logger.info("[INTERNET CRAWLER] Augmenting with Google News RSS editorial coverage...")
        q_news = f'"{brand_name}" (launches OR partners OR growth OR AI)'
        news_items = search_google_news_rss(q_news, max_results=6)
        for item in news_items:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            source = item.get("source", "Press Release")
            if not title:
                continue

            date_str = None
            if item.get("pub_date"):
                try:
                    dt = datetime.strptime(item["pub_date"][:16], "%a, %d %b %Y")
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = str(current_year)

            metrics = extract_metrics_with_regex(title + " " + snippet)

            synth_article = ScrapedArticle(
                url=f"https://news.google.com/search?q={urllib.parse.quote(brand_name)}",
                title=f"[{source}] {title}",
                published_date=date_str or str(current_year),
                lead_paragraph=snippet or title,
                full_text=f"{title}. {snippet}",
                metrics_detected=metrics,
                key_quotes=[f"{title} — reported by {source}"] if source else [title],
            )
            discovered_articles.append(synth_article)
            if len(discovered_articles) >= max_articles:
                break

    logger.info(f"[INTERNET CRAWLER] Completed! Returning {len(discovered_articles)} verified web articles.")
    return discovered_articles
