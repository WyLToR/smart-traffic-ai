from __future__ import annotations

import logging
import re
import shutil
from urllib.parse import parse_qsl, urlsplit


def youtube_url(value: str) -> str | None:
    parts = urlsplit(value if "://" in value else "https://" + value)
    host = parts.hostname
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return None
    if parts.scheme not in {"http", "https"}:
        raise ValueError("HTTP(S) YouTube-link szükséges.")
    path = parts.path.strip("/").split("/")
    if host == "youtu.be" and len(path) == 1:
        video_id = path[0]
    elif len(path) == 2 and path[0] in {"live", "embed", "shorts"}:
        video_id = path[1]
    elif parts.path == "/watch":
        ids = [value for key, value in parse_qsl(parts.query) if key == "v"]
        video_id = ids[0] if len(ids) == 1 else ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Egy konkrét YouTube-videó vagy élő közvetítés linkjét add meg.")
    return f"https://www.youtube.com/watch?v={video_id}"


def resolve_youtube(value: str) -> str:
    try:
        import yt_dlp
    except ImportError as exc:
        raise ImportError(
            "A YouTube-bemenethez telepítsd: uv pip install -e '.[youtube]'."
        ) from exc
    runtime = next((name for name in ("deno", "node") if shutil.which(name)), None)
    if runtime is None:
        raise ValueError("A YouTube feloldásához Node.js 22+ vagy Deno 2.3+ szükséges a PATH-ban.")
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    options = {
        "quiet": True,
        "no_warnings": True,
        "logger": logger,
        "noplaylist": True,
        "skip_download": True,
        "cachedir": False,
        "socket_timeout": 10,
        "retries": 0,
        "extractor_retries": 0,
        "js_runtimes": {runtime: {}},
    }
    try:
        with yt_dlp.YoutubeDL(options) as extractor:
            info = extractor.extract_info(value, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ValueError(
            "A YouTube-videó forrása nem érhető el. Lehet korlátozott, megszűnt, "
            "vagy a YouTube-feloldó frissítést igényel."
        ) from exc
    formats = (info or {}).get("formats") or []
    candidates = [
        item
        for item in formats
        if item.get("protocol") in {"m3u8", "m3u8_native"}
        and str(item.get("vcodec", "")).startswith("avc1")
        and not item.get("has_drm")
        and 0 < (item.get("height") or 0) <= 720
        and urlsplit(item.get("url") or "").scheme == "https"
    ]
    if not candidates:
        raise ValueError("Ehhez a YouTube-videóhoz nincs támogatott, legfeljebb 720p-s HLS-forrás.")
    return max(candidates, key=lambda item: (item["height"], item.get("fps") or 0))["url"]
