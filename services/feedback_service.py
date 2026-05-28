from db import get_connection

def save_feedback(user_id: int, canonical: str, feedback_type: str):
    ALLOWED_FEEDBACK_TYPES = {"liked", "disliked", "already_read", "saved", "clicked", "ignored"}

    if feedback_type not in ALLOWED_FEEDBACK_TYPES:
        raise ValueError(f"Invalid feedback_type: {feedback_type}")

    conn = get_connection()
    if not conn:
        return False
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_feedback (user_id, manhwa_canonical, feedback_type)
        VALUES (%s, %s, %s)
    """, (user_id, canonical, feedback_type))
    
    conn.commit()
    cur.close()
    conn.close()
    return True

def get_feedback_for_title(user_id: int, canonical: str):
    conn = get_connection()
    if not conn:
        return None
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT feedback_type FROM user_feedback 
        WHERE user_id = %s AND manhwa_canonical = %s 
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, canonical))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res['feedback_type'] if res else None

def get_user_feedback_summary(user_id: int):
    conn = get_connection()
    if not conn:
        return {}
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT manhwa_canonical, feedback_type 
        FROM user_feedback
        WHERE user_id = %s AND id IN (
            SELECT MAX(id) FROM user_feedback WHERE user_id = %s GROUP BY manhwa_canonical
        )
    """, (user_id, user_id))
    res = cur.fetchall()
    cur.close()
    conn.close()
    
    summary = {
        'liked': [],
        'disliked': [],
        'already_read': [],
        'saved': []
    }
    for row in res:
        ftype = row['feedback_type']
        if ftype in summary:
            summary[ftype].append(row['manhwa_canonical'])
    return summary
