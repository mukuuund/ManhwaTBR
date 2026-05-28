import numpy as np
from db import get_connection

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    from sklearn.linear_model import LogisticRegression

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
    conn = get_connection()
    if not conn:
        return {"status": "error", "message": "Database connection failed"}
        
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT 
            semantic_score, genre_score, popularity_score, 
            rating_score, freshness_score, feedback_score, label
        FROM recommendation_events
        WHERE user_id = %s AND label IS NOT NULL
    """, (user_id,))
    events = cur.fetchall()
    
    if len(events) < 20:
        cur.close()
        conn.close()
        return {"status": "success", "message": "Feedback saved. Using default weights plus your likes/dislikes until more feedback is available."}
        
    X = []
    y = []
    for e in events:
        X.append([
            float(e['semantic_score'] or 0),
            float(e['genre_score'] or 0),
            float(e['popularity_score'] or 0),
            float(e['rating_score'] or 0),
            float(e['freshness_score'] or 0),
            float(e['feedback_score'] or 0)
        ])
        y.append(float(e['label']))
        
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    
    y_binary = (y > 0.5).astype(int)
    if len(np.unique(y_binary)) < 2:
        cur.close()
        conn.close()
        return {"status": "success", "message": "Feedback saved. Need more diverse feedback (likes and dislikes) to retrain personalized weights."}
    
    X = np.clip(X, 0, 1)
    
    weights_dict = {}
    bias_val = 0.0
    loss_val = 0.0
    
    if HAS_TORCH:
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
        if w_sum > 0:
            w = w / w_sum
            
        weights_dict = {
            'semantic': float(w[0]),
            'genre': float(w[1]),
            'popularity': float(w[2]),
            'rating': float(w[3]),
            'freshness': float(w[4]),
            'feedback': float(w[5]),
            'bias': float(b)
        }
    else:
        model = LogisticRegression(fit_intercept=True, positive=True)
        model.fit(X, y_binary)
        
        w = model.coef_[0]
        b = model.intercept_[0]
        w_sum = np.sum(w)
        if w_sum > 0:
            w = w / w_sum
            
        weights_dict = {
            'semantic': float(w[0]),
            'genre': float(w[1]),
            'popularity': float(w[2]),
            'rating': float(w[3]),
            'freshness': float(w[4]),
            'feedback': float(w[5]),
            'bias': float(b)
        }
        
    cur.execute("""
        INSERT INTO learned_recommendation_weights (
            user_id,
            semantic_weight, genre_weight, popularity_weight,
            rating_weight, freshness_weight, feedback_weight,
            bias, training_examples_count, loss
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            semantic_weight = VALUES(semantic_weight),
            genre_weight = VALUES(genre_weight),
            popularity_weight = VALUES(popularity_weight),
            rating_weight = VALUES(rating_weight),
            freshness_weight = VALUES(freshness_weight),
            feedback_weight = VALUES(feedback_weight),
            bias = VALUES(bias),
            training_examples_count = VALUES(training_examples_count),
            loss = VALUES(loss),
            created_at = CURRENT_TIMESTAMP
    """, (
        user_id,
        weights_dict['semantic'], weights_dict['genre'], weights_dict['popularity'],
        weights_dict['rating'], weights_dict['freshness'], weights_dict['feedback'],
        weights_dict['bias'], len(events), loss_val
    ))
    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "status": "success", 
        "message": f"Successfully trained and updated recommendation weights using {len(events)} examples.",
        "weights": weights_dict
    }
