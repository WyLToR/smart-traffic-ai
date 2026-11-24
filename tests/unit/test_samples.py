import pytest
import yaml

from smarttraffic_ai.samples import (
    available_samples,
    sample_for_hash,
    validate_frame_count,
    video_digest,
)


def manifest(root, entries):
    (root / "config").mkdir(exist_ok=True)
    (root / "config/video-samples.yaml").write_text(
        yaml.safe_dump({"videos": entries}), encoding="utf-8"
    )


def test_registered_uppercase_and_private_videos_are_discovered_without_duplicates(tmp_path):
    directory = tmp_path / "data/samples/private"
    directory.mkdir(parents=True)
    source = directory / "IMG_6277.MP4"
    source.write_bytes(b"video")
    manifest(
        tmp_path,
        [
            {"path": str(source), "label": "Own intersection"},
            {"path": "missing.MP4", "label": "Unavailable"},
        ],
    )
    samples = available_samples(tmp_path)
    assert len(samples) == 1 and samples[0].label == "Own intersection"
    assert (tmp_path / samples[0].path).resolve() == source.resolve()


def test_digest_changes_when_the_file_is_replaced(tmp_path):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"first")
    first = video_digest(path)
    path.write_bytes(b"different contents")
    assert video_digest(path) != first


def test_only_a_hash_matched_verified_count_can_override_container_metadata(tmp_path):
    digest = "a" * 64
    manifest(
        tmp_path,
        [
            {
                "path": "original.MP4",
                "label": "Verified sample",
                "sha256": digest,
                "verified_decoded_frames": 16994,
            }
        ],
    )
    assert not available_samples(tmp_path)
    # An uploaded byte-identical copy can use the calibration even if the original was moved.
    assert sample_for_hash(tmp_path, digest) is not None
    assert validate_frame_count(tmp_path, digest, 17000, 16994)
    assert validate_frame_count(tmp_path, digest, 16994, 16994) is None
    with pytest.raises(ValueError, match="Hiányos"):
        validate_frame_count(tmp_path, "b" * 64, 17000, 16994)
    with pytest.raises(ValueError, match="Hiányos"):
        validate_frame_count(tmp_path, digest, 17000, 16993)
