from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from db import get_connection
from services.local_scan_service import update_series_from_local_files
from services.telegram_scan_service import update_telegram_latest_chapters
from services.recommendation_service import generate_recommendations
from services.feedback_service import save_feedback
from services.trending_population_service import populate_trending_manhwa
from services.dashboard_service import get_dashboard_stats, get_top_genres, get_recent_updates
from services.title_parser import group_imported_files
from services.chapter_discovery_service import update_remote_latest_chapters
from services.learning_to_rank_service import retrain_recommendation_weights, log_recommendation_event, get_latest_learned_weights
from services.cover_service import resolve_and_save_cover
import json
import hashlib
import urllib.parse

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

@app.template_filter('format_chapter')
def format_chapter_filter(value):
    if value is None:
        return '-'
    try:
        val = float(value)
        if val.is_integer():
            return str(int(val))
        return str(val)
    except (ValueError, TypeError):
        return str(value)

@app.template_filter('fromjson')
def fromjson_filter(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}

@app.template_filter('cover_fallback')
def cover_fallback_filter(cover_image, title):
    if cover_image and cover_image.strip() and cover_image != 'None':
        return cover_image
    
    h = hashlib.md5(title.encode('utf-8')).hexdigest()
    palettes = [
        ("#0f172a", "#1e1b4b", "#c3f400"),
        ("#0f172a", "#311042", "#38bdf8"),
        ("#020617", "#1c1917", "#a3e635"),
        ("#090514", "#2e0854", "#f43f5e"),
        ("#020617", "#064e3b", "#34d399"),
        ("#0c0a09", "#451a03", "#fb923c"),
    ]
    idx = int(h, 16) % len(palettes)
    start_color, end_color, text_color = palettes[idx]
    
    words = [w for w in title.split() if w]
    if len(words) >= 2:
        initials = (words[0][0] + words[1][0]).upper()
    elif len(words) == 1:
        initials = words[0][:2].upper()
    else:
        initials = "??"
        
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300" width="100%" height="100%">
        <defs>
            <linearGradient id="grad-{h[:8]}" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{start_color};stop-opacity:1" />
                <stop offset="100%" style="stop-color:{end_color};stop-opacity:1" />
            </linearGradient>
            <pattern id="grid-{h[:8]}" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="1"/>
            </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grad-{h[:8]})" />
        <rect width="100%" height="100%" fill="url(#grid-{h[:8]})" />
        <path d="M-50 350 L250 -50" stroke="rgba(255,255,255,0.015)" stroke-width="40" />
        <path d="M-50 150 L250 -250" stroke="rgba(255,255,255,0.01)" stroke-width="20" />
        <circle cx="100" cy="150" r="45" fill="rgba(0,0,0,0.2)" stroke="{text_color}" stroke-width="2" stroke-dasharray="4 4" />
        <text x="100" y="165" font-family="'Anybody', 'Space Grotesk', sans-serif" font-weight="900" font-size="42" fill="{text_color}" text-anchor="middle" letter-spacing="1">{initials}</text>
        <rect x="15" y="15" width="170" height="270" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="1" />
        <text x="100" y="275" font-family="'JetBrains Mono', monospace" font-size="8" fill="rgba(255,255,255,0.3)" text-anchor="middle" letter-spacing="2">MANHWA READER</text>
    </svg>"""
    
    encoded_svg = urllib.parse.quote(svg)
    return f"data:image/svg+xml,{encoded_svg}"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_user():
    return dict(current_user=session.get('username'), current_email=session.get('email'))

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/api-docs')
def api_docs():
    return render_template('api_docs.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_connection()
        if conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                flash("Email already exists", "error")
                return redirect(url_for('signup'))
                
            hashed = generate_password_hash(password)
            cur.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)", (username, email, hashed))
            user_id = cur.lastrowid
            
            # Auto-migrate existing series if this is the first user
            cur.execute("SELECT COUNT(*) as c FROM user_series")
            if cur.fetchone()['c'] == 0:
                cur.execute("SELECT id, local_latest_chapter FROM series WHERE local_latest_chapter IS NOT NULL")
                all_series = cur.fetchall()
                if all_series:
                    insert_rows = [(user_id, s['id'], s['local_latest_chapter']) for s in all_series]
                    cur.executemany("INSERT INTO user_series (user_id, series_id, local_latest_chapter) VALUES (%s, %s, %s)", insert_rows)
            
            conn.commit()
            cur.close()
            conn.close()
            flash("Signup successful! Please log in.", "success")
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_connection()
        if conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['email'] = user['email']
                return redirect(request.args.get('next') or url_for('dashboard'))
            else:
                flash("Invalid email or password", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    stats = get_dashboard_stats(user_id)
    top_genres = get_top_genres(user_id)
    recent_updates = get_recent_updates(user_id)
    return render_template('dashboard.html', stats=stats, top_genres=top_genres, recent_updates=recent_updates)

@app.route('/library')
@login_required
def library():
    conn = get_connection()
    series = []
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.id AS series_id,
                s.title,
                s.canonical,
                us.local_latest_chapter,
                s.remote_latest_chapter,
                s.remote_source,
                s.remote_confidence,
                s.remote_url,
                us.user_preference,
                s.needs_review,
                s.review_reason,
                s.cover_image,
                s.anilist_id,
                s.mangadex_id,
                CASE
                    WHEN s.remote_latest_chapter IS NOT NULL
                     AND s.remote_latest_chapter > COALESCE(us.local_latest_chapter, 0)
                    THEN s.remote_latest_chapter - COALESCE(us.local_latest_chapter, 0)
                    ELSE 0
                END AS chapters_behind
            FROM user_series us
            JOIN series s ON s.id = us.series_id
            WHERE us.user_id = %s
            ORDER BY s.title ASC
        """, (session['user_id'],))
        series = cur.fetchall()
        
        # Override needs_review using user specific values and resolve covers
        for s in series:
            if not s.get('cover_image'):
                s['cover_image'] = resolve_and_save_cover(
                    s['series_id'], s['title'], s['canonical'], 
                    s.get('anilist_id'), s.get('mangadex_id')
                )
            if s.get('remote_latest_chapter') is not None and s['remote_latest_chapter'] < (s.get('local_latest_chapter') or 0):
                s['needs_review'] = 1
                s['review_reason'] = "Remote chapter is lower than your local latest chapter. Needs manual review."
            
        cur.close()
        conn.close()
    return render_template('library.html', series=series)

