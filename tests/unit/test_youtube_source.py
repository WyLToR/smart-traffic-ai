import sys
from types import SimpleNamespace

import pytest

from smarttraffic_ai import youtube_source
from smarttraffic_ai.live import validate_source


@pytest.mark.parametrize(
    "value",
    [
        "youtube.com/watch?v=HUeaYuBLNNQ&embeds_referring_origin=https%3A%2F%2Fworldcam.tv",
        "https://www.youtube.com/watch?v=HUeaYuBLNNQ&source_ve_path=NzY3NTg",
        "https://youtu.be/HUeaYuBLNNQ",
        "https://www.youtube.com/live/HUeaYuBLNNQ",
        "https://www.youtube.com/embed/HUeaYuBLNNQ",
    ],
)
def test_youtube_links_are_normalized_and_embedding_parameters_removed(value):
    assert validate_source(value) == "https://www.youtube.com/watch?v=HUeaYuBLNNQ"


@pytest.mark.parametrize(
    "value",
    [
        "https://youtube.com/watch?v=invalid",
        "https://youtube.com/watch?v=HUeaYuBLNNQ&v=abcdefghijk",
        "https://youtube.com/playlist?list=something",
    ],
)
def test_invalid_video_and_playlist_links_are_rejected(value):
    with pytest.raises(ValueError):
        validate_source(value)


@pytest.fixture
def extractor(monkeypatch):
    calls = []
    data = {
        "formats": [
            {
                "protocol": "m3u8_native",
                "height": 360,
                "vcodec": "avc1",
                "url": "https://cam/360.m3u8",
            },
            {
                "protocol": "m3u8_native",
                "height": 720,
                "vcodec": "avc1",
                "url": "https://cam/720.m3u8",
            },
            {
                "protocol": "m3u8_native",
                "height": 1080,
                "vcodec": "avc1",
                "url": "https://cam/full.m3u8",
            },
            {
                "protocol": "m3u8_native",
                "height": 720,
                "vcodec": "avc1",
                "url": "https://cam/drm.m3u8",
                "has_drm": True,
            },
            {"protocol": "https", "height": 720, "vcodec": "avc1", "url": "https://cam/file.mp4"},
        ]
    }

    class Extractor:
        def __init__(self, options):
            calls.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, value, download):
            assert download is False
            return data

    module = SimpleNamespace(YoutubeDL=Extractor, utils=SimpleNamespace(DownloadError=RuntimeError))
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    monkeypatch.setattr(
        youtube_source.shutil, "which", lambda name: "/node" if name == "node" else None
    )
    return data, calls


def test_resolution_selects_720p_hls_without_downloading_a_video(extractor):
    data, calls = extractor
    assert youtube_source.resolve_youtube("https://youtube.com/watch?v=HUeaYuBLNNQ") == (
        "https://cam/720.m3u8"
    )
    assert calls[0]["noplaylist"] is True
    assert calls[0]["skip_download"] is True
    assert calls[0]["js_runtimes"] == {"node": {}}
    assert "cookiesfrombrowser" not in calls[0]


def test_missing_hls_source_is_reported(extractor):
    data, calls = extractor
    data["formats"] = []
    with pytest.raises(ValueError, match="HLS-forrás"):
        youtube_source.resolve_youtube("https://youtube.com/watch?v=HUeaYuBLNNQ")


def test_missing_javascript_runtime_is_reported(extractor, monkeypatch):
    monkeypatch.setattr(youtube_source.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="Node.js"):
        youtube_source.resolve_youtube("https://youtube.com/watch?v=HUeaYuBLNNQ")
