import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main


def make_clip(path, size, seconds, crf):
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=duration={seconds}", "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], check=True)


@pytest.fixture
def compress_client(tmp_path, monkeypatch):
    output = tmp_path / "output"
    temp = tmp_path / "temp"
    output.mkdir()
    temp.mkdir()
    sources = {}
    scheduled = []

    async def download(url, destination):
        shutil.copyfile(sources[url], destination)

    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "TEMP_DIR", str(temp))
    monkeypatch.setattr(main, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(main, "download_file", download)
    monkeypatch.setattr(main, "schedule_file_deletion", scheduled.append)
    return TestClient(main.app), tmp_path, sources, temp, scheduled


def compress(client, url, **overrides):
    return client.post("/compress-video", headers={"X-API-Key": "test-key"}, json={"video_url": url, **overrides})


def probe(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height", "-of", "json", path,
    ]))["streams"]


def test_compress_keeps_quality_pass_when_it_fits(compress_client):
    client, tmp_path, sources, temp, scheduled = compress_client
    sources["https://example.com/a.mp4"] = tmp_path / "a.mp4"
    make_clip(sources["https://example.com/a.mp4"], "1280x720", 3, 0)
    response = compress(client, "https://example.com/a.mp4")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "crf"
    assert result["size_bytes"] <= 10 * 1024 * 1024
    assert result["has_audio"] is True
    assert (result["width"], result["height"]) == (1280, 720)
    assert scheduled == [result["output_path"]]
    assert list(temp.iterdir()) == []
    assert {stream["codec_name"] for stream in probe(result["output_path"])} == {"h264", "aac"}


def test_compress_caps_short_side_and_fits_size_with_bitrate_pass(compress_client):
    client, tmp_path, sources, _, _ = compress_client
    sources["https://example.com/b.mp4"] = tmp_path / "b.mp4"
    make_clip(sources["https://example.com/b.mp4"], "1440x2560", 6, 0)
    response = compress(client, "https://example.com/b.mp4", max_bytes=1024 * 1024)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "bitrate"
    assert result["size_bytes"] <= 1024 * 1024
    assert (result["width"], result["height"]) == (1080, 1920)
    assert abs(result["duration_seconds"] - 6) < 0.2
    assert not list(Path(result["output_path"]).parent.glob("*.pass*"))


def test_compress_rejects_clips_too_long_for_the_limit(compress_client):
    client, tmp_path, sources, temp, _ = compress_client
    sources["https://example.com/c.mp4"] = tmp_path / "c.mp4"
    make_clip(sources["https://example.com/c.mp4"], "640x360", 30, 0)
    response = compress(client, "https://example.com/c.mp4", max_bytes=1024 * 1024)
    assert response.status_code == 422
    assert "too long" in response.json()["detail"]
    assert list(temp.iterdir()) == []
