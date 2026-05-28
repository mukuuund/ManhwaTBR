import requests
import difflib
from db import get_connection

ANILIST_URL = "https://graphql.anilist.co"
MANGADEX_API_URL = "https://api.mangadex.org"

def is_good_match(search_title, candidate_title):
    if not candidate_title:
        return False
    # Simple ratio check
    ratio = difflib.SequenceMatcher(None, search_title.lower(), candidate_title.lower()).ratio()
    return ratio > 0.6

def fetch_anilist_cover(title=None, anilist_id=None):
    if not title and not anilist_id:
        return None
        
    query = '''
    query ($search: String, $id: Int) {
      Media(search: $search, id: $id, type: MANGA) {
        id
        title {
          romaji
          english
          native
        }
        coverImage {
          extraLarge
          large
        }
      }
    }
    '''
    variables = {}
    if anilist_id:
        variables['id'] = int(anilist_id)
    else:
        variables['search'] = title
        
    try:
        response = requests.post(ANILIST_URL, json={'query': query, 'variables': variables}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            media = data.get("data", {}).get("Media")
            if media:
                titles = media.get("title", {})
                matched_title = titles.get("english") or titles.get("romaji") or titles.get("native") or ""
                
                # Check match if searching by title
                if not anilist_id and title and not is_good_match(title, matched_title):
                    return None
                    
                cover = media.get("coverImage", {})
                return cover.get("extraLarge") or cover.get("large")
    except Exception as e:
        print(f"AniList Error: {e}")
    return None

def fetch_mangadex_cover(title=None, mangadex_id=None):
    if not title and not mangadex_id:
        return None
        
    try:
        if mangadex_id:
            manga_id = mangadex_id
            response = requests.get(f"{MANGADEX_API_URL}/manga/{manga_id}?includes[]=cover_art", timeout=5)
            response.raise_for_status()
            data = response.json()
            manga = data.get("data")
        else:
            search_params = {
                "title": title,
                "limit": 1,
                "includes[]": ["cover_art"]
            }
            response = requests.get(f"{MANGADEX_API_URL}/manga", params=search_params, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                manga = data["data"][0]
                manga_id = manga.get("id")
                
                attrs = manga.get("attributes", {})
                titles = attrs.get("title", {})
                matched_title = titles.get("en") or next(iter(titles.values()), "")
                if not is_good_match(title, matched_title):
                    return None
            else:
                return None
                
        if manga:
            cover_filename = None
            for rel in manga.get("relationships", []):
                if rel.get("type") == "cover_art":
                    cover_filename = rel.get("attributes", {}).get("fileName")
                    break
            
            if cover_filename:
                return f"https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}"
                
    except Exception as e:
        print(f"MangaDex Error: {e}")
    return None

def resolve_cover_image(title, canonical=None, anilist_id=None, mangadex_id=None):
    # Try AniList by ID
    if anilist_id:
        cover = fetch_anilist_cover(anilist_id=anilist_id)
        if cover:
            print(f"Cover found from AniList (by ID) for {title}")
            return cover
            
    # Try AniList by Title
    cover = fetch_anilist_cover(title=title)
    if cover:
        print(f"Cover found from AniList for {title}")
        return cover
        
    # Try MangaDex by ID
    if mangadex_id:
        cover = fetch_mangadex_cover(mangadex_id=mangadex_id)
        if cover:
            print(f"Cover found from MangaDex (by ID) for {title}")
            return cover
            
    # Try MangaDex by Title
    cover = fetch_mangadex_cover(title=title)
    if cover:
        print(f"Cover found from MangaDex for {title}")
        return cover
        
    print(f"No cover found, using fallback for {title}")
    return None

def resolve_and_save_cover(series_id, title, canonical=None, anilist_id=None, mangadex_id=None):
    cover_image = resolve_cover_image(title, canonical, anilist_id, mangadex_id)
    if cover_image:
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("UPDATE series SET cover_image = %s WHERE id = %s", (cover_image, series_id))
                conn.commit()
                cur.close()
                conn.close()
        except Exception as e:
            print(f"Error saving cover for {title}: {e}")
    return cover_image
