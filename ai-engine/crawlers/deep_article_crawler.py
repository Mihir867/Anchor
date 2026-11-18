"""
Deep Article & Milestone Crawler
Crawls the actual full-body contents of recent blog posts, case studies, 
press releases, and customer stories to extract real, auditable facts, dates, and metrics.
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Tag
import requests
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("deep_article_crawler")


class ScrapedArticle(BaseModel):
    url: str
    title: str
    published_date: Optional[str] = None
    lead_paragraph: str = ""
    full_text: str = ""
    metrics_detected: List[str] = Field(default_factory=list)
    embedded_images: List[str] = Field(default_factory=list)
    key_quotes: List[str] = Field(default_factory=list)


def clean_text(text: str) -> str:
    """Removes excess whitespace, tabs, and linebreaks."""
    return re.sub(r"\s+", " ", text).strip()


def extract_published_date(soup: BeautifulSoup, html: str, url: str) -> Optional[str]:
    """
    Deterministically extracts the published date using Schema JSON-LD,
    meta tags, <time> elements, and URL patterns.
    """
    # 1. Schema.org JSON-LD (most reliable)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            if script.string:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    date = data.get("datePublished") or data.get("dateModified") or data.get("uploadDate")
                    if date:
                        return str(date).split("T")[0]
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            date = item.get("datePublished") or item.get("dateModified")
                            if date:
                                return str(date).split("T")[0]
        except Exception:
            continue

    # 2. OpenGraph & Meta tags
    for meta_prop in [
        "article:published_time",
        "og:published_time",
        "datePublished",
        "publication_date",
        "pubdate",
        "sailthru.date",
        "parsely-pub-date",
    ]:
        meta = soup.find("meta", property=meta_prop) or soup.find("meta", attrs={"name": meta_prop})
        if meta and meta.get("content"):
            val = meta["content"].strip()
            # ISO date clean
            date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", val)
            if date_match:
                return date_match.group(1).replace("/", "-")

    # 3. <time> HTML tag
    time_tag = soup.find("time")
    if time_tag:
        dt = time_tag.get("datetime") or time_tag.get_text()
        date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", dt)
        if date_match:
            return date_match.group(1).replace("/", "-")
        # Check for natural language dates (e.g. 'November 12, 2024')
        month_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
            dt,
            re.I,
        )
        if month_match:
            try:
                parsed_dt = datetime.strptime(month_match.group(0).replace(",", ""), "%B %d %Y")
                return parsed_dt.strftime("%Y-%m-%d")
            except Exception:
                pass

    # 4. URL date pattern (e.g. /2024/11/post-name or /2025/post-name)
    url_date = re.search(r"/(\d{4})/(\d{1,2})/", url)
    if url_date:
        year, month = url_date.groups()
        return f"{year}-{month.zfill(2)}-01"

    url_year = re.search(r"/(\d{4})/", url)
    if url_year:
        return f"{url_year.group(1)}-01-01"

    return None


def extract_metrics_with_regex(text: str) -> List[str]:
    """
    Deterministically discovers hard metrics:
    - Dollar amounts ($27M, $1.2B, $500K)
    - Percentages (30%, 75%, 2.5%)
    - Time reductions (15 days, 4 weeks, 28 weeks to 4)
    - Multipliers (5x, 10x)
    """
    metrics = set()

    # 1. Funding / Revenue ($X Million/Billion/K)
    currencies = re.findall(r"\$\d+(?:\.\d+)?\s*(?:billion|million|k|m|b)?(?:\s+(?:series\s+[a-z]|seed|funding|round|revenue|contract|savings))?", text, re.I)
    for c in currencies:
        c_clean = clean_text(c)
        if len(c_clean) > 1 and re.search(r"\d", c_clean):
            metrics.add(c_clean)

    # 2. Percentages (e.g. 30% savings, 75% reduction)
    percentages = re.findall(r"\b\d+(?:\.\d+)?%\s*(?:increase|decrease|reduction|faster|savings|growth|cheaper|variance|more|less)?\b", text, re.I)
    for p in percentages:
        p_clean = clean_text(p)
        if "%" in p_clean:
            metrics.add(p_clean)

    # 3. Durations & Timelines (e.g. 15 days, 28 weeks to 4 weeks, 3 minutes)
    durations = re.findall(r"\b(?:from\s+)?\d+\s*(?:weeks|days|months|hours|minutes)\s*(?:to\s+\d+\s*(?:weeks|days|months|hours|minutes))?\b", text, re.I)
    for d in durations:
        d_clean = clean_text(d)
        if re.search(r"\d", d_clean):
            metrics.add(d_clean)

    # 4. Multipliers (e.g. 5x faster, 10x ROI)
    multipliers = re.findall(r"\b\d+x\s*(?:faster|more|efficiency|growth|roi|speed)?\b", text, re.I)
    for m in multipliers:
        metrics.add(clean_text(m))

    return sorted(list(metrics))[:15]


def extract_article_body(soup: BeautifulSoup) -> tuple[str, str, List[str]]:
    """
    Extracts the main clean article text, lead paragraph, and key quotes.
    Filters out headers, footers, sidebars, cookie notices, and navigation.
    """
    # Remove unwanted elements
    for unwanted in soup.find_all(["nav", "header", "footer", "aside", "script", "style", "noscript", "svg", "form"]):
        unwanted.decompose()

    # Find the main container
    main_el = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=re.compile(r"(article-content|post-content|blog-content|entry-content|story-body|rich-text)", re.I))
        or soup.find(id=re.compile(r"(article-content|post-content|blog-content|entry-content)", re.I))
        or soup.body
    )

    if not main_el:
        return "", "", []

    paragraphs = main_el.find_all("p")
    lead_paragraph = ""
    body_paragraphs = []
    key_quotes = []

    for p in paragraphs:
        txt = clean_text(p.get_text())
        # Filter boilerplate
        if len(txt) < 25:
            continue
        if any(skip in txt.lower() for skip in ["cookie", "privacy policy", "all rights reserved", "subscribe to", "sign up for"]):
            continue

        body_paragraphs.append(txt)
        if not lead_paragraph and len(txt) > 40:
            lead_paragraph = txt

        # Check if paragraph is a quote
        if ("“" in txt and "”" in txt) or ('"' in txt and any(verb in txt.lower() for verb in ["said", "stated", "added", "noted", "explained"])):
            key_quotes.append(txt)

    full_text = " \n\n".join(body_paragraphs[:15])  # Cap at top 15 paragraphs for token efficiency
    return lead_paragraph, full_text, key_quotes[:5]


def extract_embedded_images(soup: BeautifulSoup, origin: str) -> List[str]:
    """Extracts project photos and figures embedded inside the article."""
    images = []
    seen = set()

    main_el = soup.find("article") or soup.find("main") or soup.body
    if not main_el:
        return []

    for img in main_el.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and not src.startswith("data:"):
            abs_url = urljoin(origin, src)
            # Filter icons, avatars, trackers
            if not any(sub in abs_url.lower() for sub in ["icon", "avatar", "logo", "pixel", "tracker", "badge", "flag"]):
                if abs_url not in seen:
                    seen.add(abs_url)
                    images.append(abs_url)

    return images[:6]


EXCLUDED_TAXONOMY_KEYWORDS = [
    "/category/", "/categories/", "/tag/", "/tags/", "/author/", "/authors/",
    "/page/", "/archives/", "/archive/", "/topics/", "/topic/", "/feed", "/rss"
]


def is_archive_or_taxonomy_url(url: str) -> bool:
    """Checks if a URL points to a category/tag/archive listing rather than a single article."""
    u_lower = url.lower()
    return any(bad in u_lower for bad in EXCLUDED_TAXONOMY_KEYWORDS)


def deep_crawl_articles(
    base_url: str,
    article_urls: Optional[List[str]] = None,
    max_articles: int = 5,
    brand_name: Optional[str] = None,
) -> List[ScrapedArticle]:
    """
    Crawls individual article URLs to extract complete body text, metrics, dates, and images.
    Falls back to Internet News Search if on-site articles are sparse or low-yield.
    """
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc or parsed.path}".rstrip("/")
    detected_brand = brand_name or parsed.netloc.replace("www.", "").split(".")[0].title()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # If article_urls not provided, discover from output_semantic.json or priority sections
    target_urls: List[str] = []
    category_urls: List[str] = []

    if article_urls:
        target_urls = [u for u in article_urls if not is_archive_or_taxonomy_url(u)]
    else:
        semantic_path = Path(__file__).resolve().parent.parent / "output_semantic.json"
        if semantic_path.exists():
            try:
                with open(semantic_path, "r", encoding="utf-8") as f:
                    sem_data = json.load(f)
                    if not brand_name and sem_data.get("business_name"):
                        detected_brand = sem_data["business_name"]
                    all_scraped = sem_data.get("scraped_pages", []) + sem_data.get("discovered_pages", [])
                    # Filter for actual articles (path depth >= 2 with blog/news/case-study pattern)
                    article_pattern = re.compile(
                        r"/(blog-news|blog|news|newsroom|press|case-stud|customer|client|story|article|project)s?/[a-zA-Z0-9_-]{3,}",
                        re.I,
                    )
                    for u in all_scraped:
                        if article_pattern.search(u):
                            if is_archive_or_taxonomy_url(u):
                                if u not in category_urls:
                                    category_urls.append(u)
                            else:
                                if u not in target_urls:
                                    target_urls.append(u)
            except Exception as e:
                logger.warning(f"Could not read output_semantic.json: {e}")

    # If we have category URLs but few direct articles, inspect category pages to extract child articles
    if len(target_urls) < max_articles and category_urls:
        for cat_url in category_urls[:3]:
            try:
                resp = requests.get(cat_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    cat_soup = BeautifulSoup(resp.text, "html.parser")
                    for a in cat_soup.find_all("a", href=True):
                        full = urljoin(origin, a["href"])
                        if origin in full and not is_archive_or_taxonomy_url(full):
                            if len(urlparse(full).path.strip("/").split("/")) >= 2:
                                if full not in target_urls:
                                    target_urls.append(full)
                if len(target_urls) >= max_articles * 2:
                    break
            except Exception:
                continue

    # Priority index paths for corporate blogs & press centers
    if len(target_urls) < max_articles:
        priority_paths = [
            "/newsroom", "/news", "/press", "/press-releases", "/announcements",
            "/sprint", "/case-studies", "/customers", "/blog", "/blog-news"
        ]
        for index_path in priority_paths:
            try:
                index_url = origin + index_path
                resp = requests.get(index_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        full = urljoin(origin, href)
                        if origin in full and not is_archive_or_taxonomy_url(full):
                            if len(urlparse(full).path.strip("/").split("/")) >= 2:
                                if any(sub in full for sub in ["blog", "news", "press", "case", "customer", "story", "launch", "release"]):
                                    if full not in target_urls and full != index_url:
                                        target_urls.append(full)
                if len(target_urls) >= max_articles * 2:
                    break
            except Exception:
                continue

    logger.info(f"Identified {len(target_urls)} candidate deep article URLs (filtered out taxonomy archives). Crawling top {max_articles}...")
    scraped_articles: List[ScrapedArticle] = []

    for url in target_urls[:max_articles]:
        try:
            logger.info(f"Deep scraping: {url}...")
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
                continue

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Title
            title = ""
            h1 = soup.find("h1")
            if h1:
                title = clean_text(h1.get_text())
            elif soup.title:
                title = clean_text(soup.title.get_text().split("|")[0].split("-")[0])

            if not title:
                title = urlparse(url).path.strip("/").split("/")[-1].replace("-", " ").title()

            # Date
            pub_date = extract_published_date(soup, html, url)

            # Body, lead, quotes
            lead_p, full_text, quotes = extract_article_body(soup)
            if len(full_text) < 100:
                logger.warning(f"Skipping {url}: content too short ({len(full_text)} chars).")
                continue

            # Metrics
            metrics = extract_metrics_with_regex(full_text)

            # Images
            images = extract_embedded_images(soup, origin)

            article = ScrapedArticle(
                url=url,
                title=title,
                published_date=pub_date,
                lead_paragraph=lead_p,
                full_text=full_text,
                metrics_detected=metrics,
                embedded_images=images,
                key_quotes=quotes,
            )
            scraped_articles.append(article)
            logger.info(f"Successfully scraped '{title}' ({pub_date or 'No date'}) -> {len(metrics)} metrics, {len(quotes)} quotes.")

        except Exception as e:
            logger.warning(f"Failed to deep crawl {url}: {e}")

    # Quality check: count articles with actual metrics or quotes
    quality_articles = [
        a for a in scraped_articles
        if len(a.metrics_detected) > 0 or len(a.key_quotes) > 0
    ]

    # If on-site articles are sparse or low-yield, fallback to live Internet News Intelligence!
    if len(quality_articles) < 2:
        logger.info(
            f"\n[INTERNET FALLBACK] On-site articles yielded only {len(quality_articles)} high-evidence stories. "
            f"Querying live web intelligence for '{detected_brand}'..."
        )
        try:
            from .internet_news_crawler import search_internet_company_news
            internet_articles = search_internet_company_news(
                brand_name=detected_brand,
                brand_url=base_url,
                max_articles=max_articles,
            )
            if internet_articles:
                # Merge internet news articles ahead of empty on-site pages
                scraped_articles = internet_articles + [a for a in scraped_articles if a not in quality_articles]
                logger.info(f"[INTERNET FALLBACK] Successfully integrated {len(internet_articles)} verified web media stories!")
        except Exception as e:
            logger.warning(f"[INTERNET FALLBACK] Could not execute internet news fallback: {e}")

    logger.info(f"Deep crawling complete. Gathered {len(scraped_articles)} rich articles.")
    return scraped_articles


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://inhabitr.ai"
    articles = deep_crawl_articles(target, max_articles=5)

    out_path = Path("output_deep_articles.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in articles], f, indent=2)

    logger.info(f"Saved {len(articles)} deep articles to {out_path.resolve()}")
