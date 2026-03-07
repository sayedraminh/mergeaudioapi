import pytest
import httpx
import asyncio
import os
import tempfile
import shutil
import subprocess
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from main import app, get_media_duration, OUTPUT_DIR

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


def _decoded_md5(image_path):
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(image_path), "-f", "md5", "-"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestHealthEndpoint:
    def test_health_check(self):
        """Test health check endpoint returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestMergeEndpoint:
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
        assert data["message"] == "Video and audio merged successfully"
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

    def test_merge_invalid_video_url(self):
        """Test merge with invalid video URL."""
        payload = {
            "video_urls": ["https://invalid-url-that-does-not-exist.com/video.mp4"],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code in [400, 500]

    def test_merge_invalid_audio_url(self):
        """Test merge with invalid audio URL."""
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL],
            "audio_url": "https://invalid-url-that-does-not-exist.com/audio.mp3"
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code in [400, 500]

    def test_merge_empty_video_urls(self):
        """Test merge with empty video URLs list."""
        payload = {
            "video_urls": [],
            "audio_url": SAMPLE_AUDIO_URL
        }
        response = client.post("/merge", json=payload, headers=HEADERS)
        assert response.status_code in [400, 422, 500]


class TestDownloadEndpoint:
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
        payload = {
            "video_urls": [SAMPLE_VIDEO_URL]
        }
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
