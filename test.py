import pytest
import httpx
import asyncio
import json
import os
import tempfile
import shutil
import subprocess
import uuid
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from fastapi import HTTPException
from main import (
    DELETE_AFTER_SECONDS,
    OUTPUT_DIR,
    TEMP_DIR,
    app,
    get_media_duration,
    has_audio_stream,
    resolve_path_within_directory,
)

load_dotenv()

API_KEY = os.getenv("API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

client = TestClient(app)

SAMPLE_VIDEO_URL = "https://media.nsketchai.com/videos/1769050552017-u9o0aq.mp4"
SAMPLE_AUDIO_URL = "https://media.nsketchai.com/audiofiles/turnthelightsoff.mp3"


def _run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _create_png_frame(output_path, color):
    _run_command([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=64x64:d=0.04",
        "-frames:v", "1",
        str(output_path)
    ])


def _create_lossless_test_video(tmp_path, colors, filename):
    frames_dir = tmp_path / f"{filename}_frames"
    frames_dir.mkdir()

    for index, color in enumerate(colors, start=1):
        _create_png_frame(frames_dir / f"frame{index:02d}.png", color)

    video_path = tmp_path / filename
    _run_command([
        "ffmpeg", "-y",
        "-framerate", "1",
        "-i", str(frames_dir / "frame%02d.png"),
        "-c:v", "png",
        "-pix_fmt", "rgb24",
        str(video_path)
    ])
    return video_path, frames_dir


def _create_testsrc_video(output_path, duration_seconds, include_audio=False):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size=96x96:rate=30:duration={duration_seconds}",
    ]

    if include_audio:
        cmd += [
            "-f", "lavfi",
            "-i", f"sine=frequency=1000:sample_rate=44100:duration={duration_seconds}",
            "-shortest",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            str(output_path),
        ]
    else:
        cmd += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]

    _run_command(cmd)
    return output_path


def _create_colored_video(
    output_path,
    *,
    color,
    width,
    height,
    duration_seconds=5,
    frame_rate=24,
    profile="high",
):
    _run_command([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", (
            f"color=c={color}:s={width}x{height}:"
            f"r={frame_rate}:d={duration_seconds}"
        ),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-profile:v", profile,
        "-pix_fmt", "yuv420p",
        str(output_path),
    ])
    return output_path


def _create_audio_fixture(output_path, duration_seconds=10):
    _run_command([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:sample_rate=48000:duration={duration_seconds}",
        "-c:a", "pcm_s16le",
        str(output_path),
    ])
    return output_path


def _add_display_rotation(input_path, output_path, rotation_degrees):
    _run_command([
        "ffmpeg", "-y",
        "-display_rotation", str(rotation_degrees),
        "-i", str(input_path),
        "-c", "copy",
        str(output_path),
    ])
    return output_path


