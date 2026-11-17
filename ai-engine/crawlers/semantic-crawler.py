"""
Semantic & Competitor Intelligence Crawler (Crawler 2)
Discovers and scrapes subpages (/about, /pricing, /faq, /customer-stories)
to extract value props, competitor edges, testimonials, and schema.org data.
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("semantic_crawler")


class Testimonial(BaseModel):
    author: Optional[str] = None
    company: Optional[str] = None
    quote: str


class FAQItem(BaseModel):
    question: str
    answer: str


class SemanticIntelligence(BaseModel):
    url: str
    business_name: str = ""
    tagline: str = ""
    core_offerings: List[str] = Field(default_factory=list)
    advantages_and_usps: List[str] = Field(default_factory=list)
    pricing_summary: List[str] = Field(default_factory=list)
    customer_testimonials: List[Testimonial] = Field(default_factory=list)
    faqs: List[FAQItem] = Field(default_factory=list)
    social_links: Dict[str, str] = Field(default_factory=dict)
    contact_details: Dict[str, str] = Field(default_factory=dict)
    blog_headlines: List[str] = Field(default_factory=list)
    scraped_pages: List[str] = Field(default_factory=list)


# Standard key pages to probe on marketing websites
PRIORITY_PATHS = [
    "/",
    "/about",
    "/about-us",
    "/pricing",
    "/faq",
    "/faqs",
    "/how-it-works",
    "/solutions",
    "/customer-stories",
    "/customers",
    "/reviews",
    "/blog",
]


def clean_text(text: str) -> str:
    """Removes excess whitespace and linebreaks."""
    return re.sub(r"\s+", " ", text).strip()


def extract_schema_json_ld(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extracts all Schema.org JSON-LD scripts embedded in the page."""
    schema_data = []
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            if script.string:
                data = json.loads(script.string)
                if isinstance(data, list):
                    schema_data.extend(data)
                else:
                    schema_data.append(data)
        except Exception:
            continue
    return schema_data


