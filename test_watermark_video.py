import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main


def make_clip(path, size, seconds, audio=True):
    sources = ["-f", "lavfi", "-i", f"color=c=black:size={size}:rate=30:duration={seconds}"]
    if audio:
        sources += ["-f", "lavfi", "-i", f"sine=duration={seconds}", "-shortest", "-c:a", "aac"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *sources, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.fixture
def watermark_client(tmp_path, monkeypatch):
    output = tmp_path / "output"
    temp = tmp_path / "temp"
    output.mkdir()
    temp.mkdir()
    sources = {}

    async def download(url, destination):
        shutil.copyfile(sources[url], destination)

    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "TEMP_DIR", str(temp))
    monkeypatch.setattr(main, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(main, "download_file", download)
    monkeypatch.setattr(main, "schedule_file_deletion", lambda path: None)
    return TestClient(main.app), tmp_path, sources, temp


def watermark(client, url):
    return client.post("/watermark", headers={"X-API-Key": "test-key"}, json={"video_url": url})


def corner_brightness(path, width, height, corner):
    """Mean luma of a small box in one corner of the last frame."""
    box = min(width, height) // 6
    x = width - box if corner.endswith("right") else 0
    y = height - box if corner.startswith("bottom") else 0
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-sseof", "-0.1", "-i", path, "-frames:v", "1",
        "-vf", f"crop={box}:{box}:{x}:{y},format=gray", "-f", "rawvideo", "-",
    ])
    return sum(raw) / len(raw)


@pytest.mark.parametrize("size", ["720x1280", "1280x720"])
def test_watermark_marks_bottom_right_and_keeps_shape_length_and_audio(watermark_client, size):
    client, tmp_path, sources, temp = watermark_client
    sources["https://example.com/a.mp4"] = tmp_path / "a.mp4"
    make_clip(sources["https://example.com/a.mp4"], size, 3)
    response = watermark(client, "https://example.com/a.mp4")
    assert response.status_code == 200, response.text
    result = response.json()
    width, height = map(int, size.split("x"))
    assert (result["width"], result["height"]) == (width, height)
    assert abs(result["duration_seconds"] - 3) < 0.15
    assert result["has_audio"] is True
    # The white mark lights up the bottom-right of a black clip and nothing else, to the last frame.
    marked = corner_brightness(result["output_path"], width, height, "bottom-right")
    assert marked > corner_brightness(result["output_path"], width, height, "top-left") + 5
    assert list(temp.iterdir()) == []


def test_watermark_handles_silent_video(watermark_client):
    client, tmp_path, sources, _ = watermark_client
    sources["https://example.com/s.mp4"] = tmp_path / "s.mp4"
    make_clip(sources["https://example.com/s.mp4"], "640x640", 2, audio=False)
    response = watermark(client, "https://example.com/s.mp4")
    assert response.status_code == 200, response.text
    assert response.json()["has_audio"] is False


def test_watermark_rejects_overlong_video(watermark_client, monkeypatch):
    client, tmp_path, sources, _ = watermark_client
    monkeypatch.setattr(main, "WATERMARK_MAX_SECONDS", 1)
    sources["https://example.com/l.mp4"] = tmp_path / "l.mp4"
    make_clip(sources["https://example.com/l.mp4"], "320x320", 2)
    response = watermark(client, "https://example.com/l.mp4")
    assert response.status_code == 422
    assert "at most" in response.json()["detail"]


def test_watermark_rejects_oversized_frame(watermark_client, monkeypatch):
    client, tmp_path, sources, _ = watermark_client
    monkeypatch.setattr(main, "WATERMARK_MAX_LONG_SIDE", 320)
    sources["https://example.com/big.mp4"] = tmp_path / "big.mp4"
    make_clip(sources["https://example.com/big.mp4"], "640x360", 1)
    response = watermark(client, "https://example.com/big.mp4")
    assert response.status_code == 422
    assert "long side" in response.json()["detail"]
