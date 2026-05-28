from config import Config
from services.source_discovery_service import discover_candidate_urls
from services.asura_metadata_service import find_latest_chapter_from_asura, build_asura_url_from_title
from services.generic_metadata_service import find_latest_chapter_from_generic
from urllib.parse import urlparse

def resolve_latest_chapter_from_external_sources(title: str, local_latest_chapter: float, saved_url: str = None):
    debug = {
        "resolver_called": True,
        "reason_for_calling": "API chapters missing or below local chapter.",
        "search_enabled": getattr(Config, 'SEARCH_ENABLED', True),
        "search_provider": getattr(Config, 'SEARCH_PROVIDER', 'serpapi_google_light'),
        "serpapi_key_present": bool(getattr(Config, 'SERPAPI_API_KEY', None)),
        "asura_enabled": False,
        "saved_url_attempted": saved_url,
        "saved_url_status": None,
        "asura_slug_url_attempted": None,
        "asura_slug_status": None,
        "asura_latest_chapter": None,
        "asura_confidence": None,
        "asura_error": None,
        "search_attempted": False,
        "search_queries": [],
        "candidate_urls_found": [],
        "candidate_urls_after_filter": [],
        "url_filter_rejections": [],
        "candidate_results": [],
        "final_external_status": "no_result",
        "final_external_source": None,
        "final_external_chapter": None,
        "final_external_error": None,
        "rejection_summary": {
            "direct_asura_error": None,
            "candidate_urls_found": 0,
            "candidate_urls_after_filter": 0,
            "rejected_title_mismatch_count": 0,
            "rejected_below_local_count": 0,
            "rejected_no_chapter_count": 0
        }
    }

    results = []

    # 1. Try saved URL
    if saved_url:
        res = evaluate_url(title, saved_url, local_latest_chapter)
        if res:
            res["discovered_by"] = "saved_url"
            debug["saved_url_status"] = res["status"]
            cand_res = make_candidate_result(saved_url, res)
            debug["candidate_results"].append(cand_res)
            
            if res["status"] == "success":
                return finalize_result(res, debug, "Saved URL found valid chapter.")
            results.append(res)

    # 2. Try generated Asura URL
    asura_enabled = next((p for p in Config.LATEST_CHAPTER_PROVIDERS if p["name"] == "asura" and p["enabled"]), None)
    if asura_enabled:
        debug["asura_enabled"] = True
        asura_url = build_asura_url_from_title(title)
        debug["asura_slug_url_attempted"] = asura_url
        res = find_latest_chapter_from_asura(title, local_latest_chapter, asura_url)
        
        debug["asura_slug_status"] = res["status"]
        debug["asura_latest_chapter"] = res.get("latest_chapter")
        debug["asura_confidence"] = res.get("confidence")
        debug["asura_error"] = res.get("error")
        debug["rejection_summary"]["direct_asura_error"] = res.get("error")
        
        cand_res = make_candidate_result(asura_url, res, provider="asura")
        debug["candidate_results"].append(cand_res)

        if res and res["status"] == "success":
            res["discovered_by"] = "generated_asura_slug"
            return finalize_result(res, debug, None)
            
        results.append(res)

    # 3. Source Discovery Fallback (Broader queries)
    if debug["search_enabled"] and debug["serpapi_key_present"]:
        debug["search_attempted"] = True
        
        queries = [
            f'site:asurascans.com/comics "{title}"',
            f'"{title}" "Chapter" "manhwa"',
            f'"{title}" "latest chapter"',
            f'"{title}" "read manhwa"'
        ]
        
        for q in queries:
            debug["search_queries"].append(q)
            discovery = discover_candidate_urls(q)
            
            if discovery.get("status") == "success":
                all_found = discovery.get("results", [])
                debug["candidate_urls_found"].extend([r.get("link") for r in all_found])
                debug["rejection_summary"]["candidate_urls_found"] += len(all_found)
                
                debug["url_filter_rejections"].extend(discovery.get("rejected_urls", []))
                
                urls = discovery.get("candidate_urls", [])
                debug["candidate_urls_after_filter"].extend(urls)
                debug["rejection_summary"]["candidate_urls_after_filter"] += len(urls)
                
                for candidate_url in urls:
                    res = evaluate_url(title, candidate_url, local_latest_chapter)
                    if res:
                        res["discovered_by"] = Config.SEARCH_PROVIDER
                        cand_res = make_candidate_result(candidate_url, res)
                        debug["candidate_results"].append(cand_res)
                        results.append(res)
                        
                        update_rejection_summary(debug["rejection_summary"], res)
                        
                        if res["status"] == "success":
                            return finalize_result(res, debug, None)

    # 4. Determine final reason if all failed
    reason = "No reliable external source found."
    if debug["search_attempted"]:
        if debug["rejection_summary"]["candidate_urls_found"] > 0:
            if debug["rejection_summary"]["candidate_urls_after_filter"] == 0:
                reason = "Asura direct URL failed. Search discovery found candidates, but all were rejected during URL filtering."
            else:
                reason = "Asura direct URL failed. Search discovery found candidates, but all were rejected."
        else:
            reason = "No reliable external source found after Asura and broad search discovery."
    else:
        if not debug["search_enabled"]:
            reason = "SerpApi disabled: SEARCH_ENABLED=false"
        elif not debug["serpapi_key_present"]:
            reason = "SerpApi disabled: missing SERPAPI_API_KEY"

    return {
        "status": "no_result",
        "source": None,
        "latest_chapter": None,
        "source_url": None,
        "confidence": 0,
        "discovered_by": None,
        "error": reason,
        "external_debug": debug,
        "rejection_summary": debug["rejection_summary"]
    }