def fetch_page(url: str, headers: Dict[str, str], timeout: int = 10) -> Optional[str]:
    """Fetches a single page HTML with custom headers."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            return resp.text
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
    return None


def extract_semantic_intelligence(base_url: str) -> SemanticIntelligence:
    """
    Crawls key marketing pages of the target URL to extract semantic business intelligence.
    """
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc or parsed.path}".rstrip("/")
    logger.info(f"Starting Semantic Crawler for origin: {origin}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    scraped_pages = []
    all_faqs: List[FAQItem] = []
    all_testimonials: List[Testimonial] = []
    advantages: Set[str] = set()
    core_offerings: Set[str] = set()
    pricing_points: Set[str] = set()
    blog_titles: Set[str] = set()
    social_links: Dict[str, str] = {}
    contact_details: Dict[str, str] = {}
    business_name = ""
    tagline = ""

    # 1. Fetch priority pages
    for path in PRIORITY_PATHS:
        target = origin + path
        html = fetch_page(target, headers=headers)
        if not html:
            continue

        scraped_pages.append(target)
        logger.info(f"Scraped and analyzing: {target}")
        soup = BeautifulSoup(html, "html.parser")

        # Extract Business Name & Tagline from Homepage
        if path == "/":
            og_site_name = soup.find("meta", property="og:site_name")
            if og_site_name and og_site_name.get("content"):
                business_name = og_site_name["content"].strip()
            elif soup.title:
                business_name = soup.title.string.split("|")[0].split("-")[0].strip()

            h1 = soup.find("h1")
            if h1:
                tagline = clean_text(h1.text)

        # 2. Extract Schema.org JSON-LD (Rich snippets)
        schemas = extract_schema_json_ld(soup)
        for schema in schemas:
            s_type = schema.get("@type", "")
            # FAQ Schema
            if s_type == "FAQPage" and "mainEntity" in schema:
                for q_obj in schema["mainEntity"]:
                    q = q_obj.get("name", "")
                    a = q_obj.get("acceptedAnswer", {}).get("text", "")
                    if q and a:
                        all_faqs.append(FAQItem(question=clean_text(q), answer=clean_text(a)))

            # Organization Schema
            elif s_type == "Organization":
                if not business_name and schema.get("name"):
                    business_name = schema["name"]
                if "sameAs" in schema and isinstance(schema["sameAs"], list):
                    for s_url in schema["sameAs"]:
                        for platform in ["twitter", "linkedin", "instagram", "facebook", "youtube", "github"]:
                            if platform in s_url:
                                social_links[platform] = s_url

            # Review / Testimonial Schema
            elif s_type in ("Review", "Testimonial"):
                quote = schema.get("reviewBody", "")
                author = schema.get("author", {}).get("name", "") if isinstance(schema.get("author"), dict) else str(schema.get("author", ""))
                if quote:
                    all_testimonials.append(Testimonial(author=author, quote=clean_text(quote)))

        # 3. HTML Scrape: Social Links (from footer or header)
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            for platform in ["instagram.com", "linkedin.com", "x.com", "twitter.com", "youtube.com", "facebook.com", "tiktok.com"]:
                if platform in href:
                    clean_name = platform.split(".")[0]
                    if clean_name not in social_links:
                        social_links[clean_name] = href

        # 4. HTML Scrape: Testimonials / Customer Stories (blockquotes & quote classes)
        quotes = soup.find_all(["blockquote", "q"])
        for q in quotes:
            text = clean_text(q.text)
            if len(text) > 20 and len(text) < 400:
                # Look for adjacent author
                parent = q.parent
                author = ""
                company = ""
                strong = parent.find(["strong", "cite", "h4", "p"])
                if strong:
                    author = clean_text(strong.text)
                all_testimonials.append(Testimonial(quote=text, author=author, company=company))

        # 5. HTML Scrape: Pricing Clues
        if "pricing" in path or "/pricing" in target:
            pricing_elements = soup.find_all(string=re.compile(r"(\$|€|£|kr|\/mo|\/month|free trial|per month)", re.I))
            for p_str in pricing_elements[:8]:
                cleaned = clean_text(p_str)
                if len(cleaned) < 120 and cleaned not in pricing_points:
                    pricing_points.add(cleaned)

        # 6. HTML Scrape: Blog headlines
        if "blog" in path:
            blog_headers = soup.find_all(["h2", "h3"])
            for h in blog_headers:
                txt = clean_text(h.text)
                if len(txt) > 15 and len(txt) < 100 and not any(skip in txt.lower() for skip in ["subscribe", "newsletter", "cookie"]):
                    blog_titles.add(txt)

        # 7. Core Offerings & USPs (Feature lists & cards)
        feature_sections = soup.find_all(["article", "section", "div"], class_=re.compile(r"(feature|solution|benefit|value|why-us)", re.I))
        for sec in feature_sections[:5]:
            headings = sec.find_all(["h3", "h4"])
            for h in headings:
                txt = clean_text(h.text)
                if 10 < len(txt) < 80:
                    advantages.add(txt)

    # Clean deduplicated results
    unique_testimonials = []
    seen_quotes = set()
    for t in all_testimonials:
        if t.quote not in seen_quotes:
            seen_quotes.add(t.quote)
            unique_testimonials.append(t)

    result = SemanticIntelligence(
        url=origin,
        business_name=business_name or "Unknown Brand",
        tagline=tagline,
        core_offerings=list(core_offerings)[:6],
        advantages_and_usps=list(advantages)[:10],
        pricing_summary=list(pricing_points)[:6],
        customer_testimonials=unique_testimonials[:6],
        faqs=all_faqs[:10],
        social_links=social_links,
        contact_details=contact_details,
        blog_headlines=list(blog_titles)[:8],
        scraped_pages=scraped_pages,
    )

    logger.info(f"Semantic Extraction Complete! Scraped {len(scraped_pages)} pages.")
    return result


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://native.no/"
    logger.info(f"Running semantic crawler on: {target_url}")

    data = extract_semantic_intelligence(target_url)

    output_path = Path("output_semantic.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data.model_dump(), f, indent=2)

    logger.info(f"Saved semantic data to {output_path.resolve()}")
    print("\n--- SEMANTIC INTELLIGENCE EXTRACTED ---")
    print(f"Business Name:      {data.business_name}")
    print(f"Tagline:            {data.tagline}")
    print(f"Pages Scraped:      {len(data.scraped_pages)}")
    print(f"FAQs Found:         {len(data.faqs)}")
    print(f"Testimonials Found: {len(data.customer_testimonials)}")
    print(f"Blog Headlines:     {len(data.blog_headlines)}")
    print(f"Social Links:       {list(data.social_links.keys())}")
    print(f"Advantages/USPs:    {data.advantages_and_usps[:3]}")
    print("---------------------------------------\n")