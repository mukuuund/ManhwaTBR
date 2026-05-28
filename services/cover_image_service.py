import requests
from db import get_connection
from services.anilist_service import fetch_metadata_for_title
from services.mangadex_service import search_manga

MANGADEX_API_URL = "https://api.mangadex.org"

# Basic in-memory cache for one recommendation run
_cover_cache = {}

def clear_cover_cache():
    global _cover_cache
    _cover_cache.clear()

def extract_mangadex_cover_url(manga_id, relationships):
    for rel in relationships:
        if rel.get('type') == 'cover_art' and 'attributes' in rel and 'fileName' in rel['attributes']:
            filename = rel['attributes']['fileName']
            return f"https://uploads.mangadex.org/covers/{manga_id}/{filename}.512.jpg"
    return None

def fetch_mangadex_cover_by_id(mangadex_id):
    try:
        res = requests.get(f"{MANGADEX_API_URL}/manga/{mangadex_id}", params={
            "includes[]": "cover_art"
        }, timeout=10)
        if res.status_code == 200:
            data = res.json().get("data", {})
            return extract_mangadex_cover_url(mangadex_id, data.get("relationships", []))
    except Exception as e:
        print(f"Error fetching MangaDex cover for ID {mangadex_id}: {e}")
    return None

def fetch_mangadex_cover_by_title(title):
    results = search_manga(title)
    if not results:
        return None
    
    # search_manga doesn't include cover_art by default, so we take the first/best match and query it
    best_match = results[0]
    manga_id = best_match.get("id")
    if manga_id:
        return fetch_mangadex_cover_by_id(manga_id)
    return None

def resolve_cover_image(title, canonical, anilist_id=None, mangadex_id=None):
    cache_key = canonical or title
    if cache_key in _cover_cache:
        return _cover_cache[cache_key]

    # 1. Check local DB (trending_manhwa) first
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT cover_image FROM trending_manhwa WHERE canonical = %s AND cover_image IS NOT NULL LIMIT 1", (canonical,))
            row = cur.fetchone()
            if row and row['cover_image']:
                _cover_cache[cache_key] = row['cover_image']
                cur.close()
                conn.close()
                return row['cover_image']
        except Exception as e:
            print(f"DB check failed for cover image of {canonical}: {e}")
        finally:
            if conn:
                try: cur.close()
                except: pass
                conn.close()

    # 2. Try AniList
    print(f"Fetching cover for {title} from AniList...")
    ani_data = fetch_metadata_for_title(title, anilist_id)
    if ani_data and ani_data.get("cover"):
        cover = ani_data["cover"]
        print(f"Found AniList cover for {title}")
        _cover_cache[cache_key] = cover
        
        # Optional DB caching
        if canonical:
            conn2 = get_connection()
            if conn2:
                try:
                    cur2 = conn2.cursor()
                    cur2.execute("UPDATE trending_manhwa SET cover_image = %s WHERE canonical = %s", (cover, canonical))
                    conn2.commit()
                except Exception as e:
                    print(f"Failed to cache AniList cover image in DB for {canonical}: {e}")
                finally:
                    try: cur2.close()
                    except: pass
                    conn2.close()
                    
        return cover
    else:
        print(f"AniList cover missing for {title}")

    # 3. Try MangaDex
    print(f"Fetching cover for {title} from MangaDex...")
    md_cover = None
    if mangadex_id:
        md_cover = fetch_mangadex_cover_by_id(mangadex_id)
    else:
        md_cover = fetch_mangadex_cover_by_title(title)
        
    final_cover = md_cover
    if final_cover:
        print(f"Found MangaDex cover for {title}")
    else:
        print(f"MangaDex cover missing for {title}")
        print(f"No cover found for {title}")
        
    _cover_cache[cache_key] = final_cover
    
    # Optional DB caching
    if final_cover and canonical:
        conn = get_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("UPDATE trending_manhwa SET cover_image = %s WHERE canonical = %s", (final_cover, canonical))
                conn.commit()
            except Exception as e:
                print(f"Failed to cache cover image in DB for {canonical}: {e}")
            finally:
                if conn:
                    try: cur.close()
                    except: pass
                    conn.close()
                    
    return final_cover