@app.route('/updates')
@login_required
def updates():
    conn = get_connection()
    updates_list = []
    review_list = []
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.id AS series_id,
                s.title,
                s.canonical,
                us.local_latest_chapter,
                s.remote_latest_chapter,
                s.remote_source,
                s.remote_confidence,
                s.remote_url,
                us.user_preference,
                s.needs_review,
                s.review_reason,
                s.remote_latest_chapter - COALESCE(us.local_latest_chapter, 0) AS chapters_behind,
                s.cover_image,
                s.anilist_id,
                s.mangadex_id
            FROM user_series us
            JOIN series s ON s.id = us.series_id
            WHERE us.user_id = %s
              AND s.remote_latest_chapter IS NOT NULL
              AND s.remote_latest_chapter > COALESCE(us.local_latest_chapter, 0)
              AND (s.needs_review IS NULL OR s.needs_review = 0)
            ORDER BY chapters_behind DESC
        """, (session['user_id'],))
        updates_list = cur.fetchall()
        
        cur.execute("""
            SELECT
                s.id AS series_id,
                s.title,
                s.canonical,
                us.local_latest_chapter,
                s.remote_latest_chapter,
                s.remote_source,
                s.remote_confidence,
                s.remote_url,
                us.user_preference,
                s.needs_review,
                s.review_reason,
                s.cover_image,
                s.anilist_id,
                s.mangadex_id
            FROM user_series us
            JOIN series s ON s.id = us.series_id
            WHERE us.user_id = %s
              AND (s.needs_review = 1 OR s.remote_latest_chapter IS NULL OR s.remote_latest_chapter < COALESCE(us.local_latest_chapter, 0))
            ORDER BY s.title ASC
        """, (session['user_id'],))
        review_list = cur.fetchall()
        
        for item in updates_list:
            if not item.get('cover_image'):
                item['cover_image'] = resolve_and_save_cover(
                    item['series_id'], item['title'], item['canonical'],
                    item.get('anilist_id'), item.get('mangadex_id')
                )
                
        for item in review_list:
            if not item.get('cover_image'):
                item['cover_image'] = resolve_and_save_cover(
                    item['series_id'], item['title'], item['canonical'],
                    item.get('anilist_id'), item.get('mangadex_id')
                )
            if item.get('remote_latest_chapter') is not None and item['remote_latest_chapter'] < item.get('local_latest_chapter', 0):
                item['review_reason'] = "Remote chapter is lower than your local latest chapter. Needs manual review."
                
        cur.close()
        conn.close()
    return render_template('updates.html', updates=updates_list, review_list=review_list)

@app.route('/recommendations')
@login_required
def recommendations():
    conn = get_connection()
    recs = []
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM recommendation_results WHERE user_id = %s ORDER BY score DESC", (session['user_id'],))
        recs = cur.fetchall()
        for r in recs:
            if r['genres']:
                try: r['genres'] = json.loads(r['genres'])
                except: r['genres'] = []
        cur.close()
        conn.close()
    return render_template('recommendations.html', recommendations=recs)

@app.route('/recommendations/generate', methods=['POST'])
@login_required
def run_recommendations():
    try:
        res = generate_recommendations(session['user_id'])
        if res.get('status') == 'success':
            flash(res['message'], 'success')
        else:
            flash(res.get('message', 'Failed to generate recommendations.'), 'error')
    except Exception as e:
        flash(f"Error generating recommendations: {str(e)}.", 'error')
    return redirect(url_for('recommendations'))

@app.route('/scan/local', methods=['POST'])
@login_required
def scan_local():
    res = update_series_from_local_files(session['user_id'])
    if res.get('status') == 'success':
        flash(res['message'], 'success')
    else:
        flash(res.get('message', 'Local scan failed.'), 'error')
    return redirect(url_for('library'))

@app.route('/scan/telegram', methods=['POST'])
@login_required
def scan_telegram():
    if not Config.telegram_configured():
        flash("Telegram credentials missing. Please set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env", "warning")
        return redirect(url_for('library'))
        
    try:
        res = update_telegram_latest_chapters()
        if res.get('status') == 'success':
            flash(res['message'], 'success')
        else:
            flash(res.get('message', 'Telegram scan failed.'), 'error')
    except Exception as e:
        flash(f"Error during Telegram scan: {str(e)}", 'error')
    return redirect(url_for('library'))

@app.route('/api/import-folder', methods=['POST'])
@login_required
def api_import_folder():
    data = request.json
    files = data.get('files', [])
    series_list, files_processed, warnings = group_imported_files(files)
    
    conn = get_connection()
    if conn:
        cur = conn.cursor()
        user_id = session['user_id']
        for s in series_list:
            # 1. Insert into global series
            cur.execute("""
                INSERT INTO series (title, canonical)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE title = VALUES(title), updated_at = CURRENT_TIMESTAMP
            """, (s['title'], s['canonical']))
            
            cur.execute("SELECT id FROM series WHERE canonical = %s", (s['canonical'],))
            series_id = cur.fetchone()[0]
            
            # 2. Insert into user_series
            cur.execute("""
                INSERT INTO user_series (user_id, series_id, local_latest_chapter)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    local_latest_chapter = GREATEST(COALESCE(VALUES(local_latest_chapter), 0), COALESCE(user_series.local_latest_chapter, 0)),
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, series_id, s['local_latest_chapter']))
            
        conn.commit()
        cur.close()
        conn.close()
        
    return jsonify({
        "imported_series_count": len(series_list),
        "files_processed": files_processed,
        "series": series_list,
        "warnings": warnings
    })

