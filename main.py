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
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from starlette.background import BackgroundTask

load_dotenv()

handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
logger = logging.getLogger("mergerapi")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, ValidationError
from typing import List, Optional, Tuple

DELETE_AFTER_SECONDS = 120
MAX_CONCURRENT_JOBS = 20
MIN_SEGMENT_DURATION_SECONDS = 0.05

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
    processing_time_seconds: Optional[float] = None


class BeatSyncMergeRequest(BaseModel):
    video_urls: List[HttpUrl]
    audio_url: HttpUrl
    beat_timestamps: List[float]
    video_cut_starts: Optional[List[float]] = None
    output_filename: Optional[str] = None


class BeatSyncMergeResponse(MergeResponse):
    segments_created: int
    total_duration_seconds: float


class TrimRequest(BaseModel):
    video_url: HttpUrl
    trim_from: Optional[float] = None
    trim_to: Optional[float] = None
    output_filename: Optional[str] = None


class TrimResponse(BaseModel):
    success: bool
    message: str
    output_path: Optional[str] = None
    delete_after_seconds: int = DELETE_AFTER_SECONDS
    processing_time_seconds: Optional[float] = None
    original_duration_seconds: Optional[float] = None
    trimmed_duration_seconds: Optional[float] = None


class ReverseRequest(BaseModel):
    video_url: HttpUrl
    output_filename: Optional[str] = None


class SpeedRequest(BaseModel):
    video_url: HttpUrl
    speed: float
    output_filename: Optional[str] = None


class FifthFrameRequest(BaseModel):
    video_url: HttpUrl
    output_filename: Optional[str] = None


class VideoTransformResponse(BaseModel):
    success: bool
    message: str
    output_path: Optional[str] = None
    delete_after_seconds: int = DELETE_AFTER_SECONDS
    processing_time_seconds: Optional[float] = None
    original_duration_seconds: Optional[float] = None
    transformed_duration_seconds: Optional[float] = None


class SpeedResponse(VideoTransformResponse):
    speed: float


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


def cleanup_files(file_paths: List[str]):
    """Delete temporary files immediately."""
    for file_path in file_paths:
        if not file_path:
            continue
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted temp file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete temp file {file_path}: {e}")


async def save_uploaded_file(upload_file, dest_path: str) -> str:
    """Persist an uploaded file to a temporary location."""
    try:
        with open(dest_path, "wb") as file_handle:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                file_handle.write(chunk)
    finally:
        await upload_file.close()

    return dest_path


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


def get_video_dimensions(file_path: str) -> Tuple[int, int]:
    """Read first video stream dimensions with ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffprobe stream error: {result.stderr}")
    raw_dimensions = result.stdout.strip()
    width_text, height_text = raw_dimensions.split("x")
    width = int(width_text)
    height = int(height_text)
    if width <= 0 or height <= 0:
        raise Exception(f"Invalid video dimensions from ffprobe: {raw_dimensions}")
    return width, height


def get_video_frame_count(file_path: str) -> Optional[int]:
    """Read total video frame count when ffprobe can determine it."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-count_frames",
        "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffprobe frame count error: {result.stderr}")

    raw_count = result.stdout.strip()
    if not raw_count or raw_count == "N/A":
        return None

    try:
        return int(raw_count)
    except ValueError:
        return None


