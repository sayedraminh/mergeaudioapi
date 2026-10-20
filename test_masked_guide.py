import io
import json
import os
import shutil
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

import main

HEADERS = {"X-API-Key": "test-key"}
# Point this at a setup-face-mesh.sh environment to run the composite worker;
# without it only the FFmpeg composite runs.
WORKER_PYTHON = os.getenv("FACE_MESH_TEST_PYTHON")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def frame_pixels(path, frame, width, height):
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{frame})",
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    assert len(data) == width * height * 3
    return lambda x, y: tuple(data[(y * width + x) * 3:(y * width + x) * 3 + 3])


def stream_info(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,nb_read_frames,duration", "-of", "json", str(path),
    ]))["streams"]


@pytest.fixture(params=["ffmpeg", "worker"])
def guide(request, tmp_path, monkeypatch):
    if request.param == "worker" and not WORKER_PYTHON:
        pytest.skip("set FACE_MESH_TEST_PYTHON to run the composite worker")
    monkeypatch.setattr(main, "FACE_MESH_PYTHON", WORKER_PYTHON if request.param == "worker" else str(tmp_path / "missing-python"))
    files = {}
    output = tmp_path / "output"
    temp = tmp_path / "temp"
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


def test_normalize_video_uses_one_clock_for_video_and_audio(guide):
    client, files, tmp, temp = guide
    source = tmp / "source.mp4"
    # 30 fps video of 2.5 s with 3 s of audio: the video decides the length.
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=200x100:rate=30:duration=2.5",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source))
    files["https://example.com/source.mp4"] = source
    response = client.post("/normalize-video", headers=HEADERS, json={"video_url": "https://example.com/source.mp4", "fps": 24, "max_dimension": 100})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["width"], result["height"], result["fps"], result["frames"]) == (100, 50, 24, 60)
    assert result["has_audio"] is True
    video, audio = sorted(stream_info(result["output_path"]), key=lambda s: s["codec_type"], reverse=True)
    assert (video["width"], video["height"], video["r_frame_rate"], int(video["nb_read_frames"])) == (100, 50, "24/1", 60)
    assert abs(float(audio["duration"]) - 2.5) < 0.05
    assert list(temp.iterdir()) == []


def test_pitch_audio_keeps_length_and_raises_frequency(guide):
    client, files, tmp, _ = guide
    source = tmp / "vocals.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(source))
    files["https://example.com/vocals.wav"] = source
    response = client.post("/pitch-audio", headers=HEADERS, json={"audio_url": "https://example.com/vocals.wav", "semitones": 12})
    assert response.status_code == 200, response.text
    result = response.json()
    assert abs(result["duration_seconds"] - 2) < 0.05
    samples = subprocess.check_output(["ffmpeg", "-v", "error", "-i", result["output_path"], "-ac", "1", "-ar", "8000", "-f", "s16le", "-"])
    values = [int.from_bytes(samples[i:i + 2], "little", signed=True) for i in range(0, len(samples), 2)][4000:12000]
    crossings = sum(1 for a, b in zip(values, values[1:]) if a < 0 <= b)
    # One octave up: about 880 rising zero crossings per second of steady tone.
    assert 800 < crossings < 960