@app.route('/api/refresh-remote-chapters', methods=['POST'])
@login_required
def api_refresh_remote_chapters():
    user_id = session['user_id']
    conn = get_connection()
    series_list = []
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT s.*, us.local_latest_chapter
            FROM user_series us
            JOIN series s ON s.id = us.series_id
            WHERE us.user_id = %s
        """, (user_id,))
        series_list = cur.fetchall()
        cur.close()
        conn.close()
        
    res = update_remote_latest_chapters(series_list=series_list)
    
    conn = get_connection()
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.title,
                us.local_latest_chapter,
                s.remote_latest_chapter,
                s.remote_source,
                CASE
                    WHEN s.remote_latest_chapter IS NOT NULL
                     AND s.remote_latest_chapter > COALESCE(us.local_latest_chapter, 0)
                    THEN s.remote_latest_chapter - COALESCE(us.local_latest_chapter, 0)
                    ELSE 0
                END AS chapters_behind
            FROM user_series us
            JOIN series s ON s.id = us.series_id
            WHERE us.user_id = %s
            ORDER BY s.title ASC
        """, (user_id,))
        sql_result = cur.fetchall()
        cur.close()
        conn.close()
        
        print("=== USER LIBRARY UPDATE STATUS FROM SQL ===")
        for row in sql_result:
            print(f"{row['title']} local={row['local_latest_chapter']} remote={row['remote_latest_chapter']} behind={row['chapters_behind']} source={row['remote_source']}")

    return jsonify(res)