def has_audio_stream(file_path: str) -> bool:
    """Return True if file has at least one audio stream."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffprobe audio stream error: {result.stderr}")
    return bool(result.stdout.strip())


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


def concatenate_videos_reencoded(video_paths: List[str], output_path: str) -> str:
    """
    Concatenate videos using the filter_complex concat filter.
    Each input is decoded independently so source timestamps are discarded,
    preventing duration inflation from containers with non-zero start times.
    """
    if not video_paths:
        raise Exception("No video segments provided for concatenation")

    cmd = ["ffmpeg", "-y"]
    for video_path in video_paths:
        cmd += ["-i", video_path]

    n = len(video_paths)
    filter_inputs = "".join(f"[{i}:v]" for i in range(n))
    filter_complex = f"{filter_inputs}concat=n={n}:v=1:a=0[vout]"

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg re-encoded concat error: {result.stderr}")

    return output_path


def extract_video_segment(
    input_path: str,
    output_path: str,
    start_seconds: float,
    duration_seconds: float,
    clip_duration_seconds: float,
    target_width: int,
    target_height: int
) -> str:
    """Extract one segment from an input video and normalize it for concatenation."""
    if duration_seconds < MIN_SEGMENT_DURATION_SECONDS:
        raise Exception(
            f"Segment duration {duration_seconds} is too short. "
            f"Minimum is {MIN_SEGMENT_DURATION_SECONDS} seconds."
        )

    effective_start = start_seconds
    if clip_duration_seconds > 0:
        effective_start = start_seconds % clip_duration_seconds

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-ss", f"{effective_start:.6f}",
        "-i", input_path,
        "-t", f"{duration_seconds:.6f}",
        "-map", "0:v:0",
        "-vf",
        (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
            "fps=30,format=yuv420p"
        ),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-an",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg segment extraction error: {result.stderr}")
    return output_path


def _validate_beat_timestamps(beat_timestamps: List[float]) -> List[float]:
    """Validate beat list and return segment durations from song start (0)."""
    if not beat_timestamps:
        raise HTTPException(status_code=422, detail="beat_timestamps must contain at least one value")

    segment_durations: List[float] = []
    previous_beat = 0.0
    for index, beat in enumerate(beat_timestamps):
        if beat <= 0:
            raise HTTPException(
                status_code=422,
                detail=f"beat_timestamps[{index}] must be greater than 0"
            )
        if beat <= previous_beat:
            raise HTTPException(
                status_code=422,
                detail="beat_timestamps must be strictly increasing"
            )

        segment_duration = beat - previous_beat
        if segment_duration < MIN_SEGMENT_DURATION_SECONDS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Each beat interval must be at least "
                    f"{MIN_SEGMENT_DURATION_SECONDS} seconds"
                )
            )
        segment_durations.append(segment_duration)
        previous_beat = beat

    return segment_durations


def _resolve_video_cut_starts(
    video_cut_starts: Optional[List[float]],
    segment_count: int
) -> Tuple[List[float], str]:
    """
    Returns segment start offsets and mode:
    - 'per_video': two values [video1_start, video2_start]
    - 'per_segment': one value per segment
    - default: per_video with [0.0, 0.0]
    """
    if video_cut_starts is None:
        return [0.0, 0.0], "per_video"

    if len(video_cut_starts) not in (2, segment_count):
        raise HTTPException(
            status_code=422,
            detail=(
                "video_cut_starts must have either 2 values "
                "(one start for each source video) "
                f"or {segment_count} values (one start for each segment)"
            )
        )

    for index, cut_start in enumerate(video_cut_starts):
        if cut_start < 0:
            raise HTTPException(
                status_code=422,
                detail=f"video_cut_starts[{index}] must be >= 0"
            )

    if len(video_cut_starts) == 2:
        return video_cut_starts, "per_video"
    return video_cut_starts, "per_segment"


def _build_beat_sync_filter_complex(
    segment_durations: List[float],
    segment_starts: List[float],
    cut_mode: str,
    clip_durations: List[float],
    target_width: int,
    target_height: int
) -> str:
    """Build ffmpeg filter_complex for alternating beat-synced segments."""
    chains: List[str] = []
    segment_labels: List[str] = []

    for segment_index, segment_duration in enumerate(segment_durations):
        source_video_index = segment_index % 2
        source_duration = clip_durations[source_video_index]
        if source_duration <= 0:
            raise HTTPException(
                status_code=422,
                detail=f"Source video {source_video_index + 1} has invalid duration"
            )

        raw_start = (
            segment_starts[segment_index]
            if cut_mode == "per_segment"
            else segment_starts[source_video_index]
        )
        effective_start = raw_start % source_duration
        end_time = effective_start + segment_duration
        label = f"v{segment_index}"

        chains.append(
            f"[{source_video_index}:v]"
            f"trim=start={effective_start:.6f}:end={end_time:.6f},"
            "setpts=PTS-STARTPTS,"
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
            "fps=30,format=yuv420p"
            f"[{label}]"
        )
        segment_labels.append(f"[{label}]")

    chains.append(
        f"{''.join(segment_labels)}concat=n={len(segment_durations)}:v=1:a=0[vout]"
    )
    chains.append("[2:a]apad[aout]")
    return ";".join(chains)


def render_beat_sync_video(
    video_paths: List[str],
    audio_path: str,
    segment_durations: List[float],
    segment_starts: List[float],
    cut_mode: str,
    clip_durations: List[float],
    target_width: int,
    target_height: int,
    output_path: str
) -> str:
    """
    Render beat-synced video in a single ffmpeg pass.
    This avoids per-segment temp files and speeds up processing.
    """
    total_duration = sum(segment_durations)
    if total_duration <= 0:
        raise HTTPException(status_code=422, detail="Total duration must be greater than 0")

    filter_complex = _build_beat_sync_filter_complex(
        segment_durations=segment_durations,
        segment_starts=segment_starts,
        cut_mode=cut_mode,
        clip_durations=clip_durations,
        target_width=target_width,
        target_height=target_height
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", video_paths[0],
        "-stream_loop", "-1",
        "-i", video_paths[1],
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "24",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{total_duration:.6f}",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg beat-sync render error: {result.stderr}")
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


def normalize_png_filename(requested_filename: Optional[str], fallback_stem: str) -> str:
    """Return a safe PNG filename for the extracted frame."""
    filename = os.path.basename(requested_filename) if requested_filename else fallback_stem
    stem, _ = os.path.splitext(filename)
    safe_stem = stem or "frame_5"
    return f"{safe_stem}.png"


def normalize_optional_text(value) -> Optional[str]:
    """Normalize optional form values to stripped strings or None."""
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def extract_nth_frame(input_path: str, output_path: str, frame_number: int) -> str:
    """Extract a 1-based frame number from the source video as a PNG image."""
    if frame_number <= 0:
        raise ValueError("frame_number must be greater than 0")

    frame_count = get_video_frame_count(input_path)
    if frame_count is not None and frame_count < frame_number:
        raise ValueError(f"Video must contain at least {frame_number} frames")

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"select=eq(n\\,{frame_number - 1})",
        "-frames:v", "1",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg frame extraction error: {result.stderr}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ValueError(
            f"Unable to extract frame {frame_number}. The source video may not contain enough frames."
        )

    return output_path


def _build_atempo_filter(speed: float) -> str:
    """
    Build an atempo chain for arbitrary playback rates.
    ffmpeg atempo only supports factors in [0.5, 2.0] per filter.
    """
    if speed <= 0:
        raise ValueError("speed must be greater than 0")

    remaining = speed
    factors: List[float] = []

    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5

    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0

    if abs(remaining - 1.0) > 1e-9 or not factors:
        factors.append(remaining)

    return ",".join(
        f"atempo={f'{factor:.8f}'.rstrip('0').rstrip('.')}"
        for factor in factors
    )


def reverse_video(input_path: str, output_path: str) -> str:
    """Reverse video frames and reverse audio if present."""
    include_audio = has_audio_stream(input_path)

    if include_audio:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter_complex", "[0:v]reverse[vout];[0:a]areverse[aout]",
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", "reverse",
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg reverse error: {result.stderr}")
    return output_path


def change_video_speed(input_path: str, output_path: str, speed: float) -> str:
    """Apply video/audio speed change using setpts and atempo chain."""
    if speed <= 0:
        raise ValueError("speed must be greater than 0")

    include_audio = has_audio_stream(input_path)
    video_filter = f"setpts=PTS/{speed:.8f}"

    if include_audio:
        atempo_filter = _build_atempo_filter(speed)
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter_complex", f"[0:v]{video_filter}[vout];[0:a]{atempo_filter}[aout]",
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", video_filter,
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg speed change error: {result.stderr}")
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
        request_start_time = time.perf_counter()
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
            
            for i, vp in enumerate(video_paths):
                vp_dur = get_media_duration(vp)
                logger.info(f"Input clip {i} duration: {vp_dur}s — {vp}")

            concatenated_path = os.path.join(TEMP_DIR, f"concat_{session_id}.mp4")
            if len(video_paths) > 1:
                concatenate_videos_reencoded(video_paths, concatenated_path)
            else:
                concatenated_path = video_paths[0]

            concat_dur = get_media_duration(concatenated_path)
            logger.info(f"Concatenated video duration: {concat_dur}s")
            
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

            processing_time_seconds = round(time.perf_counter() - request_start_time, 3)
            
            return MergeResponse(
                success=True,
                message=f"Video and audio merged successfully. File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds.",
                output_path=output_path,
                delete_after_seconds=DELETE_AFTER_SECONDS,
                processing_time_seconds=processing_time_seconds
            )
        
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/merge-beat-sync", response_model=BeatSyncMergeResponse)
async def merge_videos_with_beat_sync(
    request: BeatSyncMergeRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Create a beat-synced video by alternating 2 clips across beat intervals.

    Behavior:
    - Requires exactly 2 input videos.
    - Uses beat_timestamps as cut points from song start (0.0s).
    - Segment durations are: [beat1-0, beat2-beat1, ...].
    - Alternates source clips as: video1, video2, video1, video2...
    - Merges the provided audio over the assembled video.
    """
    async with processing_semaphore:
        request_start_time = time.perf_counter()
        session_id = uuid.uuid4().hex
        downloaded_video_paths: List[str] = []
        audio_path: Optional[str] = None

        try:
            if len(request.video_urls) != 2:
                raise HTTPException(
                    status_code=422,
                    detail="video_urls must contain exactly 2 video URLs"
                )

            segment_durations = _validate_beat_timestamps(request.beat_timestamps)
            segment_starts, cut_mode = _resolve_video_cut_starts(
                request.video_cut_starts,
                len(segment_durations)
            )

            logger.info(
                "Received beat-sync merge request: segments=%s mode=%s",
                len(segment_durations),
                cut_mode
            )

            video_extensions = [
                os.path.splitext(str(request.video_urls[0]).split("?")[0])[1] or ".mp4",
                os.path.splitext(str(request.video_urls[1]).split("?")[0])[1] or ".mp4"
            ]
            for index in range(2):
                video_path = os.path.join(
                    TEMP_DIR,
                    f"beat_video_{session_id}_{index}{video_extensions[index]}"
                )
                downloaded_video_paths.append(video_path)

            audio_ext = os.path.splitext(str(request.audio_url).split("?")[0])[1] or ".mp3"
            audio_path = os.path.join(TEMP_DIR, f"beat_audio_{session_id}{audio_ext}")

            await asyncio.gather(
                download_file(str(request.video_urls[0]), downloaded_video_paths[0]),
                download_file(str(request.video_urls[1]), downloaded_video_paths[1]),
                download_file(str(request.audio_url), audio_path)
            )

            clip_durations = [
                get_media_duration(downloaded_video_paths[0]),
                get_media_duration(downloaded_video_paths[1])
            ]
            target_width, target_height = get_video_dimensions(downloaded_video_paths[0])

            output_filename = request.output_filename or f"beat_sync_output_{session_id}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            render_beat_sync_video(
                video_paths=downloaded_video_paths,
                audio_path=audio_path,
                segment_durations=segment_durations,
                segment_starts=segment_starts,
                cut_mode=cut_mode,
                clip_durations=clip_durations,
                target_width=target_width,
                target_height=target_height,
                output_path=output_path
            )
            schedule_file_deletion(output_path)

            processing_time_seconds = round(time.perf_counter() - request_start_time, 3)
            total_duration = round(sum(segment_durations), 3)
            return BeatSyncMergeResponse(
                success=True,
                message=(
                    "Beat-synced video created successfully. "
                    f"File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds."
                ),
                output_path=output_path,
                delete_after_seconds=DELETE_AFTER_SECONDS,
                processing_time_seconds=processing_time_seconds,
                segments_created=len(segment_durations),
                total_duration_seconds=total_duration,
            )

        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            for temp_video_path in downloaded_video_paths:
                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
                    logger.info(f"Deleted temp beat video: {temp_video_path}")

            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
                logger.info(f"Deleted temp beat audio: {audio_path}")