def test_composite_masks_aligns_frames_and_blanks_missing_ones(guide):
    client, files, tmp, temp = guide
    video, depth, audio = tmp / "video.mp4", tmp / "depth.mp4", tmp / "audio.wav"
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x32:r=24:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    # Depth at another rate and size; it is put on the video's grid.
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=128x64:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(depth))
    ffmpeg("-f", "lavfi", "-i", "sine=duration=0.5", str(audio))
    mask = tmp / "mask.png"
    # Left half white: SAM found someone there.
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x32", "-vf", "drawbox=x=0:y=0:w=32:h=32:color=white:t=fill", "-frames:v", "1", str(mask))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        # Frames 0-9 masked, 10-23 missing (nobody found).
        for index in range(10):
            handle.write(mask, f"masks/mask_{index:05d}.png")
    (tmp / "masks.zip").write_bytes(archive.getvalue())
    files.update({
        "https://example.com/video.mp4": video, "https://example.com/depth.mp4": depth,
        "https://example.com/masks.zip": tmp / "masks.zip", "https://example.com/audio.wav": audio,
    })
    response = client.post("/composite-masks", headers=HEADERS, json={
        "video_url": "https://example.com/video.mp4", "depth_url": "https://example.com/depth.mp4",
        "mask_zips": [{"url": "https://example.com/masks.zip"}], "audio_url": "https://example.com/audio.wav", "slim_share": 0.12,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["frames"], result["masked_frames"], result["has_audio"]) == (24, 10, True)
    # Only the composite worker can slim; the response says which one drew the guide.
    worker = bool(WORKER_PYTHON) and main.FACE_MESH_PYTHON == WORKER_PYTHON
    assert result["slim_share"] == (0.12 if worker else 0)
    streams = stream_info(result["output_path"])
    assert int(next(s for s in streams if s["codec_type"] == "video")["nb_read_frames"]) == 24
    # Audio is padded to the video length.
    assert abs(float(next(s for s in streams if s["codec_type"] == "audio")["duration"]) - 1) < 0.05
    masked = frame_pixels(result["output_path"], 5, 64, 32)
    assert masked(8, 16)[0] > 200 and masked(8, 16)[2] < 60  # depth (red) inside the mask
    assert masked(56, 16)[2] > 200 and masked(56, 16)[0] < 60  # original (blue) outside
    blank = frame_pixels(result["output_path"], 20, 64, 32)
    assert blank(8, 16)[2] > 200  # missing mask frame keeps the original
    assert list(temp.iterdir()) == []


def test_composite_masks_offsets_later_zips_and_rejects_empty_masks(guide):
    client, files, tmp, _ = guide
    video, depth = tmp / "video.mp4", tmp / "depth.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x32:r=24:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x32:r=24:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(depth))
    mask = tmp / "mask.png"
    ffmpeg("-f", "lavfi", "-i", "color=c=white:s=64x32", "-frames:v", "1", str(mask))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(mask, "mask_00000.png")
    (tmp / "second.zip").write_bytes(archive.getvalue())
    empty = io.BytesIO()
    zipfile.ZipFile(empty, "w").close()
    (tmp / "empty.zip").write_bytes(empty.getvalue())
    files.update({"https://example.com/v.mp4": video, "https://example.com/d.mp4": depth,
                  "https://example.com/second.zip": tmp / "second.zip", "https://example.com/empty.zip": tmp / "empty.zip"})
    body = {"video_url": "https://example.com/v.mp4", "depth_url": "https://example.com/d.mp4"}
    response = client.post("/composite-masks", headers=HEADERS, json={**body, "mask_zips": [{"url": "https://example.com/second.zip", "start_frame": 12}]})
    assert response.status_code == 200, response.text
    assert response.json()["masked_frames"] == 1
    assert frame_pixels(response.json()["output_path"], 12, 64, 32)(32, 16)[0] > 200
    assert frame_pixels(response.json()["output_path"], 0, 64, 32)(32, 16)[2] > 200
    response = client.post("/composite-masks", headers=HEADERS, json={**body, "mask_zips": [{"url": "https://example.com/empty.zip"}]})
    assert response.status_code == 422
    assert "no people" in response.text


def test_guide_endpoints_refuse_playlists(guide):
    client, files, tmp, temp = guide
    playlist = tmp / "playlist.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n")
    files["https://example.com/p"] = playlist
    for path, body in [
        ("/normalize-video", {"video_url": "https://example.com/p"}),
        ("/pitch-audio", {"audio_url": "https://example.com/p"}),
    ]:
        response = client.post(path, headers=HEADERS, json=body)
        assert response.status_code == 422, response.text
        assert "Unsupported media format" in response.text
    assert list(temp.iterdir()) == []


