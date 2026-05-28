import asyncio
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, Message
from db import get_connection
from config import Config
from services.local_scan_service import extract_title_and_chapter, canonicalize_title

def _message_parts(msg: Message):
    parts, file_name = [], None
    if getattr(msg, "message", None):
        parts.append(msg.message)
    if getattr(msg, "file", None) and getattr(msg.file, "name", None):
        file_name = msg.file.name
        parts.append(file_name)
    return parts, file_name

def _build_msg_link(entity, msg: Message):
    if isinstance(entity, Channel) and getattr(entity, "username", None):
        return f"https://t.me/{entity.username}/{msg.id}"
    if isinstance(entity, (Channel, Chat)):
        return f"https://t.me/c/{entity.id}/{msg.id}"
    return None

async def _telegram_latest_all_dialogs(api_id, api_hash, titles, recent_scan=600):
    canon_targets = {canonicalize_title(t): t for t in titles}
    out = {t: (0.0, None, None, None) for t in titles}

    async with TelegramClient("manhwa_session", api_id, api_hash) as client:
        dialogs = []
        async for d in client.iter_dialogs():
            ent = d.entity
            name = (d.name or "").strip()
            if name.lower() == "telegram":
                continue
            if isinstance(ent, Channel) or isinstance(ent, Chat):
                dialogs.append(d)

        for d in dialogs:
            ent = d.entity
            dname = (d.name or "").strip()
            async for msg in client.iter_messages(d.id, limit=recent_scan):
                parts, fname = _message_parts(msg)
                for part in parts:
                    if fname and part == fname:
                        import pathlib
                        stem = pathlib.Path(fname).stem
                        title, chno, _ = extract_title_and_chapter(stem, filename=fname)
                    else:
                        title, chno, _ = extract_title_and_chapter(part, filename=None)
                        
                    if not title or chno is None:
                        continue

                    canon = canonicalize_title(title)
                    target_title = canon_targets.get(canon)
                    if not target_title:
                        continue

                    prev_ch, _, _, _ = out[target_title]
                    if chno > prev_ch:
                        out[target_title] = (chno, dname, _build_msg_link(ent, msg), msg.date)
    return out

def scan_telegram_channels(titles):
    if not Config.telegram_configured():
        return {"status": "error", "message": "Telegram credentials missing in .env", "data": None}
    
    api_id = Config.TELEGRAM_API_ID
    api_hash = Config.TELEGRAM_API_HASH
    
    try:
        api_id = int(api_id)
        tg_data = asyncio.run(_telegram_latest_all_dialogs(api_id, api_hash, titles))
        return {"status": "success", "data": tg_data}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}

def update_telegram_latest_chapters():
    conn = get_connection()
    if not conn:
        return {"status": "error", "message": "Database connection failed."}
        
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT title, canonical FROM series")
    series_list = cur.fetchall()
    
    if not series_list:
        cur.close()
        conn.close()
        return {"status": "success", "message": "No series found in database to scan.", "count": 0}
        
    titles = [s['title'] for s in series_list]
    
    res = scan_telegram_channels(titles)
    if res["status"] == "error":
        cur.close()
        conn.close()
        return res
        
    tg_data = res["data"]
    rows = []
    for title in titles:
        tg_ch, tg_src, tg_link, tg_dt = tg_data.get(title, (0.0, None, None, None))
        if tg_ch > 0:
            canon = canonicalize_title(title)
            dt_val = tg_dt.replace(tzinfo=None) if isinstance(tg_dt, datetime) else None
            rows.append((float(tg_ch), tg_src, tg_link, dt_val, canon))
            
    if rows:
        cur.executemany("""
            UPDATE series
            SET telegram_latest_chapter = GREATEST(COALESCE(telegram_latest_chapter, 0), %s),
                telegram_source = COALESCE(%s, telegram_source),
                telegram_link = COALESCE(%s, telegram_link),
                telegram_seen_at = COALESCE(%s, telegram_seen_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE canonical = %s
        """, rows)
        conn.commit()
        
    cur.close()
    conn.close()
    
    return {"status": "success", "message": f"Updated Telegram chapters for {len(rows)} series.", "count": len(rows)}
