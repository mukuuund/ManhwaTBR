from db import get_connection
from services.mangadex_service import find_latest_chapter_for_title
from services.anilist_service import fetch_metadata_for_title

from datetime import datetime
from services.title_parser import canonicalize_title
import json

def choose_best_remote_chapter(local_latest, anilist_total, md_latest, md_conf, external_result=None):
    local_latest = local_latest or 0.0
    
    # Identify valid API candidates
    md_valid = (md_latest is not None) and (md_conf >= 0.75)
    ani_valid = (anilist_total is not None)
    
    selected_api_source = None
    selected_api_chapter = None
    selected_api_conf = None
    
    if md_valid and ani_valid:
        if md_latest >= anilist_total:
            selected_api_source = "mangadex"
            selected_api_chapter = md_latest
            selected_api_conf = md_conf
        else:
            selected_api_source = "anilist metadata"
            selected_api_chapter = anilist_total
            selected_api_conf = 0.65
    elif md_valid:
        selected_api_source = "mangadex"
        selected_api_chapter = md_latest
        selected_api_conf = md_conf
    elif ani_valid:
        selected_api_source = "anilist metadata"
        selected_api_chapter = anilist_total
        selected_api_conf = 0.65
        
    debug_api_selected = selected_api_source
    debug_api_chapter = selected_api_chapter
        
    # Check if selected API source is sufficient
    if selected_api_chapter is not None and selected_api_chapter >= local_latest:
        return {
            "remote_latest_chapter": selected_api_chapter,
            "remote_source": selected_api_source,
            "remote_confidence": selected_api_conf,
            "remote_link": None, # Will be set below based on source
            "needs_review": False,
            "review_reason": None,
            "debug_api_selected": debug_api_selected,
            "debug_api_chapter": debug_api_chapter,
            "external_debug": {
                "resolver_called": False,
                "reason_for_calling": "External resolver was not called because selected API chapter was considered valid."
            }
        }
        
    # If we get here, API sources failed or are behind local
    if external_result and external_result.get("status") == "success":
        return {
            "remote_latest_chapter": external_result["latest_chapter"],
            "remote_source": external_result.get("provider_display_name") or ("generic metadata" if external_result["source"] == "generic_metadata" else ("asura metadata" if external_result["source"] == "asura" else external_result["source"])),
            "remote_confidence": external_result["confidence"],
            "remote_link": external_result["source_url"],
            "needs_review": False,
            "review_reason": None,
            "debug_api_selected": debug_api_selected,
            "debug_api_chapter": debug_api_chapter,
            "external_result": external_result,
            "external_debug": external_result.get("external_debug")
        }
        
    # Both APIs and External failed or are behind
    reason = "No valid AniList/MangaDex chapter found." if selected_api_chapter is None else "Best AniList/MangaDex chapter is still lower than local chapter."
    
    if external_result and external_result.get("error"):
        reason = external_result["error"]
        
    return {
        "remote_latest_chapter": None,
        "remote_source": None,
        "remote_confidence": 0.0,
        "remote_link": None,
        "needs_review": True,
        "review_reason": reason,
        "debug_api_selected": debug_api_selected,
        "debug_api_chapter": debug_api_chapter,
        "external_result": external_result,
        "external_debug": external_result.get("external_debug") if external_result else None
    }