def trim_video(input_path: str, output_path: str, trim_from: Optional[float], trim_to: Optional[float]) -> Tuple[float, float]:
    """
    Trim a video using ffmpeg.
    - trim_from only: cut from that point to end of video
    - trim_to only: cut from start to that point
    - both: extract the segment between trim_from and trim_to
    - neither: raises an error
    Returns (original_duration, trimmed_duration).
    """
    original_duration = get_media_duration(input_path)

    if trim_from is not None and trim_from < 0:
        raise ValueError("trim_from must be >= 0")
    if trim_to is not None and trim_to < 0:
        raise ValueError("trim_to must be >= 0")
    if trim_from is not None and trim_to is not None and trim_from >= trim_to:
        raise ValueError("trim_from must be less than trim_to")
    if trim_from is not None and trim_from >= original_duration:
        raise ValueError(f"trim_from ({trim_from}) exceeds video duration ({original_duration})")
    if trim_to is not None and trim_to > original_duration:
        logger.warning(f"trim_to ({trim_to}) exceeds video duration ({original_duration}), clamping to video end")
        trim_to = original_duration

    cmd = ["ffmpeg", "-y"]

    if trim_from is not None:
        cmd += ["-ss", f"{trim_from:.6f}"]

    cmd += ["-i", input_path]

    if trim_to is not None:
        if trim_from is not None:
            cmd += ["-t", f"{(trim_to - trim_from):.6f}"]
        else:
            cmd += ["-t", f"{trim_to:.6f}"]

    cmd += ["-c", "copy", output_path]

    logger.info(f"Running trim ffmpeg command")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg trim error: {result.stderr}")

    trimmed_duration = get_media_duration(output_path)
    return original_duration, trimmed_duration


