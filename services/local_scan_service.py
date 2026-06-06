import re
from pathlib import Path
from db import get_connection
from config import Config
EXTS = {".pdf", ".cbz", ".cbr", ".zip", ".rar", ".epub", ".png", ".jpg", ".jpeg", ".webp"}
IGNORED_FOLDERS = {"telegram desktop", "downloads", "screenshots", "images", "pictures", "desktop", "whatsapp images", "local", "uploads"}
CHAPTER_FOLDER_REGEX = re.compile(r"^(?:chapter|ch|episode|ep)[ \-_]*(\d+(?:\.\d+)?)$", re.I)
MULTISPACE = re.compile(r"\s{2,}")

def canonicalize_title(title: str) -> str:
    t = title.replace("-", " ").replace("–", " ").replace("_", " ")
    t = MULTISPACE.sub(" ", t)
    return t.strip().casefold()

def extract_title_and_chapter(nameWithoutExt: str):
    chapterNum = None
    title = None
    channel = None
    
    # 1. Check for [170] Title @Channel pattern
    bracketMatch = re.match(r"^\s*\[\s*(\d+(?:\.\d+)?)\s*\]\s*(.*)$", nameWithoutExt, re.I)
    if bracketMatch:
        chapterNum = float(bracketMatch.group(1))
        possibleTitle = re.sub(r"\s*@.*$", "", bracketMatch.group(2)).strip()
        if possibleTitle:
            title = possibleTitle
        
        channelMatch = re.search(r"@([a-zA-Z0-9_\- ]+)$", bracketMatch.group(2))
        if channelMatch:
            channel = channelMatch.group(1).strip()
            
        return title, chapterNum, channel
        
    # 2. Check for other chapter patterns
    m = re.search(r"(?:chapter|ch|episode|ep)[ \-_]*(\d+(?:\.\d+)?)|(?:^|[ \-_])(\d+(?:\.\d+)?)(?:[ \-_]|$)", nameWithoutExt, re.I)
    if m and not re.match(r"^(?:page|image|img|pic)\s*\d+", nameWithoutExt, re.I):
        ch_str = m.group(1) or m.group(2)
        if ch_str:
            chapterNum = float(ch_str)
            possibleTitle = nameWithoutExt.replace(m.group(0), "")
            possibleTitle = re.sub(r"\s*@.*$", "", possibleTitle).strip(" -_")
            if possibleTitle:
                title = possibleTitle
            
            channelMatch = re.search(r"@([a-zA-Z0-9_\- ]+)$", nameWithoutExt)
            if channelMatch:
                channel = channelMatch.group(1).strip()
                
    return title, chapterNum, channel

def scan_local_folder(folder=None):
    folder = folder or Config.MANHWA_FOLDER
    if not folder:
        return {}
    
    root = Path(folder)
    if not root.exists():
        return {}

    manhwa = {}
    canon_to_display = {}

    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue

        fileName = p.name
        fileExtMatch = re.match(r"^(.*?)\.[a-z0-9]+$", fileName, re.I)
        nameWithoutExt = fileExtMatch.group(1) if fileExtMatch else fileName
        
        title, chapterNum, channel = extract_title_and_chapter(nameWithoutExt)
        chapterFound = chapterNum is not None
        
        # 3. Fallback: look at folder names
        parts = p.relative_to(root).parts
        if not title:
            for i in range(len(parts) - 2, -1, -1):
                part = parts[i]
                pLower = part.lower()
                if pLower in IGNORED_FOLDERS or CHAPTER_FOLDER_REGEX.match(pLower):
                    continue
                title = part
                break
                
        # Search folders for chapter if still not found
        if not chapterFound:
            for i in range(len(parts) - 1):
                m = re.search(r"(?:chapter|ch|episode|ep)[ \-_]*(\d+(?:\.\d+)?)", parts[i], re.I)
                if m:
                    ch_val = float(m.group(1))
                    chapterNum = max(chapterNum or 0, ch_val)
                    chapterFound = True

        needs_review = False
        if not title:
            title = "Unknown Title"
            needs_review = True

        canon = canonicalize_title(title)
        
        # If we have a non-unknown title with same canon, use its display name
        if canon in canon_to_display and canon_to_display[canon] != "Unknown Title":
            display = canon_to_display[canon]
        else:
            display = title
            canon_to_display[canon] = display

        prev_last, prev_channel, prev_mtime, prev_review = (manhwa.get(display) or [0.0, None, None, False])

        if chapterNum is not None:
            if chapterNum > prev_last:
                manhwa[display] = [chapterNum, channel or prev_channel, p.stat().st_mtime, needs_review and prev_review]
            elif chapterNum == prev_last:
                current_mtime = p.stat().st_mtime
                if prev_mtime is None or current_mtime > prev_mtime:
                    manhwa[display] = [prev_last, channel or prev_channel, current_mtime, needs_review and prev_review]
        else:
            if display not in manhwa:
                manhwa[display] = [prev_last, prev_channel, prev_mtime, needs_review]
                
        # Update review flag (if any file of a valid series has title, the series does not need review)
        if not needs_review and manhwa.get(display):
            manhwa[display][3] = False

    return manhwa

def update_series_from_local_files(user_id, folder=None):
    local_data = scan_local_folder(folder=folder)
    if not local_data:
        return {"status": "error", "message": "No local files found or folder not configured."}
        
    conn = get_connection()
    if not conn:
        return {"status": "error", "message": "Database connection failed."}
    
    cur = conn.cursor()
    rows = []
    for title, (last_local, local_channel, _, needs_review) in local_data.items():
        canonical = canonicalize_title(title)
        needs_rev_int = 1 if needs_review else 0
        rows.append((title.strip(), canonical, float(last_local or 0.0), local_channel, needs_rev_int))

    if rows:
        # 1. Update global series table
        cur.executemany("""
            INSERT INTO series (title, canonical, channel, needs_review)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                channel = COALESCE(VALUES(channel), series.channel),
                needs_review = CASE WHEN VALUES(needs_review) = 1 THEN 1 ELSE series.needs_review END,
                updated_at = CURRENT_TIMESTAMP;
        """, [(r[0], r[1], r[3], r[4]) for r in rows])
        conn.commit()
        
        # 2. Update user_series
        user_series_rows = []
        for r in rows:
            cur.execute("SELECT id FROM series WHERE canonical = %s", (r[1],))
            series_id = cur.fetchone()[0]
            user_series_rows.append((user_id, series_id, r[2]))
            
        cur.executemany("""
            INSERT INTO user_series (user_id, series_id, local_latest_chapter)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                local_latest_chapter = GREATEST(COALESCE(VALUES(local_latest_chapter), 0), COALESCE(user_series.local_latest_chapter, 0)),
                updated_at = CURRENT_TIMESTAMP
        """, user_series_rows)
        conn.commit()
    
    cur.close()
    conn.close()
    
    return {"status": "success", "message": f"Updated {len(rows)} local series for current user.", "count": len(rows)}
