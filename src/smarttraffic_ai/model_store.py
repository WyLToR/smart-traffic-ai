from __future__ import annotations

import gc
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


@dataclass
class ModelHandle:
    model: object
    lock: threading.RLock = field(default_factory=threading.RLock)


_CACHE: OrderedDict[tuple, ModelHandle] = OrderedDict()
_LOCK = threading.RLock()
_MAX_MODELS = 2
OFFICIAL_MODELS = {"yolo11n.pt": "v8.3.0", "yolo26n.pt": "v8.4.0", "yolo26l.pt": "v8.4.0"}


def _load_yolo(path: Path):
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise ImportError("A felismeréshez a vision függőségeket kell telepíteni.") from exc
    try:
        model = YOLO(str(path))
        if model.task != "detect":
            raise ValueError("A modell nem objektumdetektor.")
        return model
    except Exception as exc:
        raise ValueError(f"A YOLO-modell nem tölthető be: {path} ({type(exc).__name__}).") from exc


def load_model(path: Path, device="cpu", half=False) -> tuple[ModelHandle, bool]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Nincs YOLO-modell: {path}. A Modellkezelés panelen letölthető.")
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns, device, half)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key], True
        handle = ModelHandle(_load_yolo(path))
        _CACHE[key] = handle
        while len(_CACHE) > _MAX_MODELS:
            _CACHE.popitem(last=False)
        return handle, False


def clear_model_cache():
    # An active detector retains its handle; clearing never invalidates a running video.
    with _LOCK:
        _CACHE.clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_initialized():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def official_model_url(name: str) -> str:
    return f"https://github.com/ultralytics/assets/releases/download/{OFFICIAL_MODELS[name]}/{name}"


def download_model(root: Path, name: str) -> Path:
    if name not in OFFICIAL_MODELS:
        raise ValueError("Csak a három támogatott, hivatalos modell tölthető le.")
    destination = root / "models" / name
    if destination.is_file():
        load_model(destination)  # Existing corrupt files are reported, never silently overwritten.
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        digest = hashlib.sha256()
        size = 0
        with (
            urlopen(
                Request(official_model_url(name), headers={"User-Agent": "SmartTrafficAI"}),
                timeout=30,
            ) as response,
            NamedTemporaryFile(dir=destination.parent, suffix=".pt", delete=False) as stream,
        ):
            temporary = Path(stream.name)
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise ValueError("A modellfájl meghaladja a 256 MiB-os letöltési korlátot.")
                digest.update(chunk)
                stream.write(chunk)
        model = _load_yolo(temporary)
        expected = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
        if not expected.issubset(set(model.names.values())):
            raise ValueError("A letöltött modellből hiányoznak a közlekedési osztályok.")
        del model
        temporary.replace(destination)
        destination.with_suffix(".sha256").write_text(digest.hexdigest() + "\n", encoding="ascii")
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