@app.post("/trim", response_model=TrimResponse)
async def trim_video_endpoint(request: TrimRequest, _: bool = Depends(verify_api_key)):
    """
    Trim a video clip.

    Modes:
    - trim_from only: removes the first N seconds, returns the rest
    - trim_to only: keeps the first N seconds, removes the rest
    - both trim_from and trim_to: extracts the segment between those two points
    - Requires X-API-Key header for authentication
    """
    async with processing_semaphore:
        request_start_time = time.perf_counter()
        video_path = None
        try:
            if request.trim_from is None and request.trim_to is None:
                raise HTTPException(
                    status_code=422,
                    detail="At least one of trim_from or trim_to must be provided"
                )

            logger.info(f"Received trim request: trim_from={request.trim_from}, trim_to={request.trim_to}")
            session_id = uuid.uuid4().hex

            video_ext = os.path.splitext(str(request.video_url).split("?")[0])[1] or ".mp4"
            video_path = os.path.join(TEMP_DIR, f"trim_input_{session_id}{video_ext}")
            await download_file(str(request.video_url), video_path)

            output_filename = request.output_filename or f"trimmed_{session_id}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_filename)

            original_duration, trimmed_duration = trim_video(
                video_path, output_path, request.trim_from, request.trim_to
            )

            schedule_file_deletion(output_path)

            processing_time_seconds = round(time.perf_counter() - request_start_time, 3)

            return TrimResponse(
                success=True,
                message=f"Video trimmed successfully. File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds.",
                output_path=output_path,
                delete_after_seconds=DELETE_AFTER_SECONDS,
                processing_time_seconds=processing_time_seconds,
                original_duration_seconds=round(original_duration, 3),
                trimmed_duration_seconds=round(trimmed_duration, 3)
            )

        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"Deleted temp trim input: {video_path}")


