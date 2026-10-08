import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def depth_client(tmp_path, monkeypatch):
    source = tmp_path / "colored.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=96x64:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=duration=3", "-shortest",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
    ], check=True)
    output = tmp_path / "output"
    temp = tmp_path / "temp"
    output.mkdir()
    temp.mkdir()
    downloads = []
    scheduled = []

    async def download(url, destination):
        downloads.append(url)
        shutil.copyfile(source, destination)

    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "TEMP_DIR", str(temp))
    monkeypatch.setattr(main, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(main, "download_file", download)
    monkeypatch.setattr(main, "schedule_file_deletion", scheduled.append)
    return TestClient(main.app), temp, downloads, scheduled


def request(client, **overrides):
    return client.post("/prepare-depth", headers={"X-API-Key": "test-key"}, json={
        "video_url": "https://example.com/depth.mp4",
        "source_duration_seconds": 2.5,
        **overrides,
    })


def test_prepare_depth_retimes_removes_color_and_audio(depth_client):
    client, temp, downloads, scheduled = depth_client
    response = request(client)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["grayscale"] is True
    assert abs(result["original_duration_seconds"] - 3) < 0.05
    assert abs(result["duration_seconds"] - 2.5) < 0.05
    path = result["output_path"]
    assert scheduled == [path]
    assert len(downloads) == 1
    assert list(temp.iterdir()) == []
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", path,
    ]))
    assert len(probe["streams"]) == 1
    stream = probe["streams"][0]
    assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (96, 64, "30/1")
    pixels = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    assert all(max(pixels[i:i+3]) - min(pixels[i:i+3]) <= 2 for i in range(0, len(pixels), 3))
    assert max(pixels) - min(pixels) > 100
    frame_bytes = 96 * 64 * 3
    assert pixels[:frame_bytes] != pixels[-frame_bytes:]


@pytest.mark.parametrize("duration", [0, -1, "NaN", "Infinity"])
def test_prepare_depth_rejects_invalid_duration_before_download(depth_client, duration):
    client, _, downloads, _ = depth_client
    assert request(client, source_duration_seconds=duration).status_code == 422
    assert downloads == []


def test_prepare_depth_requires_auth(depth_client):
    client, temp, downloads, _ = depth_client
    assert client.post("/prepare-depth", json={"video_url": "https://example.com/a.mp4", "source_duration_seconds": 3}).status_code == 401
    assert downloads == []
    assert list(temp.iterdir()) == []


def test_prepare_depth_cleans_partial_output_on_failure(depth_client, monkeypatch):
    client, temp, _, scheduled = depth_client

    def fail(input_path, output_path, duration):
        with open(output_path, "wb") as partial:
            partial.write(b"partial")
        raise ValueError("Invalid depth video duration")

    monkeypatch.setattr(main, "prepare_depth_video", fail)
    response = request(client)
    assert response.status_code == 422
    assert scheduled == []
    assert list(temp.iterdir()) == []
    assert list(Path(main.OUTPUT_DIR).iterdir()) == []
