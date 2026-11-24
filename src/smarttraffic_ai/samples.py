import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import Field

from smarttraffic_ai.config import Model, load_yaml


class VideoSample(Model):
    path: str
    label: str
    description: str = ""
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    camera_profile: str | None = None
    verified_decoded_frames: int | None = Field(default=None, gt=0)


class VideoSamples(Model):
    videos: list[VideoSample] = Field(default_factory=list)


def available_samples(root: Path) -> list[VideoSample]:
    manifest = root / "config/video-samples.yaml"
    registered = load_yaml(manifest, VideoSamples).videos if manifest.is_file() else []
    result = {}
    for sample in registered:
        path = root / sample.path
        if path.is_file() and path.suffix.lower() == ".mp4":
            result[path.resolve()] = sample
    for directory in (root / "outputs/video-validation/videos", root / "data/samples/private"):
        if directory.is_dir():
            for path in directory.iterdir():
                if path.is_file() and path.suffix.lower() == ".mp4":
                    result.setdefault(path.resolve(), VideoSample(path=str(path), label=path.name))
    return list(result.values())


def sample_for_hash(root: Path, digest: str) -> VideoSample | None:
    manifest = root / "config/video-samples.yaml"
    registered = load_yaml(manifest, VideoSamples).videos if manifest.is_file() else []
    return next((sample for sample in registered if sample.sha256 == digest), None)


def validate_frame_count(root: Path, digest: str, declared: int, decoded: int) -> str | None:
    if declared <= 0 or declared == decoded:
        return None
    sample = sample_for_hash(root, digest)
    if sample and sample.verified_decoded_frames == decoded:
        return (
            f"A konténer {declared} képkockát jelez, az ellenőrzött forrásból {decoded} "
            "dekódolható. A forrás SHA-256 lenyomata egyezik a mintajegyzékkel."
        )
    raise ValueError(f"Hiányos dekódolás: {decoded}/{declared} képkocka olvasható.")


@lru_cache(maxsize=16)
def _file_digest(path: str, size: int, modified: int) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def video_digest(path: Path) -> str:
    stat = path.stat()
    return _file_digest(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
