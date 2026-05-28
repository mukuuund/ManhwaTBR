import requests
import json
import re
from db import get_connection
from services.title_parser import canonicalize_title

def fetch_anilist_trending(limit=100):
    url = 'https://graphql.anilist.co'
    query = '''
    query ($page: Int, $perPage: Int) {
      Page(page: $page, perPage: $perPage) {
        media(type: MANGA, sort: TRENDING_DESC, countryOfOrigin: KR) {
          id
          title {
            romaji
            english
          }
          description(asHtml: false)
          genres
          averageScore
          popularity
          trending
          updatedAt
          coverImage {
            large
          }
          siteUrl
        }
      }
    }
    '''
    
    variables = {
        'page': 1,
        'perPage': limit
    }
    
    try:
        response = requests.post(url, json={'query': query, 'variables': variables}, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('Page', {}).get('media', [])
    except Exception as e:
        print(f"Error fetching from AniList: {e}")
    return []

def fetch_mangadex_trending(limit=100):
    url = f"https://api.mangadex.org/manga?limit={limit}&includes[]=cover_art&order[followedCount]=desc&availableTranslatedLanguage[]=en&originalLanguage[]=ko"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json().get('data', [])
    except Exception as e:
        print(f"Error fetching from MangaDex: {e}")
    return []

def clean_description(desc):
    if not desc:
        return ""
    # Remove html tags
    clean = re.compile('<.*?>')
    desc = re.sub(clean, '', desc)
    # Remove AniList specific formatting like __ or **
    desc = desc.replace('__', '').replace('**', '').replace('~', '')
    return desc.strip()

def populate_trending_manhwa(limit=100):
    conn = get_connection()
    if not conn:
        print("Error: Could not connect to database for trending population")
        return {"success": False, "error": "DB connection failed"}

    inserted_or_updated = 0
    source_counts = {"AniList": 0, "MangaDex": 0}
    
    cur = conn.cursor()

    # 1. AniList
    anilist_media = fetch_anilist_trending(limit=limit)
    for media in anilist_media:
        title = media.get('title', {}).get('english') or media.get('title', {}).get('romaji')
        if not title:
            continue
            
        canonical = canonicalize_title(title)
        desc = clean_description(media.get('description', ''))
        genres = json.dumps(media.get('genres', []))
        popularity = media.get('popularity', 0)
        avg_score = media.get('averageScore', 0) or 0
        cover = media.get('coverImage', {}).get('large')
        source_id = str(media.get('id', ''))
        source_url = media.get('siteUrl', '')
        
        try:
            cur.execute("""
                INSERT INTO trending_manhwa 
                (canonical, display, description, genres, popularity, average_score, source, source_id, source_url, cover_image)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    display = VALUES(display),
                    description = VALUES(description),
                    genres = VALUES(genres),
                    popularity = VALUES(popularity),
                    average_score = VALUES(average_score),
                    cover_image = VALUES(cover_image),
                    updated_at = CURRENT_TIMESTAMP
            """, (canonical, title, desc, genres, popularity, avg_score, 'AniList', source_id, source_url, cover))
            inserted_or_updated += 1
            source_counts["AniList"] += 1
        except Exception as e:
            print(f"Error inserting AniList title {title}: {e}")

    # 2. MangaDex (fallback/additional)
    mangadex_media = fetch_mangadex_trending(limit=limit)
    for media in mangadex_media:
        attrs = media.get('attributes', {})
        
        # Get English title, or first title
        title_dict = attrs.get('title', {})
        title = title_dict.get('en')
        if not title and title_dict:
            title = list(title_dict.values())[0]
            
        if not title:
            continue
            
        canonical = canonicalize_title(title)
        
        # Check if already in DB to avoid unnecessary updates if we don't need to
        cur.execute("SELECT id FROM trending_manhwa WHERE canonical = %s", (canonical,))
        if cur.fetchone():
            continue
            
        desc_dict = attrs.get('description', {})
        desc = clean_description(desc_dict.get('en', ''))
        
        genres_list = [tag['attributes']['name']['en'] for tag in attrs.get('tags', []) if 'name' in tag['attributes'] and 'en' in tag['attributes']['name']]
        genres = json.dumps(genres_list)
        
        source_id = media.get('id', '')
        source_url = f"https://mangadex.org/title/{source_id}"
        
        cover = None
        for rel in media.get('relationships', []):
            if rel['type'] == 'cover_art' and 'attributes' in rel and 'fileName' in rel['attributes']:
                filename = rel['attributes']['fileName']
                cover = f"https://uploads.mangadex.org/covers/{source_id}/{filename}"
                
        try:
            cur.execute("""
                INSERT INTO trending_manhwa 
                (canonical, display, description, genres, popularity, average_score, source, source_id, source_url, cover_image)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    popularity = GREATEST(popularity, VALUES(popularity))
            """, (canonical, title, desc, genres, 0, 0, 'MangaDex', source_id, source_url, cover))
            inserted_or_updated += 1
            source_counts["MangaDex"] += 1
        except Exception as e:
            print(f"Error inserting MangaDex title {title}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "success": True,
        "inserted_or_updated": inserted_or_updated,
        "source_counts": source_counts
    }
