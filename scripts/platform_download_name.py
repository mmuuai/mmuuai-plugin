"""Standalone filename parity with contracts/src/download-file-name.ts."""
from datetime import datetime, timedelta, timezone
import re
try:
    from zoneinfo import ZoneInfo
    SINGAPORE = ZoneInfo("Asia/Singapore")
except (ImportError, LookupError):
    # Contemporary Singapore completion timestamps use UTC+08:00 without DST.
    SINGAPORE = timezone(timedelta(hours=8), "Asia/Singapore")

JS_SPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
MIME_EXTENSIONS = {
    "application/json": "json", "application/pdf": "pdf", "audio/flac": "flac",
    "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav",
    "image/avif": "avif", "image/gif": "gif", "image/jpeg": "jpg", "image/png": "png",
    "image/webp": "webp", "text/csv": "csv", "text/markdown": "md", "text/plain": "txt",
    "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
}
KINDS = {"audio": "音频", "file": "文件", "image": "图片", "text": "文本", "video": "视频"}
RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I | re.ASCII)


def platform_download_source_name(value):
    raw = value.strip(JS_SPACE) if isinstance(value, str) else ""
    raw = re.sub(r"\.[a-z0-9ſK]{1,8}$", "", raw, flags=re.I | re.ASCII)
    normalized = "".join("-" if ord(char) < 32 or char in '\\/:*?"<>|' else char for char in raw)
    normalized = re.sub("[" + re.escape(JS_SPACE) + "_-]+", "-", normalized).strip(". -")
    bounded = normalized[:24].rstrip(". -")
    return "mmuuai" if not bounded or RESERVED.fullmatch(bounded) else bounded


def download_extension(mime_type, fallback=None):
    mime = mime_type.split(";", 1)[0].strip(JS_SPACE).lower() if isinstance(mime_type, str) else ""
    extension = MIME_EXTENSIONS.get(mime)
    if extension is None and isinstance(fallback, str):
        extension = re.sub(r"^\.", "", fallback).lower()
    return "." + extension if extension and re.fullmatch(r"[a-z0-9]{1,8}", extension, re.ASCII) else ""


def _positive(value):
    return int(value) if (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and 0 < value <= 2**53 - 1 and value == int(value)) else 1


def _timestamp(value, now=None):
    parsed = None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc) if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else parsed.astimezone()
    except (TypeError, ValueError, OverflowError, AttributeError):
        parsed = None
    return (parsed or now or datetime.now(timezone.utc)).astimezone(SINGAPORE).strftime("%Y%m%d-%H%M%S")


def platform_generated_download_name(value, *, now=None):
    total = _positive(value.get("total"))
    index = min(_positive(value.get("index")), total)
    sequence = f"_{index:02d}" if total > 1 else ""
    return (f"{platform_download_source_name(value.get('sourceName'))}_{KINDS.get(value.get('kind'), '文件')}_"
            f"{_timestamp(value.get('completedAt'), now)}{sequence}"
            f"{download_extension(value.get('mimeType'), value.get('fallbackExtension'))}")


def output_entries(result):
    raw = ([(-1, {"type": "text", "text": result["text"]})]
           if isinstance(result.get("text"), str) and result["text"] else []) + list(enumerate(result.get("parts", [])))
    entries, texts = [], set()
    for index, part in raw:
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            if part["text"] in texts:
                continue
            texts.add(part["text"])
        entries.append((index, part))
    def valid(part):
        return isinstance(part, dict) and (isinstance(part.get("text"), str) if part.get("type") == "text"
                                           else isinstance(part.get("type"), str) and part["type"] in KINDS and isinstance(part.get("url"), str))
    total, ordinal = sum(valid(part) for _, part in entries), 0
    for index, part in entries:
        ordinal += int(valid(part))
        yield index, part, ordinal, total


def result_download_name(part, context, index, total, mime, *, now=None):
    supplied = part.get("fileName") or part.get("url")
    extension = re.search(r"\.([a-z0-9]{1,8})(?:[?#]|$)", supplied, re.I | re.ASCII) if isinstance(supplied, str) else None
    return platform_generated_download_name({**context, "kind": part.get("type"), "index": index, "total": total,
                                             "mimeType": mime, "fallbackExtension": extension[1] if extension else None}, now=now)
