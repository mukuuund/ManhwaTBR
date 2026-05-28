import re
import json
import requests
from bs4 import BeautifulSoup
import html
from urllib.parse import urlparse
from services.asura_metadata_service import fuzzy_score, to_float, format_chapter_number, find_comicseries_objects

def extract_generic_title(soup):
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw: continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        
        for item in find_comicseries_objects(data):
            if item.get("name"):
                return html.unescape(str(item.get("name"))).strip()
                
        # Fallback to Article headline
        if isinstance(data, dict) and data.get("@type") == "Article":
            if data.get("headline"):
                return html.unescape(str(data.get("headline"))).strip()
                
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
        
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()
        
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(" ", strip=True).strip()
        
    return None

def extract_generic_metadata_from_html(page_html: str):
    soup = BeautifulSoup(page_html, "html.parser")
    title = extract_generic_title(soup)
    
    candidates = []
    
    # 1. JSON-LD ComicSeries.numberOfEpisodes
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw: continue
        try:
            data = json.loads(raw)
            for item in find_comicseries_objects(data):
                num = to_float(item.get("numberOfEpisodes"))
                if num is not None:
                    candidates.append(num)
        except json.JSONDecodeError:
            continue
            
    # 3. Visible text patterns
    text = soup.get_text(" ", strip=True)
    
    # Pattern: "Chapter 123", "123 Chapters", "Latest Chapter 123"
    matches = re.finditer(r"\b(?:Latest\s+)?Chapter\s+(\d+(?:\.\d+)?)\b", text, flags=re.IGNORECASE)
    for m in matches:
        num = to_float(m.group(1))
        if num is not None and 0 < num < 1000: # Ignore year-like values unless explicitly matched? Wait, we just filter 1000 to be safe
            candidates.append(num)
            
    matches2 = re.finditer(r"\b(\d+(?:\.\d+)?)\s+Chapters?\b", text, flags=re.IGNORECASE)
    for m in matches2:
        num = to_float(m.group(1))
        if num is not None and 0 < num < 1000:
            candidates.append(num)
            
    if not candidates:
        return title, None
        
    # Pick max of valid ones
    return title, format_chapter_number(max(candidates))

def fetch_generic_page(url: str):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    return requests.get(url, headers=headers, timeout=20, allow_redirects=True)

def find_latest_chapter_from_generic(title: str, url: str, local_latest_chapter=None):
    try:
        response = fetch_generic_page(url)
    except Exception as e:
        return {
            "latest_chapter": None,
            "matched_title": None,
            "source": "generic_metadata",
            "source_url": url,
            "confidence": 0,
            "status": "error",
            "error": str(e)
        }
        
    if response.status_code != 200:
        return {
            "latest_chapter": None,
            "matched_title": None,
            "source": "generic_metadata",
            "source_url": response.url,
            "confidence": 0,
            "status": "error",
            "error": f"HTTP {response.status_code}"
        }
        
    # Basic check if it's a search result page, just reject if we see too many "search" keywords?
    # Actually, we rely on confidence score and latest chapter.
    
    extracted_title, latest_chapter = extract_generic_metadata_from_html(response.text)
    
    if latest_chapter is None:
        return {
            "latest_chapter": None,
            "matched_title": extracted_title,
            "source": "generic_metadata",
            "source_url": response.url,
            "confidence": 0,
            "status": "no_result",
            "error": "Could not find latest chapter number in generic page HTML."
        }
        
    confidence = fuzzy_score(title, extracted_title) if extracted_title else 0
    
    if confidence < 0.70:
        return {
            "latest_chapter": latest_chapter,
            "matched_title": extracted_title,
            "source": "generic_metadata",
            "source_url": response.url,
            "confidence": confidence,
            "status": "rejected",
            "error": "Extracted title does not confidently match requested title."
        }
        
    local_num = to_float(local_latest_chapter)
    latest_num = to_float(latest_chapter)
    
    if local_num is not None and latest_num is not None and latest_num < local_num:
        return {
            "latest_chapter": latest_chapter,
            "matched_title": extracted_title,
            "source": "generic_metadata",
            "source_url": response.url,
            "confidence": confidence,
            "status": "rejected",
            "error": "Generic latest chapter is lower than local chapter."
        }
        
    return {
        "latest_chapter": latest_chapter,
        "matched_title": extracted_title,
        "source": "generic_metadata",
        "source_url": response.url,
        "confidence": confidence,
        "status": "success",
        "error": None
    }