@app.route('/api/series/<canonical>/asura-url', methods=['POST'])
@login_required
def set_asura_url(canonical):
    data = request.json or {}
    url = data.get('asura_url')
    
    if url and not url.startswith(Config.ASURA_BASE_URL):
        return jsonify({"status": "error", "message": f"URL must start with {Config.ASURA_BASE_URL}"}), 400
        
    if url and "/comics/" not in url:
        return jsonify({"status": "error", "message": "Only Asura series pages (/comics/) are supported."}), 400
        
    conn = get_connection()
    if not conn:
        return jsonify({"status": "error", "message": "DB Connection Error"}), 500
        
    try:
        cur = conn.cursor()
        if url:
            cur.execute("UPDATE series SET asura_url = %s WHERE canonical = %s", (url, canonical))
        else:
            cur.execute("UPDATE series SET asura_url = NULL WHERE canonical = %s", (canonical,))
        conn.commit()
        cur.close()
        return jsonify({"status": "success", "message": "Asura URL updated."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/manual-update', methods=['POST'])
@login_required
def api_manual_update():
    data = request.json
    canonical = data.get('canonical')
    remote_chapter = data.get('remote_chapter')
    
    if not canonical or remote_chapter is None:
        return jsonify({"status": "error", "message": "Missing parameters"})
        
    try:
        remote_chapter = float(remote_chapter)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid chapter format"})
        
    conn = get_connection()
    if conn:
        cur = conn.cursor(dictionary=True)
        
        cur.execute("""
            UPDATE series 
            SET remote_latest_chapter = %s,
                remote_source = 'manual',
                remote_confidence = 1.0,
                needs_review = 0,
                review_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE canonical = %s
        """, (remote_chapter, canonical))
        conn.commit()
            
        cur.close()
        conn.close()
        
    return jsonify({"status": "success"})

@app.route('/api/library', methods=['GET'])
@login_required
def api_library():
    conn = get_connection()
    series = []
    if conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.title,
                s.canonical,
                us.local_latest_chapter,
                s.remote_latest_chapter,
                s.remote_source,
                s.remote_confidence,
                s.remote_url,
                us.user_preference,
                s.needs_review,
                s.review_reason,
                CASE
                    WHEN s.remote_latest_chapter IS NOT NULL
                     AND s.remote_latest_chapter > COALESCE(us.local_latest_chapter, 0)
                    THEN s.remote_latest_chapter - COALESCE(us.local_latest_chapter, 0)
                    ELSE 0
                END AS chapters_behind
            FROM user_series us
            JOIN series s ON s.id = us.series_id
            LEFT JOIN trending_manhwa tm ON tm.canonical = s.canonical
            WHERE us.user_id = %s
            ORDER BY s.title ASC
        """, (session['user_id'],))
        series = cur.fetchall()
        cur.close()
        conn.close()
    return jsonify(series)

@app.route('/api/library-feedback', methods=['POST'])
@login_required
def api_library_feedback():
    data = request.json
    canonical = data.get('canonical')
    preference = data.get('preference')
    if not canonical or not preference:
        return jsonify({"status": "error", "message": "Missing data"}), 400
        
    try:
        if preference not in ['liked', 'unliked', 'neutral']:
            return jsonify({"status": "error", "message": "Invalid preference"}), 400

        user_id = session['user_id']
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM series WHERE canonical = %s", (canonical,))
            s = cur.fetchone()
            if s:
                series_id = s[0]
                cur.execute("""
                    UPDATE user_series SET user_preference = %s WHERE user_id = %s AND series_id = %s
                """, (preference, user_id, series_id))
            conn.commit()
            cur.close()
            conn.close()
            
        preference_to_feedback = {
            "liked": "liked",
            "unliked": "disliked"
        }
        if preference in preference_to_feedback:
            save_feedback(user_id, canonical, preference_to_feedback[preference])
            
        return jsonify({"status": "success", "success": True})
    except Exception as e:
        app.logger.exception("API error")
        return jsonify({"status": "error", "success": False, "error": str(e)}), 500

@app.route('/api/feedback', methods=['POST'])
@login_required
def api_feedback():
    data = request.json
    canonical = data.get('canonical')
    action = data.get('action') # liked, disliked, saved, already_read, clicked, ignored
    
    try:
        # Simple label mapping
        labels = {
            'liked': 1.0, 'saved': 1.0, 'clicked': 0.7, 
            'already_read': 0.6, 'ignored': 0.2, 'disliked': 0.0
        }
        label = labels.get(action)
        
        user_id = session['user_id']
        conn = get_connection()
        scores = {}
        series_id = None
        if conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM recommendation_results WHERE user_id = %s AND candidate_canonical = %s", (user_id, canonical))
            rec = cur.fetchone()
            if rec:
                scores = rec
            cur.execute("SELECT id FROM series WHERE canonical = %s", (canonical,))
            s = cur.fetchone()
            if s:
                series_id = s['id']
                
            if action in ['disliked', 'already_read', 'ignored']:
                cur.execute("DELETE FROM recommendation_results WHERE user_id = %s AND candidate_canonical = %s", (user_id, canonical))
                
            conn.commit()
            cur.close()
            conn.close()
            
        # Default scores if none
        if not scores:
            scores = {'semantic_score': 0, 'genre_score': 0, 'popularity_score': 0, 'rating_score': 0, 'freshness_score': 0, 'feedback_score': 0, 'score': 0}
            
        log_recommendation_event(user_id, series_id, canonical, scores, action, label)
        if action in ['liked', 'disliked', 'already_read', 'saved']:
            # Feedback type for existing functionality
            save_feedback(user_id, canonical, action)
            
        return jsonify({"status": "success", "success": True})
    except Exception as e:
        app.logger.exception("API error")
        return jsonify({"status": "error", "success": False, "error": str(e)}), 500

@app.route('/api/retrain-recommendation-weights', methods=['POST'])
@login_required
def api_retrain_weights():
    try:
        res = retrain_recommendation_weights(session['user_id'])
        res["success"] = True
        return jsonify(res)
    except Exception as e:
        app.logger.exception("API error")
        return jsonify({"status": "error", "success": False, "error": str(e)}), 500

@app.route('/api/recommendations', methods=['GET'])
@login_required
def api_recommendations():
    try:
        conn = get_connection()
        recs = []
        if conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM recommendation_results WHERE user_id = %s ORDER BY score DESC", (session['user_id'],))
            recs = cur.fetchall()
            cur.close()
            conn.close()
            
        weights = get_latest_learned_weights(session['user_id'])
        return jsonify({"recommendations": recs, "weights": weights, "success": True})
    except Exception as e:
        app.logger.exception("API error")
        return jsonify({"status": "error", "success": False, "error": str(e)}), 500

@app.route('/settings')
@login_required
def settings():
    conn = get_connection()
    db_status = "Connected" if conn else "Disconnected"
    if conn: conn.close()
    
    settings_data = {
        "db_status": db_status,
        "manhwa_folder": Config.MANHWA_FOLDER or "Not Configured",
        "env_loaded_path": Config.ENV_LOADED_PATH,
        "telegram_api_id_configured": bool(Config.TELEGRAM_API_ID),
        "telegram_api_hash_configured": bool(Config.TELEGRAM_API_HASH),
        "telegram_phone_configured": bool(Config.TELEGRAM_PHONE),
        "telegram_configured": Config.telegram_configured()
    }
    return render_template('settings.html', settings=settings_data)

@app.route('/api/debug/my-library-count')
@login_required
def api_debug_library_count():
    user_id = session['user_id']
    conn = get_connection()
    if not conn:
        return jsonify({"error": "No DB connection"}), 500
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT us.user_id, u.username, s.title, s.canonical 
        FROM user_series us 
        JOIN users u ON u.id = us.user_id 
        JOIN series s ON s.id = us.series_id 
        WHERE us.user_id = %s
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({
        "user_id": user_id,
        "library_count": len(rows),
        "library_titles": [r['title'] for r in rows]
    })

@app.route('/api/populate-trending', methods=['POST'])
@login_required
def api_populate_trending():
    try:
        result = populate_trending_manhwa(limit=100)
        return jsonify(result)
    except Exception as e:
        app.logger.exception("API error")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/debug/update-status')
@login_required
def api_debug_update_status():
    user_id = session['user_id']
    conn = get_connection()
    if not conn:
        return jsonify({"error": "No DB connection"}), 500
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            s.title,
            s.canonical,
            us.local_latest_chapter,
            s.remote_latest_chapter,
            s.remote_source,
            CASE
                WHEN s.remote_latest_chapter IS NOT NULL
                 AND s.remote_latest_chapter > COALESCE(us.local_latest_chapter, 0)
                THEN s.remote_latest_chapter - COALESCE(us.local_latest_chapter, 0)
                ELSE 0
            END AS chapters_behind
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        WHERE us.user_id = %s
        ORDER BY s.title ASC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({
        "user_id": user_id,
        "items": rows
    })

@app.route('/api/search')
@login_required
def api_search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"results": []})
        
    like_query = f"%{query}%"
    conn = get_connection()
    results = []
    if conn:
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("""
                SELECT DISTINCT
                    q.title,
                    q.canonical,
                    COALESCE(tm.cover_image, '') AS cover_image,
                    COALESCE(tm.genres, mm.genres) AS genres,
                    CASE WHEN us.id IS NOT NULL THEN 1 ELSE 0 END AS in_library
                FROM (
                    SELECT title, canonical FROM series WHERE title LIKE %s OR canonical LIKE %s
                    UNION
                    SELECT display AS title, canonical FROM trending_manhwa WHERE display LIKE %s OR canonical LIKE %s
                    UNION
                    SELECT display AS title, LOWER(REPLACE(display, ' ', '-')) AS canonical FROM manhwa_meta WHERE display LIKE %s OR search_title LIKE %s
                ) q
                LEFT JOIN trending_manhwa tm ON tm.canonical = q.canonical
                LEFT JOIN manhwa_meta mm ON LOWER(mm.display) = LOWER(q.title)
                LEFT JOIN series s ON s.canonical = q.canonical
                LEFT JOIN user_series us ON us.series_id = s.id AND us.user_id = %s
                WHERE q.title IS NOT NULL AND q.title != ''
                LIMIT 15
            """, (like_query, like_query, like_query, like_query, like_query, like_query, session['user_id']))
            rows = cur.fetchall()
            
            for r in rows:
                genres_raw = r['genres']
                genres_list = []
                if genres_raw:
                    try:
                        genres_list = json.loads(genres_raw) if isinstance(genres_raw, str) else genres_raw
                    except:
                        pass
                r['genres'] = genres_list if isinstance(genres_list, list) else []
                r['cover_image'] = cover_fallback_filter(r['cover_image'], r['title'])
                
                # De-duplicate by canonical
                # We'll just append and dedupe later if needed, or dedupe inline
                
            seen = set()
            for r in rows:
                if r['canonical'] not in seen:
                    seen.add(r['canonical'])
                    results.append(r)
            
            cur.close()
        except Exception as e:
            app.logger.exception("Search API error")
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            conn.close()
            
    return jsonify({"results": results})

@app.route('/api/notifications')
@login_required
def api_notifications():
    user_id = session['user_id']
    conn = get_connection()
    if not conn:
        return jsonify({"updates_count": 0, "needs_review_count": 0, "recommendation_count": 0, "latest_updates": []})
        
    cur = conn.cursor(dictionary=True)
    
    # Updates
    cur.execute("""
        SELECT s.title
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        WHERE us.user_id = %s
          AND s.remote_latest_chapter IS NOT NULL
          AND s.remote_latest_chapter > COALESCE(us.local_latest_chapter, 0)
          AND (s.needs_review IS NULL OR s.needs_review = 0)
        ORDER BY s.title ASC
    """, (user_id,))
    updates = cur.fetchall()
    
    # Needs review
    cur.execute("""
        SELECT COUNT(*) as c
        FROM user_series us
        JOIN series s ON s.id = us.series_id
        WHERE us.user_id = %s
          AND (s.needs_review = 1 OR (s.remote_latest_chapter IS NOT NULL AND s.remote_latest_chapter < COALESCE(us.local_latest_chapter, 0)))
    """, (user_id,))
    needs_review = cur.fetchone()['c']
    
    # Recommendations
    cur.execute("SELECT COUNT(*) as c FROM recommendation_results WHERE user_id = %s", (user_id,))
    rec_count = cur.fetchone()['c']
    
    cur.close()
    conn.close()
    
    return jsonify({
        "updates_count": len(updates),
        "needs_review_count": needs_review,
        "recommendation_count": rec_count,
        "latest_updates": [u['title'] for u in updates[:2]]
    })

@app.route('/api/library/add', methods=['POST'])
@login_required
def api_library_add():
    data = request.json or {}
    canonical = data.get('canonical')
    title = data.get('title')
    
    if not canonical or not title:
        return jsonify({"status": "error", "message": "Missing title or canonical"}), 400
        
    conn = get_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection error"}), 500
        
    try:
        cur = conn.cursor()
        user_id = session['user_id']
        
        cur.execute("""
            INSERT INTO series (title, canonical)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE title = VALUES(title), updated_at = CURRENT_TIMESTAMP
        """, (title, canonical))
        
        cur.execute("SELECT id FROM series WHERE canonical = %s", (canonical,))
        row = cur.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Failed to create series"}), 500
        series_id = row[0]
        
        cur.execute("""
            INSERT IGNORE INTO user_series (user_id, series_id, local_latest_chapter, user_preference)
            VALUES (%s, %s, 1, 'neutral')
        """, (user_id, series_id))
        
        conn.commit()
        cur.close()
        return jsonify({"status": "success", "message": f"Added '{title}' to your library!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=Config.FLASK_DEBUG)
