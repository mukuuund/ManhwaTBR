from db import get_connection
import json

def get_dashboard_stats(user_id):
    conn = get_connection()
    if not conn:
        return {"total_tracked": 0, "updates_available": 0, "recommendations": 0}
        
    cur = conn.cursor(dictionary=True)
    
    cur.execute("SELECT COUNT(*) as count FROM user_series WHERE user_id = %s", (user_id,))
    total_tracked = cur.fetchone()['count']
    
    cur.execute("""
        SELECT COUNT(*) as count 
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        WHERE us.user_id = %s AND s.remote_latest_chapter > us.local_latest_chapter
    """, (user_id,))
    updates_available = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) as count FROM recommendation_results WHERE user_id = %s", (user_id,))
    recommendations = cur.fetchone()['count']
    
    # Calculate completion rate
    cur.execute("""
        SELECT us.local_latest_chapter, s.remote_latest_chapter
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        WHERE us.user_id = %s
          AND us.local_latest_chapter IS NOT NULL
          AND s.remote_latest_chapter IS NOT NULL
          AND s.remote_latest_chapter > 0
    """, (user_id,))
    rows = cur.fetchall()
    
    completion_rate = "N/A"
    if rows:
        total_progress = 0.0
        for r in rows:
            local = float(r['local_latest_chapter'])
            remote = float(r['remote_latest_chapter'])
            progress = (local / remote) * 100.0
            total_progress += progress
        completion_rate = int(round(total_progress / len(rows)))
        
    cur.close()
    conn.close()
    
    return {
        "total_tracked": total_tracked,
        "updates_available": updates_available,
        "recommendations": recommendations,
        "active_reading": total_tracked,
        "completion_rate": completion_rate
    }

def get_top_genres(user_id):
    conn = get_connection()
    if not conn:
        return []
        
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.genres 
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        JOIN manhwa_meta m ON LOWER(m.display) = LOWER(s.title)
        WHERE us.user_id = %s AND m.genres IS NOT NULL
    """, (user_id,))
    rows = cur.fetchall()
    
    genre_counts = {}
    for row in rows:
        try:
            genres = json.loads(row['genres']) if isinstance(row['genres'], str) else row['genres']
            if genres:
                for g in genres:
                    genre_counts[g] = genre_counts.get(g, 0) + 1
        except:
            pass
            
    cur.close()
    conn.close()
    
    sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"name": k, "count": v} for k, v in sorted_genres[:5]]

def get_recent_updates(user_id):
    from services.cover_service import resolve_and_save_cover
    conn = get_connection()
    if not conn:
        return []
        
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT s.id AS series_id, s.title, s.canonical, us.local_latest_chapter, s.remote_latest_chapter, 
               GREATEST(COALESCE(s.remote_latest_chapter,0) - COALESCE(us.local_latest_chapter,0), 0) AS chapters_behind, 
               us.updated_at,
               s.cover_image,
               s.anilist_id,
               s.mangadex_id
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        WHERE us.user_id = %s
        ORDER BY us.updated_at DESC
        LIMIT 5
    """, (user_id,))
    rows = cur.fetchall()
    
    for row in rows:
        if not row.get('cover_image'):
            row['cover_image'] = resolve_and_save_cover(
                row['series_id'], row['title'], row['canonical'],
                row.get('anilist_id'), row.get('mangadex_id')
            )
            
    cur.close()
    conn.close()
    return rows
