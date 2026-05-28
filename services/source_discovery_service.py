import requests
from config import Config
from urllib.parse import urlparse

def discover_candidate_urls(query: str, max_results: int = 10):
    if not getattr(Config, 'SEARCH_ENABLED', True):
        return {"status": "disabled", "error": "SEARCH_ENABLED is false"}
    
    api_key = getattr(Config, 'SERPAPI_API_KEY', None)
    if not api_key:
        return {"status": "disabled", "error": "SERPAPI_API_KEY is missing"}

    engine = getattr(Config, 'SERPAPI_ENGINE', 'google_light')
    
    params = {
        "engine": engine,
        "q": query,
        "api_key": api_key,
        "num": max_results
    }
    
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
            organic = data.get("organic_results", [])
            
            valid_urls = []
            rejected_urls = []
            
            seen = set()
            for item in organic:
                link = item.get("link", "")
                
                if link in seen:
                    continue
                seen.add(link)
                
                if not link.startswith("http"):
                    rejected_urls.append({"url": link, "reason": "non-http URL"})
                    continue
                    
                domain = urlparse(link).netloc.lower()
                social_domains = ["reddit.com", "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "x.com", "twitter.com", "pinterest.com"]
                if any(sd in domain for sd in social_domains):
                    rejected_urls.append({"url": link, "reason": "Social media domain"})
                    continue
                    
                if "cdn" in link.lower() or link.lower().endswith((".jpg", ".png", ".webp", ".jpeg", ".gif")):
                    rejected_urls.append({"url": link, "reason": "image/CDN"})
                    continue
                    
                # Provider specific filters
                domain = urlparse(link).netloc.lower()
                is_asura = "asurascans.com" in domain or "asuracomic.net" in domain
                
                if "/chapter/" in link.lower() or "-chapter-" in link.lower() or "/ch-" in link.lower():
                    rejected_urls.append({"url": link, "reason": "/chapter/ URL"})
                    continue
                    
                if is_asura and "/comics/" not in link.lower():
                    rejected_urls.append({"url": link, "reason": "Asura URL without /comics/"})
                    continue
                    
                valid_urls.append(link)
            
            return {
                "status": "success",
                "query_used": query,
                "candidate_urls": valid_urls[:max_results],
                "rejected_urls": rejected_urls,
                "results": organic
            }
        else:
            return {"status": "error", "error": f"HTTP {res.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
