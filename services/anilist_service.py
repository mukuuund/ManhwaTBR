import requests
import re
import html

def clean_description(raw: str) -> str:
    if not raw:
        return ""
    s = raw
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?(i|b|em|strong|spoiler)>", "", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)     # strip remaining tags
    s = html.unescape(s)              # &amp; -> &
    s = re.sub(r"\s{2,}", " ", s.replace("\r", "").strip())
    return s.strip()

def fetch_metadata_for_title(title: str, anilist_id: int = None):
    url = 'https://graphql.anilist.co'
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    
    if anilist_id:
        query = '''
        query ($id: Int) {
          Media(id: $id, type: MANGA) {
            id siteUrl title { romaji english } status chapters genres
            description averageScore popularity coverImage { extraLarge large }
          }
        }
        '''
        variables = {"id": anilist_id}
    else:
        query = '''
        query ($search: String) {
          Media(search: $search, type: MANGA) {
            id siteUrl title { romaji english } status chapters genres
            description averageScore popularity coverImage { extraLarge large }
          }
        }
        '''
        variables = {"search": title}
        
    try:
        resp = requests.post(url, json={"query": query, "variables": variables}, headers=headers, timeout=20)
        js = resp.json()
        media = (js.get("data") or {}).get("Media")
        if not media:
            return None
        return normalize_anilist_response(media, title)
    except Exception as e:
        print(f"AniList metadata fetch failed for {title or anilist_id}: {e}")
        return None

def fetch_trending_manhwa(limit=20):
    url = "https://graphql.anilist.co"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    query = """
    query TrendingManhwa($page: Int = 1, $perPage: Int = 20) {
      Page(page: $page, perPage: $perPage) {
        media(
          type: MANGA
          countryOfOrigin: KR
          status: RELEASING
          isAdult: false
          sort: TRENDING_DESC
        ) {
          id
          siteUrl
          title { romaji english native }
          status
          chapters
          genres
          averageScore
          popularity
          favourites
          updatedAt
          coverImage { large }
          description
        }
      }
    }
    """
    variables = {"page": 1, "perPage": limit}

    try:
        resp = requests.post(url, json={"query": query, "variables": variables}, headers=headers, timeout=20)
        js = resp.json()
        media_list = (((js.get("data") or {}).get("Page") or {}).get("media") or [])
        
        out = []
        for m in media_list:
            norm = normalize_anilist_response(m)
            out.append(norm)
        return out
    except Exception as e:
        print("AniList trending fetch failed:", e)
        return []

def normalize_anilist_response(media: dict, search_title: str = ""):
    title_obj = media.get("title") or {}
    display = title_obj.get("english") or title_obj.get("romaji") or title_obj.get("native") or search_title
    raw_desc = media.get("description") or ""
    
    return {
        "id": media.get("id"),
        "search_title": search_title,
        "display": display,
        "romaji": title_obj.get("romaji"),
        "english": title_obj.get("english"),
        "siteUrl": media.get("siteUrl"),
        "status": media.get("status"),
        "chapters": media.get("chapters"),
        "genres": media.get("genres") or [],
        "averageScore": media.get("averageScore"),
        "popularity": media.get("popularity"),
        "favourites": media.get("favourites"),
        "updatedAt": media.get("updatedAt"),
        "cover": (media.get("coverImage") or {}).get("extraLarge") or (media.get("coverImage") or {}).get("large"),
        "description_raw": raw_desc,
        "description": clean_description(raw_desc),
    }
