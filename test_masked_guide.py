import io
import json
import shutil
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

import main

HEADERS = {"X-API-Key": "test-key"}


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


@pytest.fixture
def guide(tmp_path, monkeypatch):
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
        "mask_zips": [{"url": "https://example.com/masks.zip"}], "audio_url": "https://example.com/audio.wav",
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["frames"], result["masked_frames"], result["has_audio"]) == (24, 10, True)
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
