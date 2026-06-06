import os
import json
import numpy as np
import pandas as pd
import mysql.connector
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import torch
import torch.nn as nn
import torch.optim as optim
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")
ML_WORKER_SECRET = os.environ.get("ML_WORKER_SECRET")

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer(MODEL_NAME)
    return model

def get_connection():
    try:
        return mysql.connector.connect(
            host=DB_HOST,
            port=int(DB_PORT),
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
    except Exception as e:
        print(f"DB Error: {e}")
        return None

def verify_secret(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    if token != ML_WORKER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

class GenerateRequest(BaseModel):
    user_id: int

class RetrainRequest(BaseModel):
    user_id: int

# --- ML HELPER FUNCTIONS ---

def prep_text(title, desc, genres):
    title = (title or "").strip()
    desc  = (desc or "").strip().replace("\n", " ")
    genres = (genres or "").strip()
    parts = []
    if title:  parts.append(title)
    if desc:   parts.append(desc[:2000])
    if genres: parts.append(f"Genres: {genres}")
    return " — ".join(parts)

def get_jaccard_similarity(list1, list2):
    s1 = set(list1)
    s2 = set(list2)
    if not s1 and not s2:
        return 0.0
    return len(s1.intersection(s2)) / len(s1.union(s2))

def build_user_taste_profile(library_df, lib_emb):
    positive_idx, negative_idx, neutral_idx = [], [], []
    user_genres = set()
    
    for i, row in library_df.iterrows():
        pref = row.get("user_preference", "neutral")
        if pref == "liked":
            positive_idx.append(i)
        elif pref in ("unliked", "disliked"):
            negative_idx.append(i)
        else:
            neutral_idx.append(i)
            
        genres = row.get("genres", [])
        if isinstance(genres, str):
            try: genres = json.loads(genres)
            except: genres = []
        if pref not in ("unliked", "disliked"):
            for g in genres:
                user_genres.add(g)
                
    if positive_idx:
        pos_profile = np.average(lib_emb[positive_idx + neutral_idx], axis=0, weights=[1.0]*len(positive_idx) + [0.35]*len(neutral_idx))
    elif neutral_idx:
        pos_profile = np.mean(lib_emb[neutral_idx], axis=0)
    else:
        pos_profile = np.zeros(lib_emb.shape[1])
        
    neg_profile = np.mean(lib_emb[negative_idx], axis=0) if negative_idx else np.zeros(lib_emb.shape[1])
    return pos_profile, neg_profile, list(user_genres)

def apply_mmr_diversity(candidates_df, cand_emb, top_k=20, lambda_param=0.75):
    if len(candidates_df) == 0: return candidates_df
    top_k = min(top_k, len(candidates_df))
    scores = candidates_df['score'].values
    selected_indices = []
    remaining_indices = list(range(len(candidates_df)))
    
    first_idx = np.argmax(scores)
    selected_indices.append(first_idx)
    remaining_indices.remove(first_idx)
    
    while len(selected_indices) < top_k and remaining_indices:
        best_score = -np.inf
        best_idx = -1
        for idx in remaining_indices:
            sim_to_selected = np.max(cosine_similarity([cand_emb[idx]], cand_emb[selected_indices])[0])
            mmr_score = lambda_param * scores[idx] - (1 - lambda_param) * sim_to_selected
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)
    return candidates_df.iloc[selected_indices].copy()

def get_latest_learned_weights(user_id):
    conn = get_connection()
    if not conn: return None
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM learned_recommendation_weights WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
    weights = cur.fetchone()
    cur.close()
    conn.close()
    return weights

def get_user_feedback_summary(user_id):
    conn = get_connection()
    if not conn: return {}
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT canonical, feedback_type FROM user_feedback WHERE user_id = %s", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    summary = {'already_read': [], 'liked': [], 'disliked': [], 'saved': []}
    for r in rows:
        ftype = r['feedback_type']
        if ftype in summary:
            summary[ftype].append(r['canonical'])
    return summary

# --- ENDPOINTS ---

@app.post("/generate")
def generate_recommendations(req: GenerateRequest, authorized: bool = Depends(verify_secret)):
    user_id = req.user_id
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "DB connection failed"}
        
    library_df = pd.read_sql("""
        SELECT
            s.id AS series_id, s.title, s.canonical,
            COALESCE(m.description, '') AS description,
            COALESCE(m.genres, '') AS genres,
            us.local_latest_chapter,
            COALESCE(us.user_preference, 'neutral') AS user_preference
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        LEFT JOIN manhwa_meta m ON LOWER(m.display) = LOWER(s.title)
        WHERE us.user_id = %s
    """, conn, params=(user_id,))
    
    trending_df = pd.read_sql("""
        SELECT canonical, display as title, description, genres, 
               popularity, average_score, cover_image,
               updated_at, source, source_id
        FROM trending_manhwa
    """, conn)
    
    if len(library_df) == 0:
        conn.close()
        return {"success": False, "error": "Need at least 1 manhwa in your library."}
    if len(trending_df) == 0:
        conn.close()
        return {"success": False, "error": "Trending candidates empty."}
        
    feedback_summary = get_user_feedback_summary(user_id)
    already_read = set(library_df['canonical'].tolist())
    already_read.update(feedback_summary.get('already_read', []))
    disliked_titles = set(feedback_summary.get('disliked', []))
    
    trending_df = trending_df[~trending_df['canonical'].isin(already_read)].reset_index(drop=True)
    if len(trending_df) == 0:
        conn.close()
        return {"success": False, "error": "All candidates already read."}
        
    library_df["text"] = library_df.apply(lambda r: prep_text(r["title"], r["description"], r["genres"]), axis=1)
    trending_df["text"] = trending_df.apply(lambda r: prep_text(r["title"], r["description"], r["genres"]), axis=1)
    
    embedder = get_model()
    lib_emb = embedder.encode(library_df["text"].tolist(), normalize_embeddings=True)
    cand_emb = embedder.encode(trending_df["text"].tolist(), normalize_embeddings=True)
    
    pos_profile, neg_profile, user_genres = build_user_taste_profile(library_df, lib_emb)
    
    results = []
    max_popularity = trending_df['popularity'].max() or 1
    now = pd.Timestamp.utcnow()
    
    learned_weights = get_latest_learned_weights(user_id)
    if learned_weights and learned_weights['training_examples_count'] >= 20:
        w_sem = float(learned_weights['semantic_weight'])
        w_gen = float(learned_weights['genre_weight'])
        w_pop = float(learned_weights['popularity_weight'])
        w_rat = float(learned_weights['rating_weight'])
        w_fre = float(learned_weights['freshness_weight'])
        w_fee = float(learned_weights['feedback_weight'])
        bias = float(learned_weights['bias'])
    else:
        w_sem, w_gen, w_pop, w_rat, w_fre, w_fee = 0.40, 0.20, 0.15, 0.10, 0.10, 0.05
        bias = 0.0
    
    for i, row in trending_df.iterrows():
        cand_genres = []
        try:
            cand_genres = json.loads(row['genres']) if isinstance(row['genres'], str) else row['genres']
        except: pass
            
        sim_pos = cosine_similarity([cand_emb[i]], [pos_profile])[0][0] if pos_profile.any() else 0
        sim_neg = cosine_similarity([cand_emb[i]], [neg_profile])[0][0] if neg_profile.any() else 0
        semantic_score = sim_pos - (0.30 * sim_neg)
        
        genre_score = get_jaccard_similarity(user_genres, cand_genres)
        popularity_score = (row['popularity'] or 0) / max_popularity
        rating_score = (row['average_score'] or 0) / 100.0
        
        updated_at = pd.to_datetime(row['updated_at'], errors="coerce", utc=True)
        if pd.isna(updated_at):
            freshness_score = 0.5
        else:
            days_old = (now - updated_at).days
            freshness_score = max(0, 1 - (days_old / 365.0))
            
        feedback_score = 0.5
        if row['canonical'] in disliked_titles:
            feedback_score = 0.0
            
        final_score = (w_sem * semantic_score + w_gen * genre_score + w_pop * popularity_score + 
                       w_rat * rating_score + w_fre * freshness_score + w_fee * feedback_score + bias)
                       
        reason = f"Recommended based on {int(semantic_score*100)}% thematic match"
        if genre_score > 0.5: reason += f" and strong genre overlap."
        elif popularity_score > 0.8: reason += f" and high popularity."
        else: reason += "."
            
        results.append({
            "candidate_canonical": row['canonical'],
            "candidate_title": row['title'],
            "cover_image": row['cover_image'],
            "genres": json.dumps(cand_genres),
            "score": float(final_score),
            "semantic_score": float(semantic_score),
            "genre_score": float(genre_score),
            "popularity_score": float(popularity_score),
            "rating_score": float(rating_score),
            "freshness_score": float(freshness_score),
            "feedback_score": float(feedback_score),
            "reason": reason
        })
        
    res_df = pd.DataFrame(results)
    res_df = apply_mmr_diversity(res_df, cand_emb)
    
    cur = conn.cursor()
    cur.execute("DELETE FROM recommendation_results WHERE user_id = %s", (user_id,))
    
    insert_rows = []
    for _, r in res_df.head(20).iterrows():
        # NOTE: cover resolution is moved to JS or Render if needed, but trending_manhwa has covers usually.
        # Fallback to empty string if missing, frontend handle it via cover_fallback filter.
        insert_rows.append((
            user_id, r['candidate_canonical'], r['candidate_title'], r['cover_image'] or "", r['genres'],
            r['score'], r['semantic_score'], r['genre_score'], r['popularity_score'],
            r['rating_score'], r['freshness_score'], r['feedback_score'], r['reason']
        ))
        
    if insert_rows:
        cur.executemany("""
            INSERT INTO recommendation_results (
                user_id, candidate_canonical, candidate_title, cover_image, genres,
                score, semantic_score, genre_score, popularity_score,
                rating_score, freshness_score, feedback_score, reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, insert_rows)
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {"success": True, "message": f"Generated {len(insert_rows)} recommendations", "count": len(insert_rows)}


@app.post("/retrain")
def retrain_weights(req: RetrainRequest, authorized: bool = Depends(verify_secret)):
    user_id = req.user_id
    conn = get_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}
        
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT semantic_score, genre_score, popularity_score, rating_score, freshness_score, feedback_score, label
        FROM recommendation_events WHERE user_id = %s AND label IS NOT NULL
    """, (user_id,))
    events = cur.fetchall()
    
    if len(events) < 20:
        cur.close()
        conn.close()
        return {"success": True, "message": "Feedback saved. Need more examples."}
        
    X, y = [], []
    for e in events:
        X.append([float(e['semantic_score'] or 0), float(e['genre_score'] or 0), float(e['popularity_score'] or 0),
                  float(e['rating_score'] or 0), float(e['freshness_score'] or 0), float(e['feedback_score'] or 0)])
        y.append(float(e['label']))
        
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    y_binary = (y > 0.5).astype(int)
    
    if len(np.unique(y_binary)) < 2:
        cur.close()
        conn.close()
        return {"success": True, "message": "Need more diverse feedback (likes and dislikes)."}
    
    X = np.clip(X, 0, 1)
    
    class LRModel(nn.Module):
        def __init__(self):
            super(LRModel, self).__init__()
            self.linear = nn.Linear(6, 1)
            with torch.no_grad():
                self.linear.weight.copy_(torch.tensor([[0.40, 0.20, 0.15, 0.10, 0.10, 0.05]]))
                self.linear.bias.copy_(torch.tensor([0.0]))
        def forward(self, x):
            return torch.sigmoid(self.linear(x))
            
    model = LRModel()
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.01)
    
    X_t = torch.tensor(X)
    y_t = torch.tensor(y).view(-1, 1)
    
    for epoch in range(500):
        optimizer.zero_grad()
        outputs = model(X_t)
        loss = criterion(outputs, y_t)
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            model.linear.weight.clamp_(min=0.0)
            
    loss_val = float(loss.item())
    w = model.linear.weight.detach().numpy()[0]
    b = model.linear.bias.detach().numpy()[0]
    
    w_sum = np.sum(w)
    if w_sum > 0: w = w / w_sum
        
    weights_dict = {
        'semantic': float(w[0]), 'genre': float(w[1]), 'popularity': float(w[2]),
        'rating': float(w[3]), 'freshness': float(w[4]), 'feedback': float(w[5]),
        'bias': float(b)
    }
    
    cur.execute("""
        INSERT INTO learned_recommendation_weights (
            user_id, semantic_weight, genre_weight, popularity_weight, rating_weight, freshness_weight, feedback_weight,
            bias, training_examples_count, loss
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            semantic_weight=VALUES(semantic_weight), genre_weight=VALUES(genre_weight), popularity_weight=VALUES(popularity_weight),
            rating_weight=VALUES(rating_weight), freshness_weight=VALUES(freshness_weight), feedback_weight=VALUES(feedback_weight),
            bias=VALUES(bias), training_examples_count=VALUES(training_examples_count), loss=VALUES(loss), created_at=CURRENT_TIMESTAMP
    """, (user_id, weights_dict['semantic'], weights_dict['genre'], weights_dict['popularity'],
          weights_dict['rating'], weights_dict['freshness'], weights_dict['feedback'], weights_dict['bias'], len(events), loss_val))
    conn.commit()
    cur.close()
    conn.close()
    
    return {"success": True, "message": "Retrained successfully.", "weights": weights_dict}
