import re
import json
import html
import os
from difflib import SequenceMatcher
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_ASURA_BASE_URL = "https://asurascans.com"
DEFAULT_ASURA_URL_TEMPLATE = "https://asurascans.com/comics/{slug}"


def get_asura_enabled() -> bool:
    value = os.getenv("ASURA_ENABLED", "true").strip().lower()
    return value in ("1", "true", "yes", "on")


def get_asura_base_url() -> str:
    return os.getenv("ASURA_BASE_URL", DEFAULT_ASURA_BASE_URL).rstrip("/")


def get_asura_url_template() -> str:
    return os.getenv("ASURA_URL_TEMPLATE", DEFAULT_ASURA_URL_TEMPLATE)


def slugify_title(title: str) -> str:
    """
    Example:
    'Ending Maker' -> 'ending-maker'
    'Martial God Regressed to Level 2' -> 'martial-god-regressed-to-level-2'
    """
    title = title.lower().strip()
    title = re.sub(r"[’'`]", "", title)
    title = re.sub(r"[^a-z0-9]+", "-", title)
    title = re.sub(r"-+", "-", title)
    return title.strip("-")


def normalize_title(title: str) -> str:
    if not title:
        return ""

    title = title.lower()
    title = re.sub(r"\([^)]*\)", " ", title)
    title = re.sub(r"[’'`]", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def fuzzy_score(a: str, b: str) -> float:
    a_norm = normalize_title(a)
    b_norm = normalize_title(b)

    if not a_norm or not b_norm:
        return 0.0

    if a_norm == b_norm:
        return 0.95

    return round(SequenceMatcher(None, a_norm, b_norm).ratio(), 3)


def to_float(value):
    try:
        if value is None:
            return None
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def format_chapter_number(value):
    if value is None:
        return None

    value = float(value)
    return int(value) if value.is_integer() else value


def is_asura_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        base_host = urlparse(get_asura_base_url()).netloc
        return parsed.netloc.endswith(base_host)
    except Exception:
        return False


def find_comicseries_objects(data):
    """
    Recursively find JSON-LD objects where @type == ComicSeries.
    Handles dict, list, and nested @graph structures.
    """
    found = []

    if isinstance(data, dict):
        if data.get("@type") == "ComicSeries":
            found.append(data)

        for value in data.values():
            found.extend(find_comicseries_objects(value))

    elif isinstance(data, list):
        for item in data:
            found.extend(find_comicseries_objects(item))

    return found


def extract_title_from_html(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")

    # 1. JSON-LD ComicSeries name
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for item in find_comicseries_objects(data):
            name = item.get("name")
            if name:
                return html.unescape(str(name)).strip()

    # 2. h1
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)

    # 3. og:title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].replace("| Asura Scans", "").strip()

    # 4. title tag
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(" ", strip=True).replace("| Asura Scans", "").strip()

    return None


def looks_blocked_or_invalid(page_html: str) -> bool:
    """
    Conservative block detection.
    Normal Asura pages may contain adblock/javascript text, so do not reject those.
    """
    lowered = page_html.lower()

    normal_markers = [
        '"@type":"comicseries"',
        '"@type": "comicseries"',
        '"chaptercount"',
        "asura scans",
    ]

    if any(marker in lowered for marker in normal_markers):
        return False

    block_markers = [
        "cf-chl",
        "cf-browser-verification",
        "checking if the site connection is secure",
        "verify you are human",
        "captcha",
        "access denied",
        "attention required",
        "ddos protection by cloudflare",
    ]

    return any(marker in lowered for marker in block_markers)


def extract_jsonld_episode_count(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    values = []

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for item in find_comicseries_objects(data):
            num = to_float(item.get("numberOfEpisodes"))
            if num is not None:
                values.append(num)

    return values


def extract_astro_chapter_count(page_html: str):
    decoded_html = html.unescape(page_html)
    values = []

    # Example:
    # "chapterCount":[0,116]
    pattern = r'"chapterCount"\s*:\s*\[\s*0\s*,\s*(\d+(?:\.\d+)?)\s*\]'

    for match in re.finditer(pattern, decoded_html, flags=re.IGNORECASE):
        num = to_float(match.group(1))
        if num is not None:
            values.append(num)

    return values


def extract_chapter_text_numbers(page_html: str):
    """
    Extracts text like:
    - Chapter 116
    - Chapter 12.5

    This can also catch related/recommended series at the bottom.
    So it is filtered against trusted JSON-LD/Astro count.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    text = soup.get_text(" ", strip=True)

    values = []

    for match in re.finditer(r"\bChapter\s+(\d+(?:\.\d+)?)\b", text, flags=re.IGNORECASE):
        num = to_float(match.group(1))
        if num is not None:
            values.append(num)

    return values


def extract_latest_chapter_from_asura_html(page_html: str):
    """
    Correct strategy:

    Trusted signals:
    1. JSON-LD ComicSeries.numberOfEpisodes
    2. Astro props chapterCount

    Less trusted signal:
    3. 'Chapter X' text, because it can include related/recommended series.

    Rule:
    - Use max(JSON-LD + Astro) as trusted_base.
    - Only allow Chapter X text if it is close to trusted_base.
      Example: trusted_base=182, chapter list has 183, accept 183.
      But trusted_base=116, related section has 201, reject 201.
    """

    jsonld_values = extract_jsonld_episode_count(page_html)
    astro_values = extract_astro_chapter_count(page_html)
    chapter_text_values = extract_chapter_text_numbers(page_html)

    trusted_values = jsonld_values + astro_values

    debug = {
        "jsonld_numberOfEpisodes": jsonld_values,
        "astro_chapterCount": astro_values,
        "chapter_text_numbers_raw_count": len(chapter_text_values),
        "chapter_text_numbers_filtered_count": 0,
        "chapter_text_numbers_filtered_max": None,
        "chosen_strategy": None,
    }

    if trusted_values:
        trusted_base = max(trusted_values)

        # Allow small overshoot because sometimes the latest visible chapter is +1
        # compared to numberOfEpisodes.
        allowed_upper_limit = trusted_base + 5

        filtered_chapter_text = [
            x for x in chapter_text_values
            if x <= allowed_upper_limit
        ]

        debug["chapter_text_numbers_filtered_count"] = len(filtered_chapter_text)
        debug["chapter_text_numbers_filtered_max"] = max(filtered_chapter_text) if filtered_chapter_text else None

        final_candidates = trusted_values + filtered_chapter_text
        latest = max(final_candidates)

        debug["chosen_strategy"] = "trusted_jsonld_or_astro_with_filtered_chapter_text"

        return format_chapter_number(latest), debug

    # Fallback only if JSON-LD/Astro are missing.
    # Avoid year-like values such as 2024, 2025, 2026.
    reasonable_chapter_text = [
        x for x in chapter_text_values
        if 0 < x < 1000
    ]

    debug["chapter_text_numbers_filtered_count"] = len(reasonable_chapter_text)
    debug["chapter_text_numbers_filtered_max"] = max(reasonable_chapter_text) if reasonable_chapter_text else None

    if reasonable_chapter_text:
        latest = max(reasonable_chapter_text)
        debug["chosen_strategy"] = "chapter_text_only_fallback"
        return format_chapter_number(latest), debug

    debug["chosen_strategy"] = "no_chapter_found"
    return None, debug


def fetch_asura_page_by_url(url: str):
    if not is_asura_url(url):
        raise ValueError("Only configured Asura URLs are allowed.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    return requests.get(
        url,
        headers=headers,
        timeout=20,
        allow_redirects=True,
    )


def build_asura_url_from_title(title: str) -> str:
    slug = slugify_title(title)
    template = get_asura_url_template()
    return template.format(slug=slug)


def find_latest_chapter_from_asura(title: str, local_latest_chapter=None, asura_url=None):
    """
    Main function for app integration.

    The app should call this with the existing series title from DB/current refresh loop.
    This function must not ask for input().
    """
    if not get_asura_enabled():
        return {
            "latest_chapter": None,
            "matched_title": None,
            "source": "asura",
            "source_url": None,
            "confidence": 0,
            "status": "disabled",
            "error": "ASURA_ENABLED is false",
            "debug": {},
        }

    attempted_url = asura_url or build_asura_url_from_title(title)

    try:
        response = fetch_asura_page_by_url(attempted_url)
    except Exception as e:
        return {
            "latest_chapter": None,
            "matched_title": None,
            "source": "asura",
            "source_url": attempted_url,
            "confidence": 0,
            "status": "error",
            "error": str(e),
            "debug": {},
        }

    if response.status_code != 200:
        return {
            "latest_chapter": None,
            "matched_title": None,
            "source": "asura",
            "source_url": response.url,
            "confidence": 0,
            "status": "error",
            "error": f"HTTP {response.status_code}",
            "debug": {},
        }

    page_html = response.text

    extracted_title = extract_title_from_html(page_html)
    latest_chapter, debug = extract_latest_chapter_from_asura_html(page_html)

    if latest_chapter is None and looks_blocked_or_invalid(page_html):
        return {
            "latest_chapter": None,
            "matched_title": extracted_title,
            "source": "asura",
            "source_url": response.url,
            "confidence": 0,
            "status": "blocked",
            "error": "Page looks blocked/protected. Not attempting bypass.",
            "debug": debug,
        }

    if latest_chapter is None:
        return {
            "latest_chapter": None,
            "matched_title": extracted_title,
            "source": "asura",
            "source_url": response.url,
            "confidence": 0,
            "status": "no_result",
            "error": "Could not find latest chapter number in page HTML.",
            "debug": debug,
        }

    confidence = fuzzy_score(title, extracted_title) if extracted_title else 0

    if confidence < 0.70:
        return {
            "latest_chapter": latest_chapter,
            "matched_title": extracted_title,
            "source": "asura",
            "source_url": response.url,
            "confidence": confidence,
            "status": "rejected",
            "error": "Extracted title does not confidently match requested title.",
            "debug": debug,
        }

    local_num = to_float(local_latest_chapter)
    latest_num = to_float(latest_chapter)

    if local_num is not None and latest_num is not None and latest_num < local_num:
        return {
            "latest_chapter": latest_chapter,
            "matched_title": extracted_title,
            "source": "asura",
            "source_url": response.url,
            "confidence": confidence,
            "status": "rejected",
            "error": "Asura latest chapter is lower than local chapter.",
            "debug": debug,
        }

    return {
        "latest_chapter": latest_chapter,
        "matched_title": extracted_title,
        "source": "asura",
        "source_url": response.url,
        "confidence": confidence,
        "status": "success",
        "error": None,
        "debug": debug,
    }
