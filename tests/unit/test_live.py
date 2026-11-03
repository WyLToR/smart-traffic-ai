import base64
import io
import json
import time

import pytest

from smarttraffic_ai import live


def test_budapest_camera_page_is_recognized_without_loading_html():
    source = "https://kozutfigyelo.budapestkozut.hu/list/camerahistory?id=10003"
    assert live.budapest_camera_id(source) == "10003"
    assert live.resolve_source(source) == source


@pytest.mark.parametrize("query", ["", "id=abc", "id=-1", "id=1&id=2"])
def test_invalid_budapest_camera_id_is_reported(query):
    with pytest.raises(ValueError):
        live.resolve_source("https://kozutfigyelo.budapestkozut.hu/list/camerahistory?" + query)


def test_budapest_public_image_request_decodes_image_and_timestamp(monkeypatch):
    def fetch(request, timeout):
        assert request.get_method() == "POST"
        assert request.full_url.endswith("/api/ikszr/cameraimage")
        assert json.loads(request.data) == {"thumbnail": 0, "externalId": "10003"}
        return io.BytesIO(
            json.dumps(
                {
                    "success": True,
                    "data": {
                        "image": base64.b64encode(b"jpeg-content").decode(),
                        "createdAt": "2026-11-03 11:10:25",
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(live, "urlopen", fetch)
    assert live.fetch_budapest_image("10003") == (b"jpeg-content", "2026-11-03 11:10:25")


@pytest.mark.parametrize(
    "response",
    [
        b'{"success":false,"data":{}}',
        b'{"success":true,"data":{"image":"invalid-base64"}}',
        b"<html>unavailable</html>",
    ],
)
def test_budapest_unavailable_or_invalid_image_is_reported(monkeypatch, response):
    monkeypatch.setattr(live, "urlopen", lambda *args, **kwargs: io.BytesIO(response))
    with pytest.raises(ValueError, match="Budapest Közút"):
        live.fetch_budapest_image("10003")


@pytest.mark.parametrize("source", ["blob:https://www.idokep.hu/123", "file:///a.mp4", "hello"])
def test_local_and_browser_urls_are_rejected(source):
    with pytest.raises(ValueError):
        live.validate_source(source)


def test_idokep_resolves_the_current_embedded_player(monkeypatch):
    requested = []

    def open_page(url, timeout):
        requested.append(url)
        response = io.BytesIO(
            b'<source src="//cam.idokep.hu/live/camera/current.m3u8?x=1&amp;y=2">'
        )
        response.url = url
        return response

    monkeypatch.setattr(live, "urlopen", open_page)
    page = "https://www.idokep.hu/webkamera/hgabesz"
    assert live.resolve_source(page) == "https://cam.idokep.hu/live/camera/current.m3u8?x=1&y=2"
    assert requested == [page]
    assert live.resolve_source("rtsp://camera/live") == "rtsp://camera/live"
    assert requested == [page]


def test_missing_hls_player_is_reported(monkeypatch):
    response = io.BytesIO(b"<html>No video</html>")
    response.url = "https://www.idokep.hu/webkamera/offline"
    monkeypatch.setattr(live, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match="nem található"):
        live.resolve_source(response.url)


def test_idokep_snapshot_uses_main_image_not_nearby_camera(monkeypatch):
    response = io.BytesIO(
        b'<img src="//cam.idokep.hu/neighbor/thumbnail.jpg">'
        b'<img id="realcamimg" src="//cam.idokep.hu/kamera.php?user=kevenet&amp;token=current">'
    )
    response.url = "https://www.idokep.hu/webkamera/kevenet"
    monkeypatch.setattr(live, "urlopen", lambda *args, **kwargs: response)
    source = live.resolve_source(response.url)
    assert source == "https://cam.idokep.hu/kamera.php?user=kevenet&token=current"


def test_visibility_does_not_include_network_stalls():
    assert live.observation_duration(10, None, 5) == pytest.approx(0.2)
    assert live.observation_duration(10.1, 10, 5) == pytest.approx(0.1)
    assert live.observation_duration(20, 10, 5) == pytest.approx(0.2)
    assert not live.fresh(None)
    assert not live.fresh({"received_at": time.monotonic() - 10})
    assert live.fresh({"received_at": time.monotonic()})