@app.post("/reverse", response_model=VideoTransformResponse)
async def reverse_video_endpoint(request: ReverseRequest, _: bool = Depends(verify_api_key)):
    """Reverse an entire video clip (and audio track when available)."""
    async with processing_semaphore:
        request_start_time = time.perf_counter()
        video_path = None
        try:
            logger.info("Received reverse request")
            session_id = uuid.uuid4().hex

            video_ext = os.path.splitext(str(request.video_url).split("?")[0])[1] or ".mp4"
            video_path = os.path.join(TEMP_DIR, f"reverse_input_{session_id}{video_ext}")
            await download_file(str(request.video_url), video_path)

            output_filename = request.output_filename or f"reversed_{session_id}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_filename)

            original_duration = get_media_duration(video_path)
            reverse_video(video_path, output_path)
            transformed_duration = get_media_duration(output_path)
            schedule_file_deletion(output_path)

            processing_time_seconds = round(time.perf_counter() - request_start_time, 3)

            return VideoTransformResponse(
                success=True,
                message=(
                    "Video reversed successfully. "
                    f"File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds."
                ),
                output_path=output_path,
                delete_after_seconds=DELETE_AFTER_SECONDS,
                processing_time_seconds=processing_time_seconds,
                original_duration_seconds=round(original_duration, 3),
                transformed_duration_seconds=round(transformed_duration, 3)
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"Deleted temp reverse input: {video_path}")


@app.post("/speed", response_model=SpeedResponse)
async def speed_video_endpoint(request: SpeedRequest, _: bool = Depends(verify_api_key)):
    """Speed up or slow down a video clip based on the provided playback factor."""
    async with processing_semaphore:
        request_start_time = time.perf_counter()
        video_path = None
        try:
            if request.speed <= 0:
                raise HTTPException(status_code=422, detail="speed must be greater than 0")

            logger.info(f"Received speed request: speed={request.speed}")
            session_id = uuid.uuid4().hex

            video_ext = os.path.splitext(str(request.video_url).split("?")[0])[1] or ".mp4"
            video_path = os.path.join(TEMP_DIR, f"speed_input_{session_id}{video_ext}")
            await download_file(str(request.video_url), video_path)

            speed_token = f"{request.speed:.3f}".rstrip("0").rstrip(".").replace(".", "_")
            output_filename = request.output_filename or f"speed_{speed_token}x_{session_id}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_filename)

            original_duration = get_media_duration(video_path)
            change_video_speed(video_path, output_path, request.speed)
            transformed_duration = get_media_duration(output_path)
            schedule_file_deletion(output_path)

            processing_time_seconds = round(time.perf_counter() - request_start_time, 3)

            return SpeedResponse(
                success=True,
                message=(
                    "Video speed changed successfully. "
                    f"File will be auto-deleted in {DELETE_AFTER_SECONDS} seconds."
                ),
                output_path=output_path,
                delete_after_seconds=DELETE_AFTER_SECONDS,
                processing_time_seconds=processing_time_seconds,
                original_duration_seconds=round(original_duration, 3),
                transformed_duration_seconds=round(transformed_duration, 3),
                speed=request.speed
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"Deleted temp speed input: {video_path}")


