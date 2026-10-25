import json
import os
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

import main

HEADERS = {"X-API-Key": "test-key"}
# Point these at a setup-face-mesh.sh environment to run the worker for real.
MESH_PYTHON = os.getenv("FACE_MESH_TEST_PYTHON")
MESH_MODEL = os.getenv("FACE_MESH_TEST_MODEL")
MESH_DETECTOR = os.getenv("FACE_MESH_TEST_DETECTOR")


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


@pytest.mark.skipif(not (MESH_PYTHON and MESH_MODEL and MESH_DETECTOR), reason="set FACE_MESH_TEST_PYTHON, FACE_MESH_TEST_MODEL and FACE_MESH_TEST_DETECTOR")
def test_face_mesh_keeps_the_guide_frames_and_audio(mesh, monkeypatch):
    client, files, tmp, temp = mesh
    monkeypatch.setattr(main, "FACE_MESH_PYTHON", MESH_PYTHON)
    monkeypatch.setattr(main, "FACE_MESH_MODEL", MESH_MODEL)
    monkeypatch.setattr(main, "FACE_DETECTOR_MODEL", MESH_DETECTOR)
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


def test_face_mesh_kills_the_worker_and_its_children_on_timeout(mesh, monkeypatch, tmp_path):
    client, files, tmp, temp = mesh
    # A stand-in worker that starts a child and never finishes.
    worker = tmp_path / "slow_worker.py"
    pid_file = tmp_path / "child.pid"
    worker.write_text(
        "import subprocess, time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    model = tmp_path / "model.task"
    model.write_text("x")
    monkeypatch.setattr(main, "FACE_MESH_PYTHON", os.sys.executable)
    monkeypatch.setattr(main, "FACE_MESH_WORKER", str(worker))
    monkeypatch.setattr(main, "FACE_MESH_MODEL", str(model))
    monkeypatch.setattr(main, "FACE_DETECTOR_MODEL", str(model))
    real_popen = subprocess.Popen

    class QuickTimeout(real_popen):
        def communicate(self, input=None, timeout=None):
            return super().communicate(input, timeout=2 if timeout else None)

    monkeypatch.setattr(main.subprocess, "Popen", QuickTimeout)
    clip = tmp / "clip.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x48:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip))
    files.update({"https://example.com/a.mp4": clip, "https://example.com/b.mp4": clip})
    response = client.post("/face-mesh", headers=HEADERS, json={"video_url": "https://example.com/a.mp4", "guide_url": "https://example.com/b.mp4"})
    assert response.status_code == 422 and "timed out" in response.text
    child = int(pid_file.read_text())
    # The orphaned child is reparented and reaped; give that a moment.
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the worker's child process survived the timeout")


def test_trim_heads_cuts_the_hair_outline_but_keeps_the_head_neck_and_body():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    pytest.importorskip("mediapipe")
    import face_mesh_worker as worker

    depth = (80, 40, 120)
    frame = np.zeros((200, 200, 3), np.uint8)
    frame[:] = depth
    # A gray silhouette: long hair falling past the shoulders around a face, then a body.
    frame[25:140, 60:140] = 126   # the hair mass, with a bun on top
    frame[120:200, 50:150] = 126  # shoulders and body
    face = [(85, 60), (115, 60), (85, 100), (115, 100)]  # the mesh's box: 30 wide, 40 tall
    out = worker.trim_heads(frame, [face]).astype(int)
    gray = lambda y, x: np.abs(out[y, x] - 126).max() <= 12
    assert gray(80, 100), "the face stays"
    assert gray(108, 100), "the neck stays"
    assert gray(190, 100), "the body below the chin stays"
    assert not gray(80, 66) and not gray(80, 134), "the hair beside the face is cut"
    assert not gray(30, 100), "the bun above the head is cut"
    assert np.abs(out[80, 66] - depth).max() <= 30, "the cut is painted with the depth around it"
    assert (out[5, 5] == depth).all(), "the background is untouched"
    neighbour = frame.copy()
    neighbour[0:100, 0:56] = 126  # someone else's arm raised beside the hair, not touching it
    kept = worker.trim_heads(neighbour, [face]).astype(int)
    assert np.abs(kept[60, 40] - 126).max() <= 12, "a neighbour's silhouette inside the ring stays"
    assert np.abs(kept[80, 66] - depth).max() <= 30, "the face's own hair is still cut"
    huge = [(10, 5), (190, 5), (10, 195), (190, 195)]
    assert (worker.trim_heads(frame, [huge]) == frame).all(), "a face filling the frame is never trimmed"