def make_candidate_result(url, res, provider=None):
    return {
        "url": url,
        "provider": provider or res.get("source"),
        "status": res["status"],
        "matched_title": res.get("matched_title"),
        "title_confidence": res.get("confidence"),
        "latest_chapter": res.get("latest_chapter"),
        "rejection_reason": res.get("error")
    }

def update_rejection_summary(summary, res):
    err = str(res.get("error") or "")
    if "match requested title" in err:
        summary["rejected_title_mismatch_count"] += 1
    elif "lower than local chapter" in err:
        summary["rejected_below_local_count"] += 1
    elif "Could not find latest chapter number" in err:
        summary["rejected_no_chapter_count"] += 1

def finalize_result(res, debug, custom_reason):
    source_val = res.get("source")
    url_val = res.get("source_url") or ""
    
    if "mangaupdates.com" in url_val:
        source_val = "mangaupdates"
        provider_display_name = "MangaUpdates metadata"
    else:
        provider_display_name = "Generic metadata" if source_val == "generic_metadata" else ("Asura metadata" if source_val == "asura" else str(source_val))
        
    res["source"] = source_val
    res["provider_display_name"] = provider_display_name
    
    debug["final_external_status"] = res["status"]
    debug["final_external_source"] = source_val
    debug["final_external_chapter"] = res["latest_chapter"]
    debug["final_external_error"] = res.get("error") or custom_reason
    res["external_debug"] = debug
    res["rejection_summary"] = debug.get("rejection_summary", {})
    return res

def evaluate_url(title: str, url: str, local_latest_chapter: float):
    try:
        domain = urlparse(url).netloc
    except Exception:
        return None
        
    provider_type = "generic_metadata"
    for p in Config.LATEST_CHAPTER_PROVIDERS:
        if p["enabled"] and p["domain"] != "*" and p["domain"] in domain:
            provider_type = p["type"]
            break
            
    # Generic extractor requires the generic provider to be enabled
    generic_enabled = next((p for p in Config.LATEST_CHAPTER_PROVIDERS if p["name"] == "generic" and p["enabled"]), None)
            
    if provider_type == "asura":
        return find_latest_chapter_from_asura(title, local_latest_chapter, url)
    elif provider_type == "generic_metadata" and generic_enabled:
        return find_latest_chapter_from_generic(title, url, local_latest_chapter)
    else:
        return {
            "status": "rejected",
            "source": provider_type,
            "latest_chapter": None,
            "confidence": 0,
            "matched_title": None,
            "error": f"Provider {provider_type} is not enabled or supported."
        }
