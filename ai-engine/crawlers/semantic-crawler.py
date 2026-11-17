"""
Semantic & Competitor Intelligence Crawler (Crawler 2) — v2
Discovers and scrapes subpages to extract value props, competitor edges,
testimonials, pricing, FAQs, contact info, and schema.org data.

v2 improvements:
  - Sitemap.xml discovery for page enumeration
  - Wider testimonial extraction (div-based, aria-labels, role attributes)
  - Flexible USP/feature extraction (data-attributes, heading+paragraph pairs)
  - Robust pricing parser (filters out JS template literals)
  - Contact detail extraction (email, phone, address)
  - Core offering extraction from product/feature pages
  - Better FAQ detection (accordion patterns, aria-expanded, details/summary)
  - More priority paths (/features, /product, /integrations, /case-studies, /contact)
  - Team member extraction from /about pages
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Tag
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
    role: Optional[str] = None
    company: Optional[str] = None
    quote: str


class FAQItem(BaseModel):
    question: str
    answer: str


class TeamMember(BaseModel):
    name: str
    role: Optional[str] = None


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
    customer_names: List[str] = Field(default_factory=list)
    team_members: List[TeamMember] = Field(default_factory=list)
    scraped_pages: List[str] = Field(default_factory=list)
    discovered_pages: List[str] = Field(default_factory=list)


# Standard key pages to probe
PRIORITY_PATHS = [
    "/",
    "/about",
    "/about-us",
    "/pricing",
    "/faq",
    "/faqs",
    "/help",
    "/how-it-works",
    "/solutions",
    "/features",
    "/product",
    "/products",
    "/platform",
    "/integrations",
    "/customer-stories",
    "/customers",
    "/case-studies",
    "/reviews",
    "/testimonials",
    "/blog",
    "/contact",
    "/contact-us",
]


def clean_text(text: str) -> str:
    """Removes excess whitespace and linebreaks."""
    return re.sub(r"\s+", " ", text).strip()


def is_valid_prose(text: str, min_len: int = 15, max_len: int = 500) -> bool:
    """Checks if text looks like real prose (not JS, not too short/long)."""
    if not text or len(text) < min_len or len(text) > max_len:
        return False
    # Filter out JS-like strings
    if any(c in text for c in ["{", "}", "=>", "function", "const ", "var ", "===", "!=="]):
        return False
    # Filter out strings that are mostly special characters
    alpha_ratio = sum(1 for c in text if c.isalpha()) / max(len(text), 1)
    return alpha_ratio > 0.5


def extract_schema_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
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


def fetch_page(url: str, headers: Dict[str, str], timeout: int = 15) -> Optional[str]:
    """Fetches a single page HTML with custom headers."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "text/html" in content_type:
            return resp.text
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
    return None