def _probe_media(file_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _sample_rgb(file_path, timestamp_seconds):
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-ss", str(timestamp_seconds),
            "-i", str(file_path),
            "-frames:v", "1",
            "-vf", "scale=1:1",
            "-pix_fmt", "rgb24",
            "-f", "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert len(result.stdout) >= 3
    return tuple(result.stdout[:3])


def _sample_pixel_rgb(file_path, timestamp_seconds, x, y):
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-ss", str(timestamp_seconds),
            "-i", str(file_path),
            "-frames:v", "1",
            "-vf", f"crop=1:1:{x}:{y},format=rgb24",
            "-f", "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert len(result.stdout) >= 3
    return tuple(result.stdout[:3])


def _decoded_md5(image_path):
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(image_path), "-f", "md5", "-"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _mock_download_file(monkeypatch, source_path):
    async def fake_download_file(_url, dest_path):
        shutil.copyfile(source_path, dest_path)
        return dest_path

    monkeypatch.setattr("main.download_file", fake_download_file)


def _assert_trimmed_output(data, expected_duration_seconds):
    assert data["success"] is True
    assert data["output_path"] is not None
    assert os.path.exists(data["output_path"])
    assert data["trimmed_duration_seconds"] == pytest.approx(expected_duration_seconds, abs=0.15)
    assert get_media_duration(data["output_path"]) == pytest.approx(expected_duration_seconds, abs=0.15)
    assert has_audio_stream(data["output_path"]) is True

    if data["output_path"] and os.path.exists(data["output_path"]):
        os.remove(data["output_path"])


class TestHealthEndpoint:
    def test_health_check(self):
        """Test health check endpoint returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestMergeEndpoint:
    def test_merge_normalizes_mismatched_video_dimensions(self, tmp_path, monkeypatch):
        """Mismatched provider clips are normalized before concat."""
        first_video = _create_colored_video(
            tmp_path / "fixture-a.mp4",
            color="red",
            width=1924,
            height=1076,
            profile="main",
        )
        second_video = _create_colored_video(
            tmp_path / "fixture-b.mp4",
            color="blue",
            width=1920,
            height=1072,
            profile="high",
        )
        audio = _create_audio_fixture(tmp_path / "soundtrack.wav")

        async def fake_download_file(url, dest_path):
            if "fixture-a" in url:
                source = first_video
            elif "fixture-b" in url:
                source = second_video
            else:
                source = audio
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        output_filename = f"mismatched_{uuid.uuid4().hex}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        temp_files_before = set(os.listdir(TEMP_DIR))
        payload = {
            "video_urls": [
                "https://example.com/fixture-a.mp4",
                "https://example.com/fixture-b.mp4",
            ],
            "audio_url": "https://example.com/soundtrack.wav",
            "output_filename": output_filename,
        }

        try:
            response = client.post("/merge", json=payload, headers=HEADERS)

            assert response.status_code == 200, response.text
            data = response.json()
            assert data["success"] is True
            assert data["output_path"] == output_path
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
            assert set(os.listdir(TEMP_DIR)) == temp_files_before

            probe = _probe_media(output_path)
            video_stream = next(
                stream for stream in probe["streams"] if stream["codec_type"] == "video"
            )
            audio_stream = next(
                stream for stream in probe["streams"] if stream["codec_type"] == "audio"
            )

            assert float(probe["format"]["duration"]) == pytest.approx(10.0, abs=0.25)
            assert (video_stream["width"], video_stream["height"]) == (1920, 1080)
            assert video_stream["codec_name"] == "h264"
            assert video_stream["sample_aspect_ratio"] == "1:1"
            assert video_stream["pix_fmt"] == "yuv420p"
            assert video_stream["avg_frame_rate"] == "24/1"
            assert audio_stream["codec_name"] == "aac"

            first_clip_rgb = _sample_rgb(output_path, 2.5)
            second_clip_rgb = _sample_rgb(output_path, 7.5)
            assert first_clip_rgb[0] > first_clip_rgb[2] + 100
            assert second_clip_rgb[2] > second_clip_rgb[0] + 100
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_merge_returns_422_and_cleans_up_for_invalid_media(self, tmp_path, monkeypatch):
        """Deterministic media validation failures are concise and leave no artifacts."""
        invalid_video = tmp_path / "invalid.mp4"
        invalid_video.write_bytes(b"not an mp4")

        async def fake_download_file(_url, dest_path):
            shutil.copyfile(invalid_video, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        output_filename = f"invalid_{uuid.uuid4().hex}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        temp_files_before = set(os.listdir(TEMP_DIR))

        response = client.post(
            "/merge",
            json={
                "video_urls": ["https://example.com/invalid.mp4"],
                "audio_url": "https://example.com/soundtrack.wav",
                "output_filename": output_filename,
            },
            headers=HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "media_processing_failed"
        assert response.json()["detail"]["message"] == "Media validation failed"
        assert response.json()["detail"]["errors"]
        assert "configuration:" not in response.text
        assert set(os.listdir(TEMP_DIR)) == temp_files_before
        assert not os.path.exists(output_path)

    def test_merge_uses_portrait_canvas_for_rotated_clip(self, tmp_path, monkeypatch):
        """Display rotation is included when deriving the request canvas."""
        coded_landscape_video = _create_colored_video(
            tmp_path / "coded-landscape.mp4",
            color="green",
            width=1920,
            height=1080,
            duration_seconds=1,
        )
        portrait_video = _add_display_rotation(
            coded_landscape_video,
            tmp_path / "portrait.mp4",
            90,
        )
        audio = _create_audio_fixture(tmp_path / "portrait-audio.wav", duration_seconds=1)

        async def fake_download_file(url, dest_path):
            source = audio if "audio" in url else portrait_video
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        output_filename = f"portrait_{uuid.uuid4().hex}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        try:
            response = client.post(
                "/merge",
                json={
                    "video_urls": ["https://example.com/portrait.mp4"],
                    "audio_url": "https://example.com/portrait-audio.wav",
                    "output_filename": output_filename,
                },
                headers=HEADERS,
            )

            assert response.status_code == 200, response.text
            probe = _probe_media(output_path)
            video_stream = next(
                stream for stream in probe["streams"] if stream["codec_type"] == "video"
            )
            assert (video_stream["width"], video_stream["height"]) == (1080, 1920)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_merge_single_video_with_audio(self):
        """Test merging a single video with audio."""
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == (
            f"Video and audio merged successfully. "
            f"File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds."
        )
        assert data["output_path"] is not None
        
        if data["output_path"] and os.path.exists(data["output_path"]):
            os.remove(data["output_path"])

    def test_merge_with_custom_filename(self):
        """Test merging with custom output filename."""
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL],
            "audio_url": SAMPLE_AUDIO_URL,
            "output_filename": "custom_output.mp4"
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "custom_output.mp4" in data["output_path"]
        
        if data["output_path"] and os.path.exists(data["output_path"]):
            os.remove(data["output_path"])

    def test_merge_multiple_videos_with_audio(self):
        """Test merging multiple videos with audio."""
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL, SAMPLE_VIDEO_URL],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        if data["output_path"] and os.path.exists(data["output_path"]):
            os.remove(data["output_path"])

    def test_merge_multiple_videos_without_audio_preserves_source_audio(self, tmp_path, monkeypatch):
        """Test concatenating videos without replacement audio keeps clip audio."""
        first_video = _create_testsrc_video(tmp_path / "first.mp4", 0.6, include_audio=True)
        second_video = _create_testsrc_video(tmp_path / "second.mp4", 0.6, include_audio=True)

        async def fake_download_file(url, dest_path):
            source = first_video if "first" in url else second_video
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        payload = {
            "video_urls": [
                "https://example.com/first.mp4",
                "https://example.com/second.mp4",
            ]
        }
        response = client.post("/merge", json=payload, headers=HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == (
            f"Videos merged successfully with source audio preserved. "
            f"File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds."
        )
        assert data["output_path"] is not None
        assert os.path.exists(data["output_path"])
        assert has_audio_stream(data["output_path"]) is True
        assert get_media_duration(data["output_path"]) == pytest.approx(1.2, abs=0.35)

        if data["output_path"] and os.path.exists(data["output_path"]):
            os.remove(data["output_path"])

    def test_merge_invalid_video_url(self):
        """Test merge with invalid video URL."""
        payload = {
            "video_urls": ["https://invalid-url-that-does-not-exist.com/video.mp4"],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code in [400, 422, 500]

    def test_merge_invalid_audio_url(self):
        """Test merge with invalid audio URL."""
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL],
            "audio_url": "https://invalid-url-that-does-not-exist.com/audio.mp3"
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code in [400, 422, 500]

    def test_merge_empty_video_urls(self):
        """Test merge with empty video URLs list."""
        payload = {
            "video_urls": [],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code in [400, 422, 500]


class TestDownloadEndpoint:
    def test_download_path_resolution_rejects_traversal(self):
        """Traversal attempts must be rejected before reading outside OUTPUT_DIR."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_path_within_directory(OUTPUT_DIR, "../.env")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid filename"

    def test_download_nonexistent_file(self):
        """Test downloading a file that doesn't exist."""
        response = client.get("/download/nonexistent_file.mp4")
        assert response.status_code == 404
        assert response.json()["detail"] == "File not found"

    def test_download_after_merge(self):
        """Test downloading a file after successful merge."""
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL],
            "audio_url": SAMPLE_AUDIO_URL,
            "output_filename": "download_test.mp4"
        }
        merge_response = client.post("/merge", json=payload, headers=HEADERS)
        
        if merge_response.status_code == 200:
            download_response = client.get("/download/download_test.mp4")
            assert download_response.status_code == 200
            assert download_response.headers["content-type"] == "video/mp4"
            
            output_path = merge_response.json().get("output_path")
            if output_path and os.path.exists(output_path):
                os.remove(output_path)