def test_composite_masks_fills_gaps_closed_by_the_person_and_bottom_edge(guide):
    client, files, tmp, _ = guide
    video, depth = tmp / "video.mp4", tmp / "depth.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x32:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x32:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(depth))
    mask = tmp / "mask.png"
    # A torso (x 8-40) with a tie-shaped gap (x 20-28) running to the bottom edge.
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x32", "-vf",
           "drawbox=x=8:y=4:w=32:h=28:color=white:t=fill,drawbox=x=20:y=12:w=8:h=20:color=black:t=fill",
           "-frames:v", "1", str(mask))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        for index in range(12):
            handle.write(mask, f"mask_{index:05d}.png")
    (tmp / "m.zip").write_bytes(archive.getvalue())
    files.update({"https://example.com/v.mp4": video, "https://example.com/d.mp4": depth, "https://example.com/m.zip": tmp / "m.zip"})
    body = {"video_url": "https://example.com/v.mp4", "depth_url": "https://example.com/d.mp4", "mask_zips": [{"url": "https://example.com/m.zip"}]}
    filled = client.post("/composite-masks", headers=HEADERS, json=body)
    assert filled.status_code == 200, filled.text
    pixel = frame_pixels(filled.json()["output_path"], 3, 64, 32)
    assert pixel(24, 24)[0] > 200  # the gap now shows depth
    assert pixel(54, 16)[2] > 200  # open background stays original
    assert pixel(54, 31)[2] > 200  # including the bottom row
    kept = client.post("/composite-masks", headers=HEADERS, json={**body, "fill_holes": False})
    assert frame_pixels(kept.json()["output_path"], 3, 64, 32)(24, 24)[2] > 200


