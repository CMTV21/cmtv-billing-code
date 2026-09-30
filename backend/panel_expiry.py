"""Normalise panel expiry values to naive UTC datetimes.

XtreamUI renders expiry in the panel server's local timezone but embeds the exact Unix epoch in the
cell's data-order attribute; XuiOne/NXT Dash/Aether return epochs or ISO strings. Everything funnels
through here so stored expiry_date values are always UTC.
"""
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

NEVER_EPOCH = 4102444800  # 2100-01-01; XtreamUI uses 9999999999 for "Never"
NEVER_LABELS = {"unlimited", "never", "lifetime", "n/a"}
NEVER_WORDS = NEVER_LABELS | {"none", "null", "0", ""}
_DATA_ORDER_RE = re.compile(r'data-order="(\d{9,})"')
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T]?(\d{2}:\d{2}(?::\d{2})?)?")
_US_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(.*)$")
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def epoch_to_utc(epoch) -> Optional[datetime]:
    try:
        epoch = int(epoch)
    except (TypeError, ValueError):
        return None
    if epoch <= 0 or epoch >= NEVER_EPOCH:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)


def cell_epoch(cell) -> Optional[int]:
    m = _DATA_ORDER_RE.search(str(cell or ""))
    return int(m.group(1)) if m else None


def strip_html(cell) -> str:
    text = str(cell or "").replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def looks_like_date(text: str) -> bool:
    t = (text or "").strip()
    return bool(_DATE_RE.search(t) or _US_DATE_RE.match(t) or t.lower() in NEVER_LABELS or (t.isdigit() and len(t) == 10))


def is_unlimited(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return int(value) <= 0 or int(value) >= NEVER_EPOCH
    ep = cell_epoch(value)
    if ep is not None:
        return ep >= NEVER_EPOCH
    text = strip_html(value).lower()
    return text in NEVER_WORDS or (text.isdigit() and int(text) >= NEVER_EPOCH)


def parse_expiry(value) -> Optional[datetime]:
    """Epoch (int/str), ISO-8601, 'YYYY-MM-DD[ HH:MM[:SS]]', 'MM/DD/YYYY', or an HTML cell → naive UTC. None = unlimited/unknown."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (int, float)):
        return epoch_to_utc(int(value))
    raw = str(value)
    ep = cell_epoch(raw)
    if ep is not None:
        return epoch_to_utc(ep)
    text = strip_html(raw)
    if text.lower() in NEVER_WORDS:
        return None
    if text.isdigit():
        return epoch_to_utc(int(text))
    us = _US_DATE_RE.match(text)
    if us:
        text = f"{us.group(3)}-{int(us.group(1)):02d}-{int(us.group(2)):02d}{us.group(4)}".strip()
    m = _DATE_RE.search(text)
    if m:
        text = f"{m.group(1)} {m.group(2)}" if m.group(2) else m.group(1)
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(strip_html(raw).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def to_panel_string(dt: Optional[datetime], unlimited: bool = False) -> str:
    if unlimited or dt is None:
        return "Never" if unlimited else ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def row_expiry(row, start: int = 3, fallback_col: int = 7) -> Tuple[Optional[datetime], bool, str]:
    """Locate the expiry cell in an XtreamUI DataTables row → (utc datetime, unlimited, raw cell).

    Prefers a cell carrying data-order (exact epoch) whose text is date-like; otherwise the first
    date-like cell text (panel-local time); finally the legacy fixed column.
    """
    cells = list(row or [])
    for idx in range(start, len(cells)):
        raw = str(cells[idx])
        ep = cell_epoch(raw)
        if ep is not None and looks_like_date(strip_html(raw)):
            return epoch_to_utc(ep), ep >= NEVER_EPOCH, raw
    for idx in range(start, len(cells)):
        raw = str(cells[idx])
        text = strip_html(raw)
        if text and looks_like_date(text):
            return parse_expiry(text), is_unlimited(text), raw
    if len(cells) > fallback_col:
        raw = str(cells[fallback_col])
        return parse_expiry(raw), is_unlimited(raw), raw
    return None, False, ""