@app.post(
    "/extract-fifth-frame",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
async def extract_fifth_frame_endpoint(
    request: Request,
    _: bool = Depends(verify_api_key)
):
    """Extract the fifth frame from a video URL or uploaded file and return a PNG."""
    async with processing_semaphore:
        session_id = uuid.uuid4().hex
        video_path = None
        frame_path = os.path.join(TEMP_DIR, f"frame_output_{session_id}.png")
        cleanup_paths = [frame_path]

        try:
            logger.info("Received fifth-frame extraction request")
            content_type = request.headers.get("content-type", "")
            output_filename = None

            if "multipart/form-data" in content_type:
                form = await request.form()
                uploaded_file = form.get("video_file")
                raw_video_url = normalize_optional_text(form.get("video_url"))
                output_filename = normalize_optional_text(form.get("output_filename"))

                has_uploaded_file = bool(getattr(uploaded_file, "filename", ""))
                has_video_url = raw_video_url is not None

                if has_uploaded_file and has_video_url:
                    raise HTTPException(
                        status_code=422,
                        detail="Provide either video_url or video_file, not both"
                    )
                if not has_uploaded_file and not has_video_url:
                    raise HTTPException(
                        status_code=422,
                        detail="Provide either video_url or video_file"
                    )

                if has_uploaded_file:
                    video_ext = os.path.splitext(uploaded_file.filename or "")[1] or ".mp4"
                    video_path = os.path.join(TEMP_DIR, f"frame_upload_{session_id}{video_ext}")
                    cleanup_paths.insert(0, video_path)
                    await save_uploaded_file(uploaded_file, video_path)
                else:
                    payload = FifthFrameRequest(
                        video_url=raw_video_url,
                        output_filename=output_filename
                    )
                    video_ext = os.path.splitext(str(payload.video_url).split("?")[0])[1] or ".mp4"
                    video_path = os.path.join(TEMP_DIR, f"frame_input_{session_id}{video_ext}")
                    cleanup_paths.insert(0, video_path)
                    await download_file(str(payload.video_url), video_path)
                    output_filename = payload.output_filename
            else:
                try:
                    payload = FifthFrameRequest(**(await request.json()))
                except ValidationError as e:
                    raise HTTPException(status_code=422, detail=e.errors())
                except ValueError:
                    raise HTTPException(status_code=422, detail="Invalid JSON request body")

                video_ext = os.path.splitext(str(payload.video_url).split("?")[0])[1] or ".mp4"
                video_path = os.path.join(TEMP_DIR, f"frame_input_{session_id}{video_ext}")
                cleanup_paths.insert(0, video_path)
                await download_file(str(payload.video_url), video_path)
                output_filename = payload.output_filename

            extract_nth_frame(video_path, frame_path, frame_number=5)

            output_filename = normalize_png_filename(
                output_filename,
                fallback_stem=f"frame_5_{session_id}"
            )
            response = FileResponse(
                frame_path,
                media_type="image/png",
                filename=output_filename,
                background=BackgroundTask(cleanup_files, cleanup_paths)
            )
            cleanup_paths = []
            return response
        except ValidationError as e:
            cleanup_files(cleanup_paths)
            raise HTTPException(status_code=422, detail=e.errors())
        except ValueError as e:
            cleanup_files(cleanup_paths)
            raise HTTPException(status_code=422, detail=str(e))
        except httpx.HTTPError as e:
            cleanup_files(cleanup_paths)
            raise HTTPException(status_code=400, detail=f"Failed to download file: {str(e)}")
        except HTTPException:
            cleanup_files(cleanup_paths)
            raise
        except Exception as e:
            cleanup_files(cleanup_paths)
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
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")
