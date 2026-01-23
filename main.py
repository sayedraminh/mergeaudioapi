import os
import sys
import uuid
import subprocess
import threading
import asyncio
import time
import logging
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.security import APIKeyHeader

load_dotenv()

handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
logger = logging.getLogger("mergerapi")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import List, Optional

DELETE_AFTER_SECONDS = 30
MAX_CONCURRENT_JOBS = 20

API_KEY = os.getenv("API_KEY")
if not API_KEY:
    logger.warning("No API_KEY set in .env file - API will be unprotected!")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

app = FastAPI(title="Video Audio Merger API")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


async def verify_api_key(x_api_key: str = Depends(api_key_header)):
    """Verify the API key from request header."""
    if not API_KEY:
        return True
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


class MergeRequest(BaseModel):
    video_urls: List[HttpUrl]
    audio_url: HttpUrl
    output_filename: Optional[str] = None


class MergeResponse(BaseModel):
    success: bool
    message: str
    output_path: Optional[str] = None
    delete_after_seconds: int = DELETE_AFTER_SECONDS


def schedule_file_deletion(file_path: str, delay_seconds: int = DELETE_AFTER_SECONDS):
    """Schedule a file to be deleted after a delay using a background thread."""
    def delete_after_delay():
        logger.info(f"Scheduled deletion of {file_path} in {delay_seconds} seconds")
        time.sleep(delay_seconds)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Auto-deleted file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete file {file_path}: {e}")
        else:
            logger.warning(f"File already deleted or not found: {file_path}")
    
    thread = threading.Thread(target=delete_after_delay, daemon=False)
    thread.start()
    logger.info(f"Started deletion thread for {file_path}")


async def download_file(url: str, dest_path: str) -> str:
    """Download a file from URL to destination path."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(response.content)
    return dest_path


def get_media_duration(file_path: str) -> float:
    """Get duration of media file in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffprobe error: {result.stderr}")
    return float(result.stdout.strip())


def concatenate_videos(video_paths: List[str], output_path: str) -> str:
    """Concatenate multiple videos into one using ffmpeg."""
    if len(video_paths) == 1:
        return video_paths[0]
    
    list_file = os.path.join(TEMP_DIR, f"concat_list_{uuid.uuid4().hex}.txt")
    with open(list_file, "w") as f:
        for vp in video_paths:
            f.write(f"file '{vp}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg concat error: {result.stderr}")
    
    os.remove(list_file)
    return output_path


def merge_audio_video(video_path: str, audio_path: str, output_path: str) -> str:
    """
    Merge audio with video.
    - If audio is longer than video: trim audio to video duration
    - If audio is shorter than video: audio plays for its duration, rest is silent
    """
    video_duration = get_media_duration(video_path)
    audio_duration = get_media_duration(audio_path)
    
    logger.info(f"Video duration: {video_duration}s, Audio duration: {audio_duration}s")
    
    if audio_duration >= video_duration:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(video_duration),
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            f"[1:a]apad=whole_len={int(video_duration * 48000)}[aout]",
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(video_duration),
            output_path
        ]
    
    logger.info(f"Running ffmpeg command")
    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.debug(f"ffmpeg stdout: {result.stdout}")
    logger.debug(f"ffmpeg stderr: {result.stderr}")
    if result.returncode != 0:
        raise Exception(f"ffmpeg merge error: {result.stderr}")
    
    return output_path


@app.post("/merge", response_model=MergeResponse)
async def merge_videos_with_audio(request: MergeRequest, _: bool = Depends(verify_api_key)):
    """
    Merge multiple videos and add audio track.
    
    - Downloads all video URLs and concatenates them
    - Downloads audio and merges it with the concatenated video
    - Audio is trimmed or padded based on video duration
    - Requires X-API-Key header for authentication
    """
    async with processing_semaphore:
        try:
            logger.info(f"Received merge request with {len(request.video_urls)} video(s)")
            session_id = uuid.uuid4().hex
            video_paths = []
            
            for i, video_url in enumerate(request.video_urls):
                video_ext = os.path.splitext(str(video_url).split("?")[0])[1] or ".mp4"
                video_path = os.path.join(TEMP_DIR, f"video_{session_id}_{i}{video_ext}")
                await download_file(str(video_url), video_path)
                video_paths.append(video_path)
            
            audio_ext = os.path.splitext(str(request.audio_url).split("?")[0])[1] or ".mp3"
            audio_path = os.path.join(TEMP_DIR, f"audio_{session_id}{audio_ext}")
            await download_file(str(request.audio_url), audio_path)
            
            concatenated_path = os.path.join(TEMP_DIR, f"concat_{session_id}.mp4")
            if len(video_paths) > 1:
                concatenate_videos(video_paths, concatenated_path)
            else:
                concatenated_path = video_paths[0]
            
            output_filename = request.output_filename or f"output_{session_id}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            merge_audio_video(concatenated_path, audio_path, output_path)
            
            for vp in video_paths:
                if os.path.exists(vp):
                    os.remove(vp)
                    logger.info(f"Deleted temp video: {vp}")
            if concatenated_path != video_paths[0] and os.path.exists(concatenated_path):
                os.remove(concatenated_path)
                logger.info(f"Deleted concatenated temp: {concatenated_path}")
            if os.path.exists(audio_path):
                os.remove(audio_path)
                logger.info(f"Deleted temp audio: {audio_path}")
            
            schedule_file_deletion(output_path)
            
            return MergeResponse(
                success=True,
                message=f"Video and audio merged successfully. File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds.",
                output_path=output_path,
                delete_after_seconds=DELETE_AFTER_SECONDS
            )
        
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{filename}")
async def download_output(filename: str):
    """Download the merged output file."""
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="video/mp4", filename=filename)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
