import requests
import time
from difflib import SequenceMatcher
from services.title_parser import canonicalize_title

MANGADEX_API_URL = "https://api.mangadex.org"

def search_manga(title):
    try:
        res = requests.get(f"{MANGADEX_API_URL}/manga", params={
            "title": title,
            "limit": 5,
            "order[relevance]": "desc"
        }, timeout=10)
        res.raise_for_status()
        data = res.json()
        return data.get("data", [])
    except Exception as e:
        print(f"MangaDex search error for '{title}': {e}")
        return []

def get_latest_chapter(manga_id, translated_language="en"):
    max_ch = None
    offset = 0
    limit = 100
    max_pages = 10 # 1000 chapters max to prevent infinite loops
    
    for page in range(max_pages):
        try:
            res = requests.get(f"{MANGADEX_API_URL}/manga/{manga_id}/feed", params={
                "translatedLanguage[]": translated_language,
                "order[chapter]": "desc",
                "limit": limit,
                "offset": offset
            }, timeout=10)
            res.raise_for_status()
            data = res.json()
            chapters = data.get("data", [])
            
            if not chapters:
                break
            
            for ch in chapters:
                attrs = ch.get("attributes", {})
                ch_str = attrs.get("chapter")
                if ch_str:
                    try:
                        ch_num = float(ch_str)
                        if max_ch is None or ch_num > max_ch:
                            max_ch = ch_num
                    except ValueError:
                        pass
            
            total = data.get("total", 0)
            offset += limit
            if offset >= total:
                break
                
            time.sleep(0.3) # respect rate limit
            
        except Exception as e:
            print(f"MangaDex chapter error for ID '{manga_id}': {e}")
            break
            
    return max_ch

def find_latest_chapter_for_title(title):
    results = search_manga(title)
    if not results:
        return {
            "title": title,
            "mangadex_id": None,
            "latest_chapter": None,
            "source": "mangadex",
            "source_url": None,
            "confidence": 0.0,
            "matched_title": None,
            "warnings": ["No results found on MangaDex"]
        }
        
    canon_target = canonicalize_title(title)
    best_match = None
    best_confidence = 0.0
    matched_title_str = None
    
    for manga in results:
        attrs = manga.get("attributes", {})
        md_title_dict = attrs.get("title", {})
        md_title = list(md_title_dict.values())[0] if md_title_dict else ""
        
        canon_md = canonicalize_title(md_title)
        
        # Check title
        if canon_md == canon_target:
            best_match = manga
            best_confidence = 1.0
            matched_title_str = md_title
            break
            
        # Check alt titles
        alt_titles = attrs.get("altTitles", [])
        for alt in alt_titles:
            alt_str = list(alt.values())[0]
            if canonicalize_title(alt_str) == canon_target:
                best_match = manga
                best_confidence = 0.95
                matched_title_str = alt_str
                break
                
        if best_match:
            break
            
    if not best_match:
        # fuzzy matching fallback
        best_ratio = 0.0
        for manga in results:
            attrs = manga.get("attributes", {})
            md_title_dict = attrs.get("title", {})
            md_title = list(md_title_dict.values())[0] if md_title_dict else ""
            canon_md = canonicalize_title(md_title)
            ratio = SequenceMatcher(None, canon_target, canon_md).ratio()
            
            alt_titles = attrs.get("altTitles", [])
            for alt in alt_titles:
                alt_str = list(alt.values())[0]
                alt_ratio = SequenceMatcher(None, canon_target, canonicalize_title(alt_str)).ratio()
                if alt_ratio > ratio:
                    ratio = alt_ratio
                    md_title = alt_str
                    
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = manga
                matched_title_str = md_title
                
        best_confidence = best_ratio


    mangadex_id = best_match.get("id")
    latest_chapter = get_latest_chapter(mangadex_id)
    
    return {
        "title": title,
        "mangadex_id": mangadex_id,
        "latest_chapter": latest_chapter,
        "source": "mangadex",
        "source_url": f"https://mangadex.org/title/{mangadex_id}",
        "confidence": best_confidence,
        "matched_title": matched_title_str,
        "warnings": [] if latest_chapter is not None else ["Could not parse latest chapter"]
    }
