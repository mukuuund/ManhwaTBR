import re
from pathlib import Path
from db import get_connection
from config import Config

EXTS = {".pdf", ".cbz", ".cbr", ".zip", ".rar", ".epub", ".png", ".jpg", ".jpeg", ".webp"}

LEADING_BRACKET_NUM = re.compile(r"^\s*\[\s*(\d+(?:\.\d+)?)\s*\]\s*(.*)$", re.I)
EXPL_CH             = re.compile(r"(?:\bch(?:apter)?|\bep|\bchap)\s*(\d+(?:\.\d+)?)", re.I)
TRAILING_BARE_NUM   = re.compile(r"(?:^|[ \-–_:._])(\d+(?:\.\d+)?)\s*$", re.I)
TRAILING_TAGS       = re.compile(r"\s*[\(\[]\s*(?:eng|raw|hd|scan|color|clean|repack|v\d+|part\s*\d+)\s*[\)\]]\s*$", re.I)
MULTISPACE          = re.compile(r"\s{2,}")

_EXTS_RE = "(?:" + "|".join(re.escape(ext.lstrip(".")) for ext in sorted(EXTS, key=len, reverse=True)) + ")"
CHANNEL_BETWEEN_ANY = re.compile(rf"@([A-Za-z0-9_ ]+)(?=\.{_EXTS_RE}\b)", re.I)

def canonicalize_title(title: str) -> str:
    t = title.replace("-", " ").replace("–", " ").replace("_", " ")
    t = MULTISPACE.sub(" ", t)
    return t.strip().casefold()

def extract_title_and_chapter(stem: str, filename=None):
    s = stem.replace("_", " ").replace(".", " ").strip()
    channel = None
    if filename:
        m = CHANNEL_BETWEEN_ANY.search(filename)
        if m:
            channel = m.group(1).strip()
            variants = {channel, channel.replace("_", " ")}
            for ch in variants:
                s = re.sub(rf"\s*@{re.escape(ch)}\s*$", " ", s, flags=re.I)
                s = re.sub(rf"\s*@{re.escape(ch)}\b",  " ", s, flags=re.I)

    s = re.sub(r"\s*@[\w _-]+$", " ", s, flags=re.I)

    chapter = None
    m = LEADING_BRACKET_NUM.match(s)
    if m:
        try: chapter = float(m.group(1))
        except ValueError: chapter = None
        s = m.group(2)

    if chapter is None:
        m = EXPL_CH.search(s)
        if m:
            try: chapter = float(m.group(1))
            except ValueError: chapter = None
            s = EXPL_CH.sub("", s)

    if chapter is None:
        m = TRAILING_BARE_NUM.search(s)
        if m:
            try: chapter = float(m.group(1))
            except ValueError: chapter = None
            s = TRAILING_BARE_NUM.sub("", s)

    s = TRAILING_TAGS.sub("", s)
    s = MULTISPACE.sub(" ", s).strip(" -–_:")
    return s or stem, chapter, channel

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

        # Use parent folder name if it's not the root folder, else fallback to stem
        if p.parent != root:
            # E.g. root/Solo Leveling/Chapter 01/page.jpg -> parent is Chapter 01
            # If parent is Chapter 01, we want the manhwa title which might be "Solo Leveling"
            # So we use the relative path parts
            rel_parts = p.relative_to(root).parts
            if len(rel_parts) >= 2:
                # The first part of the relative path is the manhwa name, the second is chapter folder
                title_candidate = f"{rel_parts[0]} {rel_parts[-2]}" 
            else:
                title_candidate = p.parent.name
        else:
            title_candidate = p.stem

        # We also pass the actual filename for channel extraction
        title, ch, channel = extract_title_and_chapter(title_candidate, filename=p.name)
        if not title:
            # Fallback to stem if parent parsing yielded nothing (unlikely)
            title, ch_alt, channel_alt = extract_title_and_chapter(p.stem, filename=p.name)
            if not title:
                continue
            if ch is None: ch = ch_alt
            if channel is None: channel = channel_alt

        canon = canonicalize_title(title)
        display = canon_to_display.get(canon) or title
        canon_to_display[canon] = display

        prev_last, prev_channel, prev_mtime = (manhwa.get(display) or [0.0, None, None])

        if ch is not None:
            if ch > prev_last:
                manhwa[display] = [ch, channel or prev_channel, p.stat().st_mtime]
            elif ch == prev_last:
                current_mtime = p.stat().st_mtime
                if prev_mtime is None or current_mtime > prev_mtime:
                    manhwa[display] = [prev_last, channel or prev_channel, current_mtime]
        else:
            if display not in manhwa:
                manhwa[display] = [prev_last, prev_channel, prev_mtime]

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
    for title, (last_local, local_channel, _) in local_data.items():
        canonical = canonicalize_title(title)
        rows.append((title.strip(), canonical, float(last_local or 0.0), local_channel))

    if rows:
        # 1. Update global series table
        cur.executemany("""
            INSERT INTO series (title, canonical, channel)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                channel = COALESCE(VALUES(channel), series.channel),
                updated_at = CURRENT_TIMESTAMP;
        """, [(r[0], r[1], r[3]) for r in rows])
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
