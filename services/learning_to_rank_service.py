import numpy as np
from db import get_connection

import os
import requests

def get_latest_learned_weights(user_id):
    conn = get_connection()
    if not conn:
        return None
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT * FROM learned_recommendation_weights 
        WHERE user_id = %s
        ORDER BY created_at DESC LIMIT 1
    """, (user_id,))
    weights = cur.fetchone()
    cur.close()
    conn.close()
    return weights

def log_recommendation_event(user_id, series_id, candidate_canonical, scores, action, label):
    conn = get_connection()
    if not conn:
        return False
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO recommendation_events (
            user_id, series_id, candidate_canonical, 
            semantic_score, genre_score, popularity_score, 
            rating_score, freshness_score, feedback_score, 
            final_score_at_time, action, label
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        user_id, series_id, candidate_canonical,
        scores.get('semantic_score'), scores.get('genre_score'), scores.get('popularity_score'),
        scores.get('rating_score'), scores.get('freshness_score'), scores.get('feedback_score'),
        scores.get('score'), action, label
    ))
    conn.commit()
    cur.close()
    conn.close()
    return True

def retrain_recommendation_weights(user_id):
    hf_url = os.environ.get("HF_WORKER_URL")
    hf_secret = os.environ.get("ML_WORKER_SECRET")
    
    if not hf_url or not hf_secret:
        return {"status": "error", "message": "Hugging Face Worker URL or Secret not configured."}
        
    try:
        url = f"{hf_url.rstrip('/')}/retrain"
        headers = {"Authorization": f"Bearer {hf_secret}"}
        res = requests.post(url, json={"user_id": user_id}, headers=headers, timeout=180)
        res.raise_for_status()
        data = res.json()
        if data.get("success"):
            return {
                "status": "success", 
                "message": data.get("message", "Retrained successfully."),
                "weights": data.get("weights", {})
            }
        else:
            return {"status": "error", "message": data.get("error", "Failed to retrain weights.")}
    except Exception as e:
        return {"status": "error", "message": f"Error calling ML Worker: {str(e)}"}