class TestExtractFifthFrameEndpoint:
    def test_extract_fifth_frame_accepts_uploaded_file(self, tmp_path):
        """Test extracting the fifth frame from a direct file upload."""
        video_path, frames_dir = _create_lossless_test_video(
            tmp_path,
            ["red", "green", "blue", "yellow", "magenta"],
            "uploaded_five_frame_source.mov"
        )

        with open(video_path, "rb") as video_handle:
            response = client.post(
                "/extract-fifth-frame",
                data={"output_filename": "uploaded-preview"},
                files={
                    "video_file": (
                        "uploaded_five_frame_source.mov",
                        video_handle,
                        "video/quicktime"
                    )
                },
                headers=HEADERS
            )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert "filename=\"uploaded-preview.png\"" in response.headers["content-disposition"]

        extracted_frame_path = tmp_path / "uploaded_extracted_frame.png"
        extracted_frame_path.write_bytes(response.content)

        expected_frame_path = frames_dir / "frame05.png"
        assert _decoded_md5(extracted_frame_path) == _decoded_md5(expected_frame_path)

    def test_extract_fifth_frame_returns_png(self, tmp_path, monkeypatch):
        """Test extracting the fifth frame returns the expected PNG image."""
        video_path, frames_dir = _create_lossless_test_video(
            tmp_path,
            ["red", "green", "blue", "yellow", "magenta"],
            "five_frame_source.mov"
        )

        async def fake_download_file(_url, dest_path):
            shutil.copyfile(video_path, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)

        response = client.post(
            "/extract-fifth-frame",
            json={
                "video_url": "https://example.com/five-frame-source.mov",
                "output_filename": "preview"
            },
            headers=HEADERS
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert "filename=\"preview.png\"" in response.headers["content-disposition"]

        extracted_frame_path = tmp_path / "extracted_frame.png"
        extracted_frame_path.write_bytes(response.content)

        expected_frame_path = frames_dir / "frame05.png"
        assert _decoded_md5(extracted_frame_path) == _decoded_md5(expected_frame_path)

    def test_extract_fifth_frame_requires_at_least_five_frames(self, tmp_path, monkeypatch):
        """Test extraction fails when the source video is shorter than five frames."""
        video_path, _ = _create_lossless_test_video(
            tmp_path,
            ["red", "green", "blue", "yellow"],
            "four_frame_source.mov"
        )

        async def fake_download_file(_url, dest_path):
            shutil.copyfile(video_path, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)

        response = client.post(
            "/extract-fifth-frame",
            json={"video_url": "https://example.com/four-frame-source.mov"},
            headers=HEADERS
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "Video must contain at least 5 frames"


class TestOverlayEndpoint:
    def test_overlay_matches_base_canvas_by_default_for_same_aspect_ratio(
        self,
        tmp_path,
        monkeypatch,
    ):
        base_video = _create_colored_video(
            tmp_path / "base.mp4",
            color="red",
            width=54,
            height=96,
            duration_seconds=1,
        )
        overlay_video = tmp_path / "full-frame-layer.mov"
        _run_command([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", (
                "color=c=black@0:s=108x192:r=24:d=1,format=rgba,"
                "drawbox=x=54:y=96:w=54:h=96:color=blue@1:t=fill:replace=1"
            ),
            "-c:v", "qtrle",
            "-pix_fmt", "argb",
            str(overlay_video),
        ])

        async def fake_download_file(url, dest_path):
            source = overlay_video if "layer" in url else base_video
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        response = client.post(
            "/overlay",
            json={
                "base_video_url": "https://example.com/base.mp4",
                "overlay_video_url": "https://example.com/layer.mov",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        output_path = response.json()["output_path"]
        try:
            transparent_quadrant = _sample_pixel_rgb(output_path, 0.25, 12, 24)
            colored_quadrant = _sample_pixel_rgb(output_path, 0.25, 40, 72)

            assert transparent_quadrant[0] > 180
            assert transparent_quadrant[2] < 80
            assert colored_quadrant[2] > 180
            assert colored_quadrant[0] < 80
        finally:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

    def test_overlay_composites_layer_and_preserves_base_timeline_and_audio(
        self,
        tmp_path,
        monkeypatch,
    ):
        base_video = tmp_path / "base.mp4"
        _run_command([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "color=c=red:s=96x64:r=24:d=2",
            "-f", "lavfi",
            "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-shortest",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(base_video),
        ])
        overlay_video = _create_colored_video(
            tmp_path / "layer.mp4",
            color="blue",
            width=32,
            height=24,
            duration_seconds=0.75,
        )

        async def fake_download_file(url, dest_path):
            source = overlay_video if "layer" in url else base_video
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        output_filename = f"overlay_{uuid.uuid4().hex}.mp4"
        response = client.post(
            "/overlay",
            json={
                "base_video_url": "https://example.com/base.mp4",
                "overlay_video_url": "https://example.com/layer.mp4",
                "x": 16,
                "y": 12,
                "output_filename": output_filename,
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        output_path = data["output_path"]
        try:
            assert data["success"] is True
            assert data["base_duration_seconds"] == pytest.approx(2, abs=0.1)
            assert get_media_duration(output_path) == pytest.approx(2, abs=0.15)
            assert has_audio_stream(output_path) is True

            corner_during_overlay = _sample_pixel_rgb(output_path, 0.25, 4, 4)
            center_during_overlay = _sample_pixel_rgb(output_path, 0.25, 20, 16)
            center_after_overlay = _sample_pixel_rgb(output_path, 1.25, 20, 16)

            assert corner_during_overlay[0] > 180
            assert corner_during_overlay[2] < 80
            assert center_during_overlay[2] > 180
            assert center_during_overlay[0] < 80
            assert center_after_overlay[0] > 180
            assert center_after_overlay[2] < 80
        finally:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

    def test_overlay_can_resize_layer(self, tmp_path, monkeypatch):
        base_video = _create_colored_video(
            tmp_path / "base.mp4",
            color="red",
            width=96,
            height=64,
            duration_seconds=1,
        )
        overlay_video = _create_colored_video(
            tmp_path / "layer.mp4",
            color="blue",
            width=16,
            height=16,
            duration_seconds=1,
        )

        async def fake_download_file(url, dest_path):
            source = overlay_video if "layer" in url else base_video
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        response = client.post(
            "/overlay",
            json={
                "base_video_url": "https://example.com/base.mp4",
                "overlay_video_url": "https://example.com/layer.mp4",
                "overlay_width": 48,
                "overlay_height": 32,
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        output_path = response.json()["output_path"]
        try:
            inside_layer = _sample_pixel_rgb(output_path, 0.25, 40, 24)
            outside_layer = _sample_pixel_rgb(output_path, 0.25, 70, 40)
            assert inside_layer[2] > 180
            assert outside_layer[0] > 180
        finally:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

    def test_overlay_preserves_layer_transparency(self, tmp_path, monkeypatch):
        base_video = _create_colored_video(
            tmp_path / "base.mp4",
            color="red",
            width=64,
            height=64,
            duration_seconds=1,
        )
        overlay_video = tmp_path / "transparent-layer.mov"
        _run_command([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "color=c=blue@0.5:s=64x64:r=24:d=1,format=rgba",
            "-c:v", "qtrle",
            "-pix_fmt", "argb",
            str(overlay_video),
        ])

        async def fake_download_file(url, dest_path):
            source = overlay_video if "layer" in url else base_video
            shutil.copyfile(source, dest_path)
            return dest_path

        monkeypatch.setattr("main.download_file", fake_download_file)
        monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)

        response = client.post(
            "/overlay",
            json={
                "base_video_url": "https://example.com/base.mp4",
                "overlay_video_url": "https://example.com/layer.mov",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        output_path = response.json()["output_path"]
        try:
            blended_pixel = _sample_pixel_rgb(output_path, 0.25, 20, 20)
            assert blended_pixel[0] == pytest.approx(125, abs=30)
            assert blended_pixel[2] == pytest.approx(125, abs=30)
        finally:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

    def test_overlay_rejects_non_positive_dimensions(self):
        response = client.post(
            "/overlay",
            json={
                "base_video_url": "https://example.com/base.mp4",
                "overlay_video_url": "https://example.com/layer.mp4",
                "overlay_width": 0,
            },
            headers=HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "overlay_width must be greater than 0"


class TestTrimEndpoint:
    def test_trim_from_only_keeps_trailing_segment(self, tmp_path, monkeypatch):
        """trim_from should remove the requested prefix and keep the remainder."""
        video_path = _create_testsrc_video(
            tmp_path / "trim_from_source.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_download_file(monkeypatch, video_path)

        response = client.post(
            "/trim",
            json={
                "video_url": "https://example.com/trim-from-source.mp4",
                "trim_from": 1.0,
                "output_filename": "trimmed-from.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200
        _assert_trimmed_output(response.json(), expected_duration_seconds=2.0)

    def test_trim_to_is_frame_accurate_for_short_clips(self, tmp_path, monkeypatch):
        """trim_to should keep the requested leading duration rather than snapping to a later keyframe."""
        video_path = _create_testsrc_video(
            tmp_path / "trim_source.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_download_file(monkeypatch, video_path)

        response = client.post(
            "/trim",
            json={
                "video_url": "https://example.com/trim-source.mp4",
                "trim_to": 1.2,
                "output_filename": "trimmed-short.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200
        _assert_trimmed_output(response.json(), expected_duration_seconds=1.2)

    def test_trim_range_extracts_requested_segment(self, tmp_path, monkeypatch):
        """trim_from and trim_to together should extract the requested range."""
        video_path = _create_testsrc_video(
            tmp_path / "trim_range_source.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_download_file(monkeypatch, video_path)

        response = client.post(
            "/trim",
            json={
                "video_url": "https://example.com/trim-range-source.mp4",
                "trim_from": 0.5,
                "trim_to": 1.75,
                "output_filename": "trimmed-range.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200
        _assert_trimmed_output(response.json(), expected_duration_seconds=1.25)

    def test_trim_to_exceeding_duration_clamps_to_video_end(self, tmp_path, monkeypatch):
        """trim_to beyond the source duration should clamp to the file end."""
        video_path = _create_testsrc_video(
            tmp_path / "trim_clamp_source.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_download_file(monkeypatch, video_path)

        response = client.post(
            "/trim",
            json={
                "video_url": "https://example.com/trim-clamp-source.mp4",
                "trim_to": 10.0,
                "output_filename": "trimmed-clamped.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200
        _assert_trimmed_output(response.json(), expected_duration_seconds=3.0)

    def test_trim_requires_at_least_one_boundary(self):
        """trim must reject requests that omit both trim_from and trim_to."""
        response = client.post(
            "/trim",
            json={"video_url": "https://example.com/trim-source.mp4"},
            headers=HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "At least one of trim_from or trim_to must be provided"

    def test_trim_rejects_non_positive_trim_to(self, tmp_path, monkeypatch):
        """trim_to must be strictly greater than zero."""
        video_path = _create_testsrc_video(
            tmp_path / "trim_invalid_to_source.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_download_file(monkeypatch, video_path)

        response = client.post(
            "/trim",
            json={
                "video_url": "https://example.com/trim-invalid-to-source.mp4",
                "trim_to": 0,
            },
            headers=HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "trim_to must be > 0"

    def test_trim_rejects_trim_from_not_less_than_trim_to(self, tmp_path, monkeypatch):
        """trim_from must be strictly less than trim_to when both are provided."""
        video_path = _create_testsrc_video(
            tmp_path / "trim_invalid_range_source.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_download_file(monkeypatch, video_path)

        response = client.post(
            "/trim",
            json={
                "video_url": "https://example.com/trim-invalid-range-source.mp4",
                "trim_from": 1.5,
                "trim_to": 1.5,
            },
            headers=HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "trim_from must be less than trim_to"


def _stream_types(file_path):
    return [stream["codec_type"] for stream in _probe_media(file_path)["streams"]]


def _video_stream(file_path):
    return next(s for s in _probe_media(file_path)["streams"] if s["codec_type"] == "video")


def _count_video_frames(file_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-count_frames",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


def _mock_downloads_by_url(monkeypatch, sources):
    async def fake_download_file(url, dest_path):
        source = next(path for key, path in sources.items() if key in url)
        shutil.copyfile(source, dest_path)
        return dest_path

    monkeypatch.setattr("main.download_file", fake_download_file)
    monkeypatch.setattr("main.schedule_file_deletion", lambda *_args, **_kwargs: None)


def _remove_output(data):
    output_path = data.get("output_path")
    if output_path and os.path.exists(output_path):
        os.remove(output_path)


class TestStripAudioEndpoint:
    def test_strip_removes_audio_and_keeps_video_frames(self, tmp_path, monkeypatch):
        """strip-audio should drop the audio stream and stream-copy every video frame."""
        video_path = _create_testsrc_video(
            tmp_path / "strip_source.mp4",
            duration_seconds=2.0,
            include_audio=True,
        )
        _mock_downloads_by_url(monkeypatch, {"strip-source": video_path})

        response = client.post(
            "/strip-audio",
            json={
                "video_url": "https://example.com/strip-source.mp4",
                "output_filename": "stripped-test.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        try:
            assert data["success"] is True
            assert data["had_audio"] is True
            assert data["delete_after_seconds"] == DELETE_AFTER_SECONDS
            assert data["duration_seconds"] == pytest.approx(2.0, abs=0.15)
            assert _stream_types(data["output_path"]) == ["video"]
            assert _count_video_frames(data["output_path"]) == _count_video_frames(video_path)
            assert _video_stream(data["output_path"])["codec_name"] == "h264"

            download_response = client.get("/download/stripped-test.mp4")
            assert download_response.status_code == 200
            assert download_response.headers["content-type"] == "video/mp4"
        finally:
            _remove_output(data)

    def test_strip_silent_input_reports_had_audio_false(self, tmp_path, monkeypatch):
        """A video with no audio stream still produces an output with had_audio=false."""
        video_path = _create_testsrc_video(
            tmp_path / "silent_source.mp4",
            duration_seconds=1.0,
        )
        _mock_downloads_by_url(monkeypatch, {"silent": video_path})

        response = client.post(
            "/strip-audio",
            json={"video_url": "https://example.com/silent.mp4"},
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        try:
            assert data["had_audio"] is False
            assert os.path.exists(data["output_path"])
            assert _stream_types(data["output_path"]) == ["video"]
        finally:
            _remove_output(data)


class TestReplaceAudioEndpoint:
    def test_replace_with_audio_file_source(self, tmp_path, monkeypatch):
        """An audio file source replaces the video's audio; output ends at the shorter input."""
        video_path = _create_testsrc_video(
            tmp_path / "replace_video.mp4",
            duration_seconds=2.0,
            include_audio=True,
        )
        audio_path = _create_audio_fixture(tmp_path / "replace_audio.wav", duration_seconds=5)
        _mock_downloads_by_url(monkeypatch, {"clip": video_path, "track": audio_path})

        response = client.post(
            "/replace-audio",
            json={
                "video_url": "https://example.com/clip.mp4",
                "audio_source_url": "https://example.com/track.wav",
                "output_filename": "replaced-audio-test.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        try:
            assert data["success"] is True
            assert data["video_duration_seconds"] == pytest.approx(2.0, abs=0.15)
            assert data["audio_duration_seconds"] == pytest.approx(5.0, abs=0.15)
            assert data["output_duration_seconds"] == pytest.approx(2.0, abs=0.15)

            streams = _probe_media(data["output_path"])["streams"]
            audio_streams = [s for s in streams if s["codec_type"] == "audio"]
            assert len(audio_streams) == 1
            assert audio_streams[0]["codec_name"] == "aac"
            # The fixture's audio is 48 kHz; the original video audio was 44.1 kHz.
            assert audio_streams[0]["sample_rate"] == "48000"
            assert _video_stream(data["output_path"])["codec_name"] == "h264"
            assert _count_video_frames(data["output_path"]) == _count_video_frames(video_path)

            download_response = client.get("/download/replaced-audio-test.mp4")
            assert download_response.status_code == 200
            assert download_response.headers["content-type"] == "video/mp4"
        finally:
            _remove_output(data)

    def test_replace_with_video_file_source_takes_its_audio(self, tmp_path, monkeypatch):
        """A video file source contributes only its audio stream."""
        video_path = _create_testsrc_video(tmp_path / "target.mp4", duration_seconds=2.0)
        source_path = _create_testsrc_video(
            tmp_path / "donor.mp4",
            duration_seconds=3.0,
            include_audio=True,
        )
        _mock_downloads_by_url(monkeypatch, {"target": video_path, "donor": source_path})

        response = client.post(
            "/replace-audio",
            json={
                "video_url": "https://example.com/target.mp4",
                "audio_source_url": "https://example.com/donor.mp4?sig=abc",
            },
            headers=HEADERS,
        )

        assert response.status_code == 200, response.text
        data = response.json()
        try:
            assert data["audio_duration_seconds"] == pytest.approx(3.0, abs=0.15)
            assert data["output_duration_seconds"] == pytest.approx(2.0, abs=0.15)
            assert sorted(_stream_types(data["output_path"])) == ["audio", "video"]
            assert has_audio_stream(data["output_path"]) is True
            assert _count_video_frames(data["output_path"]) == _count_video_frames(video_path)
        finally:
            _remove_output(data)

    def test_replace_with_silent_source_returns_422(self, tmp_path, monkeypatch):
        """A source without an audio stream is rejected as a validation error."""
        video_path = _create_testsrc_video(tmp_path / "target.mp4", duration_seconds=1.0)
        silent_source = _create_testsrc_video(tmp_path / "mute.mp4", duration_seconds=1.0)
        _mock_downloads_by_url(monkeypatch, {"target": video_path, "mute": silent_source})

        response = client.post(
            "/replace-audio",
            json={
                "video_url": "https://example.com/target.mp4",
                "audio_source_url": "https://example.com/mute.mp4",
                "output_filename": "replace-silent-should-not-exist.mp4",
            },
            headers=HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "audio_source_url has no audio track"
        assert not os.path.exists(os.path.join(OUTPUT_DIR, "replace-silent-should-not-exist.mp4"))


class TestValidation:
    def test_invalid_url_format(self):
        """Test with invalid URL format."""
        payload = {
            "video_urls": ["not-a-valid-url"],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_missing_required_fields(self):
        """Test with missing required fields."""
        payload = {}
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code == 422


def run_quick_test():
    """Run a quick functional test."""
    print("Running quick functional test...")
    print(f"Using video URL: {SAMPLE_VIDEO_URL}")
    print(f"Using audio URL: {SAMPLE_AUDIO_URL}")
    
    response = client.get("/health")
    print(f"Health check: {response.json()}")
    
    print("\nTesting merge endpoint...")
    payload = {
        "video_urls": [SAMPLE_VIDEO_URL],
        "audio_url": SAMPLE_AUDIO_URL,
        "output_filename": "quick_test_output.mp4"
    }
    
    response = client.post("/merge", json=payload, headers=HEADERS)
    print(f"Status code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        output_path = response.json().get("output_path")
        if output_path and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"Output file size: {file_size} bytes")
            print(f"Output saved at: {output_path}")
            print("Test passed! Check the output file for audio.")
    else:
        print("Test failed!")


if __name__ == "__main__":
    run_quick_test()