def update_remote_latest_chapters(series_list=None, force=False):
    conn = get_connection()
    if not conn:
        return {"status": "error", "message": "Database connection failed."}
        
    cur = conn.cursor(dictionary=True)
    
    if not series_list:
        cur.execute("SELECT * FROM series")
        series_list = cur.fetchall()
        
    if not series_list:
        cur.close()
        conn.close()
        return {"status": "success", "message": "No series found.", "count": 0}
        
    rows = []
    
    summary = {
        "updated_count": 0,
        "update_available_count": 0,
        "needs_review_count": 0,
        "mangadex_latest_found_count": 0,
        "anilist_chapters_found_count": 0,
        "mangadex_selected_count": 0,
        "anilist_selected_count": 0,
        "higher_source_selected_count": 0,
        "best_api_source_below_local_count": 0,
        "external_resolver_called_count": 0,
        "external_search_attempted_count": 0,
        "external_search_disabled_count": 0,
        "external_candidate_url_count": 0,
        "external_candidate_rejected_count": 0,
        "external_used_count": 0,
        "asura_direct_attempted_count": 0,
        "asura_direct_used_count": 0,
        "generic_extractor_attempted_count": 0,
        "generic_extractor_used_count": 0,
        "mangaupdates_used_count": 0,
        "manual_override_count": 0,
        "errors": [],
        "debug": []
    }
    
    for series in series_list:
        try:
            title = series['title']
            canon = series['canonical']
            local_latest = float(series.get('local_latest_chapter') or 0.0)
            
            if series.get('remote_source') == 'manual' and not force:
                summary['manual_override_count'] += 1
                continue
                
            # 1. Fetch from MangaDex
            md_result = find_latest_chapter_for_title(title)
            md_latest = md_result['latest_chapter']
            md_conf = md_result['confidence']
            md_id = md_result['mangadex_id']
            md_url = md_result['source_url']
            md_matched_title = md_result.get('matched_title')
            
            if md_latest is not None:
                summary["mangadex_latest_found_count"] += 1
            
            # 2. Fetch metadata using AniList
            ani_data = fetch_metadata_for_title(title)
            anilist_id = None
            anilist_total = None
            anilist_status = None
            anilist_url = None
            ani_matched_title = None
            
            if ani_data:
                cur.execute("SELECT id FROM manhwa_meta WHERE LOWER(display) = %s OR LOWER(search_title) = %s", (canon, canon))
                meta_exists = cur.fetchone()
                
                if not meta_exists:
                    cur.execute("""
                        INSERT INTO manhwa_meta (search_title, display, status, chapters_total, genres, description)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        ani_data['search_title'], ani_data['display'], ani_data['status'],
                        ani_data['chapters'], json.dumps(ani_data['genres']), ani_data['description']
                    ))
                else:
                    cur.execute("""
                        UPDATE manhwa_meta SET status=%s, chapters_total=%s, genres=%s, description=%s, updated_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                    """, (
                        ani_data['status'], ani_data['chapters'], json.dumps(ani_data['genres']), 
                        ani_data['description'], meta_exists['id']
                    ))
                    
                anilist_id = str(ani_data.get('id')) if ani_data.get('id') else None
                anilist_total = ani_data.get('chapters')
                anilist_status = ani_data.get('status')
                anilist_url = ani_data.get('siteUrl')
                ani_matched_title = ani_data.get('display')
                if anilist_total is not None:
                    summary["anilist_chapters_found_count"] += 1
                
            # 3. Quick check if API chapters are below local or missing to trigger Asura
            selected_api_ch = None
            valid_md = (md_latest is not None and md_conf >= 0.75)
            valid_ani = (anilist_total is not None)
            if valid_md and valid_ani:
                selected_api_ch = max(md_latest, anilist_total)
            elif valid_md:
                selected_api_ch = md_latest
            elif valid_ani:
                selected_api_ch = anilist_total
                
            needs_asura = False
            asura_attempted = False
            external_result = None
            
            if selected_api_ch is None or selected_api_ch < local_latest:
                needs_asura = True
                if selected_api_ch is not None and selected_api_ch < local_latest:
                    summary["best_api_source_below_local_count"] += 1
            else:
                summary["higher_source_selected_count"] += 1
                    
            if needs_asura:
                from services.latest_chapter_resolver import resolve_latest_chapter_from_external_sources
                asura_attempted = True
                external_result = resolve_latest_chapter_from_external_sources(title, local_latest, series.get('asura_url'))
                summary['external_resolver_called_count'] += 1
                
            # 4. Choose best remote chapter
            best_choice = choose_best_remote_chapter(
                local_latest, anilist_total, md_latest, md_conf, external_result
            )
            
            if external_result:
                debug_info = external_result.get("external_debug", {})
                if debug_info.get("search_attempted"):
                    summary["external_search_attempted_count"] += 1
                if not debug_info.get("search_enabled") or not debug_info.get("serpapi_key_present"):
                    summary["external_search_disabled_count"] += 1
                
                cands = debug_info.get("candidate_results", [])
                summary["external_candidate_url_count"] += len(cands)
                summary["external_candidate_rejected_count"] += len([c for c in cands if c.get("status") != "success"])
                
                if debug_info.get("asura_slug_url_attempted"):
                    summary["asura_direct_attempted_count"] += 1
                
                # count generic extractor attempted if any candidate result is from generic metadata
                if any(c.get("provider") == "generic_metadata" for c in cands):
                    summary["generic_extractor_attempted_count"] += 1

            # Link fixup & stats
            if best_choice['remote_source'] == 'mangadex':
                best_choice['remote_link'] = md_url
                summary["mangadex_selected_count"] += 1
            elif best_choice['remote_source'] == 'anilist metadata':
                best_choice['remote_link'] = anilist_url
                summary["anilist_selected_count"] += 1
            elif best_choice['remote_source'] == 'Asura metadata':
                summary["external_used_count"] += 1
                summary["asura_direct_used_count"] += 1
            elif best_choice['remote_source'] == 'MangaUpdates metadata':
                summary["external_used_count"] += 1
                summary["mangaupdates_used_count"] += 1
            elif external_result and external_result.get("status") == "success":
                summary["external_used_count"] += 1
                if external_result.get("source") == "generic_metadata":
                    summary["generic_extractor_used_count"] += 1
                
            # Compute chapters behind
            chapters_behind = None
            remote_latest = best_choice['remote_latest_chapter']
            if remote_latest is not None and remote_latest >= local_latest:
                chapters_behind = float(remote_latest) - float(local_latest)
                if chapters_behind > 0:
                    summary["update_available_count"] += 1
            else:
                chapters_behind = None
                
            if best_choice['needs_review']:
                summary["needs_review_count"] += 1
                
            summary["updated_count"] += 1
            
            # Debug log format
            summary["debug"].append({
                "title": title,
                "local_latest_chapter": local_latest,
                "anilist_total_chapters": anilist_total,
                "mangadex_latest_chapter": md_latest,
                "selected_api_source": best_choice['debug_api_selected'],
                "selected_api_chapter": best_choice['debug_api_chapter'],
                "selected_api_chapter >= local_latest_chapter?": (best_choice['debug_api_chapter'] >= local_latest if best_choice['debug_api_chapter'] is not None else False),
                "external_discovery_attempted": asura_attempted,
                "external_final_url": external_result['source_url'] if external_result else None,
                "external_latest_chapter": external_result['latest_chapter'] if external_result else None,
                "external_confidence": external_result['confidence'] if external_result else None,
                "final_remote_source": best_choice['remote_source'],
                "final_remote_latest_chapter": remote_latest,
                "needs_review": best_choice['needs_review'],
                "review_reason": best_choice['review_reason']
            })
            
            asura_url_val = external_result['source_url'] if external_result and external_result.get('source') == 'asura' else None
            asura_latest_val = external_result['latest_chapter'] if external_result and external_result.get('source') == 'asura' else None
            asura_conf_val = external_result['confidence'] if external_result and external_result.get('source') == 'asura' else None
            asura_status_val = external_result['status'] if external_result and external_result.get('source') == 'asura' else None
            asura_error_val = external_result['error'] if external_result and external_result.get('source') == 'asura' else None

            generic_url_val = external_result['source_url'] if external_result else None
            generic_latest_val = external_result['latest_chapter'] if external_result else None
            generic_conf_val = external_result['confidence'] if external_result else None
            generic_status_val = external_result['status'] if external_result else None
            generic_error_val = json.dumps(best_choice.get("external_debug")) if best_choice.get("external_debug") else None

            
            rows.append((
                anilist_id, anilist_total, anilist_status, anilist_url,
                md_id, md_latest, md_url, md_conf,
                asura_url_val, asura_latest_val, asura_conf_val, asura_status_val, asura_error_val,
                generic_latest_val, external_result['source'] if external_result else None, generic_url_val, generic_conf_val, generic_status_val, generic_error_val, # generic scraped fields
                remote_latest, best_choice['remote_source'], best_choice['remote_link'], best_choice['remote_confidence'],
                chapters_behind, best_choice['needs_review'], best_choice['review_reason'],
                canon
            ))
            
        except Exception as e:
            summary["errors"].append(f"Error processing {series.get('title')}: {str(e)}")
        
    if rows:
        cur.executemany("""
            UPDATE series
            SET anilist_id = %s,
                anilist_total_chapters = %s,
                anilist_status = %s,
                anilist_site_url = %s,
                mangadex_id = %s,
                mangadex_latest_chapter = %s,
                mangadex_url = %s,
                mangadex_confidence = %s,
                asura_url = %s,
                asura_latest_chapter = %s,
                asura_confidence = %s,
                asura_status = %s,
                asura_error = %s,
                asura_seen_at = CURRENT_TIMESTAMP,
                scraped_latest_chapter = %s,
                scraped_source = %s,
                scraped_url = %s,
                scraped_confidence = %s,
                scraped_status = %s,
                scraped_error = %s,
                scraped_seen_at = CURRENT_TIMESTAMP,
                remote_latest_chapter = %s,
                remote_source = %s,
                remote_link = %s,
                remote_confidence = %s,
                remote_seen_at = CURRENT_TIMESTAMP,
                chapters_behind = %s,
                needs_review = %s,
                review_reason = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE canonical = %s
        """, rows)
        conn.commit()
        
    cur.close()
    conn.close()
    
    return {
        "status": "success", 
        "message": f"Updated {summary['updated_count']} series. {summary['update_available_count']} updates found. {summary['needs_review_count']} need review.", 
        "summary": summary
    }
