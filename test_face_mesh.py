import json
import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main

HEADERS = {"X-API-Key": "test-key"}
# Point these at a setup-face-mesh.sh environment to run the worker for real.
MESH_PYTHON = os.getenv("FACE_MESH_TEST_PYTHON")
MESH_MODEL = os.getenv("FACE_MESH_TEST_MODEL")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture
def mesh(tmp_path, monkeypatch):
    files = {}
    output, temp = tmp_path / "output", tmp_path / "temp"
    output.mkdir()
    temp.mkdir()

    async def download(url, destination):
        shutil.copyfile(files[str(url)], destination)

    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "TEMP_DIR", str(temp))
    monkeypatch.setattr(main, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(main, "download_file", download)
    monkeypatch.setattr(main, "schedule_file_deletion", lambda path: None)
    return TestClient(main.app), files, tmp_path, temp


def test_face_mesh_reports_when_it_is_not_installed(mesh, monkeypatch):
    client, _, tmp, _ = mesh
    monkeypatch.setattr(main, "FACE_MESH_PYTHON", str(tmp / "missing-python"))
    response = client.post("/face-mesh", headers=HEADERS, json={"video_url": "https://example.com/a.mp4", "guide_url": "https://example.com/b.mp4"})
    assert response.status_code == 503
    assert "not installed" in response.text


@pytest.mark.skipif(not (MESH_PYTHON and MESH_MODEL), reason="set FACE_MESH_TEST_PYTHON and FACE_MESH_TEST_MODEL")
def test_face_mesh_keeps_the_guide_frames_and_audio(mesh, monkeypatch):
    client, files, tmp, temp = mesh
    monkeypatch.setattr(main, "FACE_MESH_PYTHON", MESH_PYTHON)
    monkeypatch.setattr(main, "FACE_MESH_MODEL", MESH_MODEL)
    source, guide = tmp / "source.mp4", tmp / "guide.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=128x96:rate=24:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=128x96:r=24:d=1", "-f", "lavfi", "-i", "sine=duration=1",
           "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(guide))
    files.update({"https://example.com/source.mp4": source, "https://example.com/guide.mp4": guide})
    response = client.post("/face-mesh", headers=HEADERS, json={"video_url": "https://example.com/source.mp4", "guide_url": "https://example.com/guide.mp4"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["frames"], result["tracked_frames"], result["faces"]) == (24, 0, 0)
    streams = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=codec_type,nb_read_frames", "-of", "json", result["output_path"]]))["streams"]
    assert sorted(stream["codec_type"] for stream in streams) == ["audio", "video"]
    assert int(next(s for s in streams if s["codec_type"] == "video")["nb_read_frames"]) == 24
    assert list(temp.iterdir()) == []

    short = tmp / "short.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=128x96:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(short))
    files["https://example.com/short.mp4"] = short
    response = client.post("/face-mesh", headers=HEADERS, json={"video_url": "https://example.com/source.mp4", "guide_url": "https://example.com/short.mp4"})
    assert response.status_code == 422