def discover_sitemap_paths(origin: str, headers: Dict[str, str]) -> List[str]:
    """Tries to fetch sitemap.xml and extract page paths."""
    paths: List[str] = []
    sitemap_urls_to_try = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap-index.xml",
    ]

    for sitemap_url in sitemap_urls_to_try:
        try:
            resp = requests.get(sitemap_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                # Parse XML-ish content
                locs = re.findall(r"<loc>(.*?)</loc>", resp.text)
                for loc in locs:
                    loc = loc.strip()
                    parsed = urlparse(loc)
                    path = parsed.path.rstrip("/")
                    if path and path != "/" and not path.endswith((".xml", ".gz")):
                        paths.append(path)
                if paths:
                    logger.info(f"Discovered {len(paths)} paths from {sitemap_url}")
                    break
        except Exception:
            continue
    return paths


def extract_testimonials_from_html(soup: BeautifulSoup) -> List[Testimonial]:
    """Deep testimonial extraction using multiple strategies."""
    testimonials: List[Testimonial] = []
    seen_quotes: Set[str] = set()

    def add_testimonial(quote: str, author: str = "", role: str = "", company: str = ""):
        quote = clean_text(quote)
        if is_valid_prose(quote, min_len=20, max_len=600) and quote not in seen_quotes:
            seen_quotes.add(quote)
            testimonials.append(
                Testimonial(quote=quote, author=author or None, role=role or None, company=company or None)
            )

    # Strategy 1: <blockquote> and <q> tags
    for q in soup.find_all(["blockquote", "q"]):
        text = clean_text(q.get_text())
        parent = q.parent
        author = ""
        if parent:
            cite = parent.find(["cite", "figcaption", "strong", "h4", "h5"])
            if cite:
                author = clean_text(cite.get_text())
        add_testimonial(text, author)

    # Strategy 2: Containers with testimonial-related classes or data attributes
    testimonial_patterns = re.compile(
        r"(testimonial|review|quote|customer-story|customer-voice|client-quote|case-study|feedback|endorsement|said)",
        re.I,
    )
    containers = soup.find_all(
        ["div", "section", "article", "li", "figure"],
        class_=testimonial_patterns,
    )
    # Also check data-* attributes and id
    for el in soup.find_all(["div", "section", "article", "li"], id=testimonial_patterns):
        if el not in containers:
            containers.append(el)

    for container in containers:
        # Look for the quote text
        quote_el = container.find(["p", "span", "div", "blockquote", "q"])
        if not quote_el:
            continue
        quote_text = clean_text(quote_el.get_text())

        # Look for author info
        author = ""
        role = ""
        company = ""
        for author_sel in ["cite", "figcaption", "strong", "h4", "h5", "span"]:
            author_el = container.find(author_sel)
            if author_el and author_el != quote_el:
                author_text = clean_text(author_el.get_text())
                if 2 < len(author_text) < 60:
                    author = author_text
                    break

        add_testimonial(quote_text, author, role, company)

    # Strategy 3: Elements with aria-label containing "testimonial" or "quote"
    for el in soup.find_all(attrs={"aria-label": testimonial_patterns}):
        p = el.find("p")
        if p:
            add_testimonial(clean_text(p.get_text()))

    # Strategy 4: <figure> with <figcaption> (common testimonial pattern)
    for figure in soup.find_all("figure"):
        # Skip images/media figures
        if figure.find("img") and not figure.find("blockquote"):
            continue
        caption = figure.find("figcaption")
        quote_el = figure.find(["blockquote", "p", "q"])
        if quote_el:
            quote = clean_text(quote_el.get_text())
            author = clean_text(caption.get_text()) if caption else ""
            add_testimonial(quote, author)

    return testimonials


def extract_faqs_from_html(soup: BeautifulSoup) -> List[FAQItem]:
    """Deep FAQ extraction — schema, accordion patterns, details/summary."""
    faqs: List[FAQItem] = []
    seen_questions: Set[str] = set()

    def add_faq(question: str, answer: str):
        question = clean_text(question)
        answer = clean_text(answer)
        if question and answer and question not in seen_questions:
            if 10 < len(question) < 200 and 10 < len(answer) < 2000:
                seen_questions.add(question)
                faqs.append(FAQItem(question=question, answer=answer))

    # Strategy 1: Schema.org FAQ (handled separately in main loop)

    # Strategy 2: <details> / <summary> elements
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if summary:
            question = clean_text(summary.get_text())
            # Answer is everything in <details> except <summary>
            answer_parts = []
            for child in details.children:
                if child != summary and hasattr(child, "get_text"):
                    answer_parts.append(clean_text(child.get_text()))
            answer = " ".join(answer_parts)
            add_faq(question, answer)

    # Strategy 3: Accordion patterns (button + content with aria-expanded)
    accordion_buttons = soup.find_all(
        ["button", "div", "h3", "h4"],
        attrs={"aria-expanded": True}
    )
    for btn in accordion_buttons:
        question = clean_text(btn.get_text())
        # Find the associated content panel
        panel_id = btn.get("aria-controls")
        answer_el = None
        if panel_id:
            answer_el = soup.find(id=panel_id)
        if not answer_el:
            # Try next sibling
            next_sib = btn.find_next_sibling()
            if next_sib:
                answer_el = next_sib
        if answer_el:
            answer = clean_text(answer_el.get_text())
            add_faq(question, answer)

    # Strategy 4: FAQ-class containers
    faq_patterns = re.compile(r"(faq|question|accordion|expandable|collapse)", re.I)
    faq_sections = soup.find_all(["div", "section", "dl"], class_=faq_patterns)
    for section in faq_sections:
        # <dt>/<dd> pattern
        dts = section.find_all("dt")
        dds = section.find_all("dd")
        for dt, dd in zip(dts, dds):
            add_faq(clean_text(dt.get_text()), clean_text(dd.get_text()))

        # Heading + paragraph pairs
        headings = section.find_all(["h3", "h4", "h5", "button"])
        for h in headings:
            q_text = clean_text(h.get_text())
            # Look for the answer right after
            next_el = h.find_next_sibling()
            if next_el and next_el.name in ["p", "div", "span"]:
                a_text = clean_text(next_el.get_text())
                add_faq(q_text, a_text)

    return faqs


def extract_usps_and_offerings(soup: BeautifulSoup) -> tuple[List[str], List[str]]:
    """Extract USPs/advantages and core offerings from feature sections."""
    usps: Set[str] = set()
    offerings: Set[str] = set()

    # Wide net of class/id patterns for feature sections
    feature_patterns = re.compile(
        r"(feature|solution|benefit|value|why-?us|advantage|usp|capability|pillar|"
        r"differentiator|strength|offering|service|product-card|highlight|what-we)",
        re.I,
    )

    # Strategy 1: Class-matched sections
    feature_containers = soup.find_all(
        ["article", "section", "div", "li"],
        class_=feature_patterns,
    )
    # Also check id
    for el in soup.find_all(["article", "section", "div"], id=feature_patterns):
        if el not in feature_containers:
            feature_containers.append(el)

    for container in feature_containers[:20]:
        headings = container.find_all(["h2", "h3", "h4"])
        for h in headings:
            txt = clean_text(h.get_text())
            if is_valid_prose(txt, min_len=8, max_len=100):
                # Check if there's a description paragraph
                desc = h.find_next_sibling("p")
                if desc:
                    desc_text = clean_text(desc.get_text())
                    if is_valid_prose(desc_text, min_len=15, max_len=300):
                        usps.add(f"{txt}: {desc_text}")
                    else:
                        usps.add(txt)
                else:
                    usps.add(txt)

    # Strategy 2: Data attribute based (e.g., data-feature, data-service)
    data_elements = soup.find_all(attrs={"data-feature": True})
    data_elements += soup.find_all(attrs={"data-service": True})
    for el in data_elements:
        heading = el.find(["h2", "h3", "h4"])
        if heading:
            txt = clean_text(heading.get_text())
            if is_valid_prose(txt, min_len=8, max_len=100):
                offerings.add(txt)

    # Strategy 3: Heading + paragraph pairs in main content (wider grab)
    main_content = soup.find("main") or soup.find("body")
    if main_content:
        for h in main_content.find_all(["h2", "h3"], limit=20):
            txt = clean_text(h.get_text())
            if is_valid_prose(txt, min_len=10, max_len=100):
                # Check if it has a descriptive sibling
                next_p = h.find_next_sibling("p")
                if next_p:
                    desc = clean_text(next_p.get_text())
                    if is_valid_prose(desc, min_len=20, max_len=300):
                        offerings.add(txt)

    # Strategy 4: List items in feature/benefit sections
    for section in feature_containers[:10]:
        list_items = section.find_all("li")
        for li in list_items[:10]:
            txt = clean_text(li.get_text())
            if is_valid_prose(txt, min_len=15, max_len=150):
                usps.add(txt)

    return list(usps)[:12], list(offerings)[:8]


def extract_contact_details(soup: BeautifulSoup) -> Dict[str, str]:
    """Extracts email addresses, phone numbers, and physical addresses."""
    contacts: Dict[str, str] = {}
    page_text = soup.get_text()

    # Emails (from mailto: links or regex)
    mailto_links = soup.find_all("a", href=re.compile(r"^mailto:", re.I))
    for a in mailto_links:
        email = a["href"].replace("mailto:", "").split("?")[0].strip()
        if email and "@" in email:
            contacts.setdefault("email", email)

    if "email" not in contacts:
        email_match = re.search(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
            page_text
        )
        if email_match:
            email = email_match.group()
            # Filter out common false positives
            if not any(fp in email for fp in ["example.com", "domain.com", "email.com", "sentry.io"]):
                contacts["email"] = email

    # Phone numbers (from tel: links or regex)
    tel_links = soup.find_all("a", href=re.compile(r"^tel:", re.I))
    for a in tel_links:
        phone = a["href"].replace("tel:", "").strip()
        if phone:
            contacts.setdefault("phone", phone)

    if "phone" not in contacts:
        phone_match = re.search(
            r"(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}",
            page_text
        )
        if phone_match:
            phone = phone_match.group().strip()
            if 7 < len(phone) < 20:
                contacts["phone"] = phone

    # Physical address (Schema.org or common patterns)
    address_el = soup.find("address")
    if address_el:
        addr_text = clean_text(address_el.get_text())
        if 10 < len(addr_text) < 200:
            contacts["address"] = addr_text

    return contacts


def extract_customer_names(soup: BeautifulSoup) -> List[str]:
    """Extract customer/client logos alt texts from customer sections."""
    names: Set[str] = set()

    # Look for customer/client logo sections
    customer_patterns = re.compile(
        r"(customer|client|partner|trusted|logo-?wall|logo-?strip|brand|company|used-by|loved-by)",
        re.I,
    )
    customer_sections = soup.find_all(["section", "div"], class_=customer_patterns)
    customer_sections += soup.find_all(["section", "div"], id=customer_patterns)

    for section in customer_sections:
        images = section.find_all("img")
        for img in images:
            alt = img.get("alt", "").strip()
            if alt and 2 < len(alt) < 50 and alt.lower() not in ("logo", "image", "icon", "arrow"):
                # Clean common suffixes
                for suffix in [" logo", " Logo", " icon", " Icon"]:
                    alt = alt.replace(suffix, "")
                names.add(alt.strip())

    return list(names)[:20]


def extract_team_from_about(soup: BeautifulSoup) -> List[TeamMember]:
    """Extracts team member names and roles from about pages."""
    members: List[TeamMember] = []

    team_patterns = re.compile(r"(team|leadership|founders|people|staff|executives)", re.I)
    team_sections = soup.find_all(["section", "div"], class_=team_patterns)
    team_sections += soup.find_all(["section", "div"], id=team_patterns)

    for section in team_sections:
        cards = section.find_all(["div", "li", "article"], limit=20)
        for card in cards:
            name_el = card.find(["h3", "h4", "strong", "b"])
            if name_el:
                name = clean_text(name_el.get_text())
                if 3 < len(name) < 50 and not any(c in name for c in ["{", "}", "(", "="]):
                    role = ""
                    role_el = name_el.find_next_sibling(["p", "span"])
                    if role_el:
                        role = clean_text(role_el.get_text())
                        if len(role) > 60:
                            role = ""
                    members.append(TeamMember(name=name, role=role or None))

    return members[:15]


def extract_semantic_intelligence(base_url: str) -> SemanticIntelligence:
    """
    Crawls key marketing pages of the target URL to extract semantic business intelligence.
    """
    # Normalize URL
    parsed = urlparse(base_url)
    if not parsed.scheme:
        base_url = "https://" + base_url
        parsed = urlparse(base_url)

    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    logger.info(f"Starting Semantic Crawler for origin: {origin}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    scraped_pages: List[str] = []
    all_faqs: List[FAQItem] = []
    all_testimonials: List[Testimonial] = []
    all_usps: List[str] = []
    all_offerings: List[str] = []
    pricing_points: Set[str] = set()
    blog_titles: Set[str] = set()
    social_links: Dict[str, str] = {}
    contact_details: Dict[str, str] = {}
    customer_names: List[str] = []
    team_members: List[TeamMember] = []
    business_name = ""
    tagline = ""

    # ----- STEP 0: Discover pages via sitemap.xml -----
    logger.info("Checking for sitemap.xml...")
    sitemap_paths = discover_sitemap_paths(origin, headers)
    discovered_pages = [origin + p for p in sitemap_paths[:30]]

    # Merge sitemap paths with priority paths (priority first, dedup)
    all_paths = list(PRIORITY_PATHS)
    seen_paths = set(all_paths)
    # Add interesting sitemap pages (product, feature, customer pages)
    interesting_patterns = re.compile(
        r"(feature|product|solution|customer|case|about|pricing|faq|blog|contact|team|integrat)",
        re.I,
    )
    for path in sitemap_paths:
        if path not in seen_paths and interesting_patterns.search(path):
            all_paths.append(path)
            seen_paths.add(path)

    # ----- STEP 1: Fetch and analyze pages -----
    for path in all_paths:
        target = origin + path
        html = fetch_page(target, headers=headers)
        if not html:
            continue

        scraped_pages.append(target)
        logger.info(f"Scraped and analyzing: {target}")
        soup = BeautifulSoup(html, "html.parser")

        # ---- Homepage-specific extraction ----
        if path == "/":
            og_site_name = soup.find("meta", property="og:site_name")
            if og_site_name and og_site_name.get("content"):
                business_name = og_site_name["content"].strip()
            elif soup.title and soup.title.string:
                business_name = soup.title.string.split("|")[0].split("-")[0].split("—")[0].strip()

            h1 = soup.find("h1")
            if h1:
                tagline = clean_text(h1.text)

            # Customer names from logo walls on homepage
            customer_names = extract_customer_names(soup)

        # ---- Schema.org JSON-LD ----
        schemas = extract_schema_json_ld(soup)
        for schema in schemas:
            s_type = schema.get("@type", "")

            if s_type == "FAQPage" and "mainEntity" in schema:
                for q_obj in schema["mainEntity"]:
                    q = q_obj.get("name", "")
                    a = q_obj.get("acceptedAnswer", {}).get("text", "")
                    if q and a:
                        all_faqs.append(FAQItem(question=clean_text(q), answer=clean_text(a)))

            elif s_type == "Organization":
                if not business_name and schema.get("name"):
                    business_name = schema["name"]
                if "sameAs" in schema and isinstance(schema["sameAs"], list):
                    for s_url in schema["sameAs"]:
                        for platform in ["twitter", "linkedin", "instagram", "facebook", "youtube", "github", "tiktok"]:
                            if platform in s_url:
                                social_links[platform] = s_url
                # Contact from schema
                if "email" in schema:
                    contact_details.setdefault("email", schema["email"])
                if "telephone" in schema:
                    contact_details.setdefault("phone", schema["telephone"])

            elif s_type in ("Review", "Testimonial"):
                quote = schema.get("reviewBody", "")
                author = ""
                if isinstance(schema.get("author"), dict):
                    author = schema["author"].get("name", "")
                elif schema.get("author"):
                    author = str(schema["author"])
                if quote:
                    all_testimonials.append(
                        Testimonial(author=author or None, quote=clean_text(quote))
                    )

        # ---- Social Links (from footer or header anchors) ----
        platform_domains = {
            "instagram.com": "instagram",
            "linkedin.com": "linkedin",
            "x.com": "x",
            "twitter.com": "twitter",
            "youtube.com": "youtube",
            "facebook.com": "facebook",
            "tiktok.com": "tiktok",
            "github.com": "github",
        }
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            for domain, name in platform_domains.items():
                if domain in href:
                    if name not in social_links:
                        social_links[name] = href

        # ---- Testimonials (deep extraction) ----
        page_testimonials = extract_testimonials_from_html(soup)
        all_testimonials.extend(page_testimonials)

        # ---- FAQs (deep extraction) ----
        page_faqs = extract_faqs_from_html(soup)
        all_faqs.extend(page_faqs)

        # ---- USPs & Offerings ----
        page_usps, page_offerings = extract_usps_and_offerings(soup)
        all_usps.extend(page_usps)
        all_offerings.extend(page_offerings)

        # ---- Pricing (robust extraction) ----
        is_pricing_page = any(kw in path.lower() for kw in ["pricing", "plans", "price"])
        if is_pricing_page:
            # Find pricing cards/tiers
            pricing_cards = soup.find_all(
                ["div", "section", "li"],
                class_=re.compile(r"(plan|tier|price|pricing-card|package)", re.I),
            )
            for card in pricing_cards[:6]:
                # Get plan name
                plan_name_el = card.find(["h2", "h3", "h4"])
                plan_name = clean_text(plan_name_el.get_text()) if plan_name_el else ""

                # Get price
                price_el = card.find(string=re.compile(r"\$\d+|\€\d+|£\d+|Free", re.I))
                if price_el:
                    price_text = clean_text(str(price_el))
                    if is_valid_prose(price_text, min_len=2, max_len=60):
                        entry = f"{plan_name}: {price_text}" if plan_name else price_text
                        pricing_points.add(entry)

            # Fallback: regex on full page text
            if not pricing_points:
                pricing_strings = soup.find_all(
                    string=re.compile(r"(\$\d[\d,.]+|\€\d[\d,.]+|£\d[\d,.]+)", re.I)
                )
                for p_str in pricing_strings[:10]:
                    cleaned = clean_text(str(p_str))
                    # Must have an actual dollar amount (not just $)
                    if re.search(r"\$\d{1,}", cleaned) and is_valid_prose(cleaned, min_len=3, max_len=120):
                        pricing_points.add(cleaned)

        # ---- Blog headlines ----
        is_blog_page = any(kw in path.lower() for kw in ["blog", "news", "articles", "resources"])
        if is_blog_page:
            blog_headers = soup.find_all(["h2", "h3"])
            for h in blog_headers:
                txt = clean_text(h.text)
                if is_valid_prose(txt, min_len=15, max_len=120):
                    if not any(skip in txt.lower() for skip in [
                        "subscribe", "newsletter", "cookie", "sign up", "privacy",
                        "terms", "follow us", "contact"
                    ]):
                        blog_titles.add(txt)

        # ---- Contact details ----
        is_contact_page = any(kw in path.lower() for kw in ["contact", "about", "support", "help"])
        if is_contact_page or path == "/":
            page_contacts = extract_contact_details(soup)
            for key, val in page_contacts.items():
                contact_details.setdefault(key, val)

        # ---- Team members (from about pages) ----
        is_about_page = any(kw in path.lower() for kw in ["about", "team", "people", "leadership"])
        if is_about_page:
            page_team = extract_team_from_about(soup)
            team_members.extend(page_team)

        # ---- Customer names from dedicated customer pages ----
        is_customer_page = any(kw in path.lower() for kw in ["customer", "case-stud", "client"])
        if is_customer_page:
            page_customers = extract_customer_names(soup)
            customer_names.extend(page_customers)

    # ----- DEDUPLICATION -----
    unique_testimonials = []
    seen_quotes: Set[str] = set()
    for t in all_testimonials:
        if t.quote not in seen_quotes:
            seen_quotes.add(t.quote)
            unique_testimonials.append(t)

    unique_faqs = []
    seen_questions: Set[str] = set()
    for f in all_faqs:
        if f.question not in seen_questions:
            seen_questions.add(f.question)
            unique_faqs.append(f)

    unique_usps = list(dict.fromkeys(all_usps))
    unique_offerings = list(dict.fromkeys(all_offerings))
    unique_customers = list(dict.fromkeys(customer_names))

    # Deduplicate team members by name
    unique_team: List[TeamMember] = []
    seen_team: Set[str] = set()
    for m in team_members:
        if m.name not in seen_team:
            seen_team.add(m.name)
            unique_team.append(m)

    result = SemanticIntelligence(
        url=origin,
        business_name=business_name or "Unknown Brand",
        tagline=tagline,
        core_offerings=unique_offerings[:8],
        advantages_and_usps=unique_usps[:12],
        pricing_summary=list(pricing_points)[:8],
        customer_testimonials=unique_testimonials[:8],
        faqs=unique_faqs[:15],
        social_links=social_links,
        contact_details=contact_details,
        blog_headlines=list(blog_titles)[:10],
        customer_names=unique_customers[:20],
        team_members=unique_team[:15],
        scraped_pages=scraped_pages,
        discovered_pages=discovered_pages[:20],
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
    print(f"Pages Discovered:   {len(data.discovered_pages)} (from sitemap)")
    print(f"FAQs Found:         {len(data.faqs)}")
    print(f"Testimonials Found: {len(data.customer_testimonials)}")
    print(f"USPs/Advantages:    {len(data.advantages_and_usps)}")
    print(f"Core Offerings:     {len(data.core_offerings)}")
    print(f"Pricing Points:     {len(data.pricing_summary)}")
    print(f"Blog Headlines:     {len(data.blog_headlines)}")
    print(f"Customer Names:     {data.customer_names[:5]}")
    print(f"Team Members:       {len(data.team_members)}")
    print(f"Social Links:       {list(data.social_links.keys())}")
    print(f"Contact Details:    {data.contact_details}")
    print(f"Advantages:         {data.advantages_and_usps[:3]}")
    print("---------------------------------------\n")