def test_composite_masks_unions_two_zips_for_the_same_frames(guide):
    client, files, tmp, _ = guide
    video, depth = tmp / "video.mp4", tmp / "depth.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x32:r=24:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x32:r=24:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(depth))
    left, right = tmp / "left.png", tmp / "right.png"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x32", "-vf", "drawbox=x=0:y=0:w=32:h=32:color=white:t=fill,format=gray", "-frames:v", "1", str(left))
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x32", "-vf", "drawbox=x=32:y=0:w=32:h=32:color=white:t=fill,format=gray", "-frames:v", "1", str(right))
    for name, mask in (("people.zip", left), ("characters.zip", right)):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(mask, "mask_00000.png")
        (tmp / name).write_bytes(archive.getvalue())
        files[f"https://example.com/{name}"] = tmp / name
    files.update({"https://example.com/v.mp4": video, "https://example.com/d.mp4": depth})
    response = client.post("/composite-masks", headers=HEADERS, json={
        "video_url": "https://example.com/v.mp4", "depth_url": "https://example.com/d.mp4",
        "mask_zips": [{"url": "https://example.com/people.zip"}, {"url": "https://example.com/characters.zip"}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["masked_frames"] == 1
    pixel = frame_pixels(response.json()["output_path"], 0, 64, 32)
    assert pixel(10, 16)[0] > 200 and pixel(54, 16)[0] > 200, "both halves come from the depth video"
    assert pixel(10, 16)[2] < 100 and pixel(54, 16)[2] < 100


@pytest.fixture
def worker_guide(guide):
    if not WORKER_PYTHON or main.FACE_MESH_PYTHON != WORKER_PYTHON:
        pytest.skip("runs only on the composite worker")
    return guide


def test_composite_worker_drops_border_bands_and_paints_the_ring_with_the_person(worker_guide):
    client, files, tmp, _ = worker_guide
    video, depth = tmp / "video.mp4", tmp / "depth.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=128x96:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    # Depth: the person's side red, the background's green.
    ffmpeg("-f", "lavfi", "-i", "color=c=green:s=128x96:r=24:d=0.5", "-vf", "drawbox=x=0:y=0:w=80:h=96:color=red:t=fill",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(depth))
    mask = tmp / "mask.png"
    # A person (x 40-80) standing on the bottom edge, and a 4 px strip down the left edge.
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=128x96", "-vf",
           "drawbox=x=40:y=20:w=40:h=76:color=white:t=fill,drawbox=x=0:y=0:w=4:h=96:color=white:t=fill",
           "-frames:v", "1", str(mask))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        for index in range(12):
            handle.write(mask, f"mask_{index:05d}.png")
    (tmp / "m.zip").write_bytes(archive.getvalue())
    files.update({"https://example.com/v.mp4": video, "https://example.com/d.mp4": depth, "https://example.com/m.zip": tmp / "m.zip"})
    response = client.post("/composite-masks", headers=HEADERS, json={
        "video_url": "https://example.com/v.mp4", "depth_url": "https://example.com/d.mp4",
        "mask_zips": [{"url": "https://example.com/m.zip"}], "spread_pixels": 6,
    })
    assert response.status_code == 200, response.text
    pixel = frame_pixels(response.json()["output_path"], 3, 128, 96)
    assert pixel(2, 48)[2] > 200, "the edge strip is dropped"
    assert pixel(60, 60)[0] > 200, "depth inside the person"
    ring = pixel(84, 60)
    assert ring[0] > 200 and ring[1] < 80, "the grown ring takes the person's depth, not the background's"
    assert pixel(100, 60)[2] > 200, "background beyond the ring stays original"


def test_composite_worker_decodes_masks_only_as_png(worker_guide):
    client, files, tmp, _ = worker_guide
    video, depth = tmp / "video.mp4", tmp / "depth.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x32:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x32:r=24:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(depth))
    png, bmp = tmp / "mask.png", tmp / "mask.bmp"
    ffmpeg("-f", "lavfi", "-i", "color=c=white:s=64x32", "-frames:v", "1", str(png))
    ffmpeg("-f", "lavfi", "-i", "color=c=white:s=64x32", "-frames:v", "1", str(bmp))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(png, "mask_00000.png")
        # Only the first mask is probed on unpack; a later one in another format must not be decoded.
        handle.write(bmp, "mask_00001.png")
    (tmp / "m.zip").write_bytes(archive.getvalue())
    files.update({"https://example.com/v.mp4": video, "https://example.com/d.mp4": depth, "https://example.com/m.zip": tmp / "m.zip"})
    response = client.post("/composite-masks", headers=HEADERS, json={
        "video_url": "https://example.com/v.mp4", "depth_url": "https://example.com/d.mp4", "mask_zips": [{"url": "https://example.com/m.zip"}],
    })
    assert response.status_code == 422, response.text


def test_unpack_masks_refuses_a_playlist_disguised_as_a_png(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("mask_00000.png", "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n")
    masks = tmp_path / "masks"
    masks.mkdir()
    with pytest.raises(ValueError, match="not a PNG"):
        main.unpack_mask_zips([(str(archive), 0)], str(masks), 4)


def test_unpack_masks_unions_three_overlapping_zips_in_one_pass_each(tmp_path, monkeypatch):
    stripes = []
    for index, x in enumerate((0, 21, 42)):
        mask = tmp_path / f"stripe{index}.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x32", "-vf", f"drawbox=x={x}:y=0:w=21:h=32:color=white:t=fill,format=gray", "-frames:v", "1", str(mask))
        archive = tmp_path / f"stripe{index}.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(mask, "mask_00000.png")
            handle.write(mask, "mask_00001.png")
        stripes.append((str(archive), 0))
    runs = []
    real_run = main.subprocess.run
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **kwargs: (runs.append(cmd), real_run(cmd, **kwargs))[1])
    masks = tmp_path / "masks"
    masks.mkdir()
    found, size = main.unpack_mask_zips(stripes, str(masks), 3)
    assert (found, size) == (2, (64, 32))
    assert sum("blend=all_mode=lighten" in " ".join(cmd) for cmd in runs) == 2, "one union pass per extra layer"
    data = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(masks / "mask_00001.png"), "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    assert all(data[16 * 64 + x] > 200 for x in (5, 30, 55)), "every stripe survives the union"
    assert sorted(path.name for path in masks.iterdir()) == ["blank.png", "mask_00000.png", "mask_00001.png", "mask_00002.png"]
