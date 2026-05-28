import os
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"

import numpy as np
import pandas as pd
import json
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from db import get_connection
from services.feedback_service import get_user_feedback_summary
from services.learning_to_rank_service import get_latest_learned_weights
from services.trending_population_service import populate_trending_manhwa
from services.cover_image_service import resolve_cover_image, clear_cover_cache

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer(MODEL_NAME)
    return model

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
    positive_idx = []
    negative_idx = []
    neutral_idx = []
    user_genres = set()
    
    for i, row in library_df.iterrows():
        pref = row.get("user_preference", "neutral")
        if pref == "liked":
            positive_idx.append(i)
        elif pref == "unliked" or pref == "disliked":
            negative_idx.append(i)
        else:
            neutral_idx.append(i)
            
        genres = row.get("genres", [])
        if isinstance(genres, str):
            try: genres = json.loads(genres)
            except: genres = []
        if pref != "unliked" and pref != "disliked":
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
    if len(candidates_df) == 0:
        return candidates_df
        
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

def generate_recommendations(user_id):
    conn = get_connection()
    if not conn:
        return {"status": "error", "message": "DB connection failed"}
        
    library_df = pd.read_sql("""
        SELECT
            s.id AS series_id,
            s.title,
            s.canonical,
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
        return {"status": "error", "message": "Need at least 1 manhwa in your library to generate recommendations."}
        
    if len(trending_df) == 0:
        print("Trending candidates empty. Populating from AniList/MangaDex...")
        populate_trending_manhwa(limit=100)
        trending_df = pd.read_sql("""
            SELECT canonical, display as title, description, genres, 
                   popularity, average_score, cover_image,
                   updated_at
            FROM trending_manhwa
        """, conn)
        
    if len(trending_df) == 0:
        conn.close()
        return {"status": "error", "message": "Could not fetch trending candidates from AniList or MangaDex. Check internet/API."}
        
    print("=== RECOMMENDATION DEBUG ===")
    print("user_id=", user_id)
    print("library_count=", len(library_df))
    print("trending_count=", len(trending_df))
        
    feedback_summary = get_user_feedback_summary(user_id)
    already_read = set(library_df['canonical'].tolist())
    already_read.update(feedback_summary.get('already_read', []))
    disliked_titles = set(feedback_summary.get('disliked', []))
    
    trending_df = trending_df[~trending_df['canonical'].isin(already_read)].reset_index(drop=True)
    print("candidates_after_filter=", len(trending_df))
    if len(trending_df) == 0:
        conn.close()
        return {"status": "error", "message": f"Recommendation failed: library_count={len(library_df)}, trending_count=0, candidates_after_filter=0. Could not fetch candidates from AniList/MangaDex."}
        
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
        except:
            pass
            
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
            
        final_score = (
            w_sem * semantic_score +
            w_gen * genre_score +
            w_pop * popularity_score +
            w_rat * rating_score +
            w_fre * freshness_score +
            w_fee * feedback_score +
            bias
        )
        
        reason = f"Recommended based on {int(semantic_score*100)}% thematic match"
        if genre_score > 0.5:
            reason += f" and strong genre overlap."
        elif popularity_score > 0.8:
            reason += f" and high popularity."
        else:
            reason += "."
            
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
    
    clear_cover_cache()
    
    insert_rows = []
    for _, r in res_df.head(20).iterrows():
        cover = r.get('cover_image')
        if pd.isna(cover) or not cover:
            ani_id = r['source_id'] if r.get('source') == 'AniList' else None
            md_id = r['source_id'] if r.get('source') == 'MangaDex' else None
            
            try:
                if ani_id:
                    ani_id = int(ani_id)
            except:
                ani_id = None
                
            cover = resolve_cover_image(r['candidate_title'], r['candidate_canonical'], anilist_id=ani_id, mangadex_id=md_id)
            
        insert_rows.append((
            user_id, r['candidate_canonical'], r['candidate_title'], cover, r['genres'],
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
    
    return {"status": "success", "message": f"Generated {len(insert_rows)} recommendations", "count": len(insert_rows)}
