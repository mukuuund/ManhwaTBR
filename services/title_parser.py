import re
from pathlib import Path

EXTS = {".pdf", ".cbz", ".cbr", ".zip", ".rar", ".epub", ".png", ".jpg", ".jpeg", ".webp"}

LEADING_BRACKET_NUM = re.compile(r"^\s*\[\s*(\d+(?:\.\d+)?)\s*\]\s*(.*)$", re.I)
TRAILING_BRACKET_NUM = re.compile(r"\s*\[\s*(\d+(?:\.\d+)?)\s*\]\s*$", re.I)
EXPL_CH             = re.compile(r"(?:\bch(?:apter)?|\bep|\bchap)\s*(\d+(?:\.\d+)?)", re.I)
TRAILING_BARE_NUM   = re.compile(r"(?:^|[ \-–_:._])(\d+(?:\.\d+)?)\s*$", re.I)
TRAILING_TAGS       = re.compile(r"\s*[\(\[]\s*(?:eng|raw|hd|scan|color|clean|repack|v\d+|part\s*\d+|[^\]\)]*)\s*[\)\]]\s*$", re.I)
MULTISPACE          = re.compile(r"\s{2,}")

_EXTS_RE = "(?:" + "|".join(re.escape(ext.lstrip(".")) for ext in sorted(EXTS, key=len, reverse=True)) + ")"
CHANNEL_BETWEEN_ANY = re.compile(rf"@([A-Za-z0-9_ ]+)(?=\.{_EXTS_RE}\b)", re.I)
GROUP_BRACKETS = re.compile(r"^\[([^\]]+)\]\s*(.*)$")

def normalize_title(text: str) -> str:
    t = text.replace("-", " ").replace("–", " ").replace("_", " ")
    t = MULTISPACE.sub(" ", t)
    return t.strip()

def canonicalize_title(title: str) -> str:
    t = normalize_title(title)
    return t.casefold()

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

    # remove leading group bracket like [Asura]
    m_group = GROUP_BRACKETS.match(s)
    if m_group:
        # Check if it's just a number like [120]
        if not m_group.group(1).replace('.', '').isdigit():
            s = m_group.group(2)

    chapter = None
    m = LEADING_BRACKET_NUM.match(s)
    if m:
        try: chapter = float(m.group(1))
        except ValueError: chapter = None
        s = m.group(2)

    if chapter is None:
        m = TRAILING_BRACKET_NUM.search(s)
        if m:
            try: chapter = float(m.group(1))
            except ValueError: chapter = None
            s = TRAILING_BRACKET_NUM.sub("", s)

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
    s = normalize_title(s)
    return s or stem, chapter, channel

def group_imported_files(files):
    series = {}
    canon_to_display = {}
    warnings = []
    
    files_processed = 0
    for file_entry in files:
        name = file_entry.get('name', '')
        rel_path = file_entry.get('relative_path', '')
        
        path_obj = Path(rel_path)
        if path_obj.suffix.lower() not in EXTS and '.' in name:
            # ignore unsupported extensions
            pass
            
        stem = path_obj.stem
        title, ch, channel = extract_title_and_chapter(stem, filename=name)
        
        if not title:
            warnings.append(f"Could not extract title from {name}")
            continue
            
        files_processed += 1
            
        canon = canonicalize_title(title)
        display = canon_to_display.get(canon) or title
        canon_to_display[canon] = display
        
        if display not in series:
            series[display] = {
                "title": display,
                "canonical": canon,
                "local_latest_chapter": ch if ch is not None else 0.0,
                "matched_files": 1
            }
        else:
            series[display]["matched_files"] += 1
            if ch is not None and ch > series[display]["local_latest_chapter"]:
                series[display]["local_latest_chapter"] = ch
                
    # remove zeroes if possible, wait, if 0.0 it's fine
    return list(series.values()), files_processed, warnings
