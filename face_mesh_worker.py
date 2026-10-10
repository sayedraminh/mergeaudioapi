"""Draw a face-tracking mesh on a guide video.

Faces are tracked on the ORIGINAL frames (MediaPipe Face Landmarker, 478
points) and the mesh is drawn on the matching GUIDE frames, where the people
are hidden, so a video model can follow mouth and expression movement without
seeing who they are. Runs in its own environment (setup-face-mesh.sh) because
MediaPipe pulls in OpenCV; main.py calls it as a subprocess.

usage: face_mesh_worker.py SOURCE GUIDE OUTPUT MODEL [--max-faces N]
Prints one JSON line: {"frames": n, "tracked_frames": n, "faces": max_faces_seen}
"""
import argparse
import json
import subprocess
import sys

import cv2
import mediapipe as mp
import numpy as np

# RGB: frames are decoded as rgb24.
TESSELATION = (50, 170, 205)
LIPS = (255, 135, 100)
EYES = (130, 255, 150)


def probe(path):
    out = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate", "-of", "json", path,
    ], capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    num, _, den = stream["r_frame_rate"].partition("/")
    return int(stream["width"]), int(stream["height"]), int(stream["nb_read_frames"]), float(num) / float(den or 1)


def reader(path, width, height):
    process = subprocess.Popen([
        "ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], stdout=subprocess.PIPE)
    size = width * height * 3
    while True:
        data = process.stdout.read(size)
        if len(data) < size:
            break
        yield np.frombuffer(data, np.uint8).reshape(height, width, 3)
    process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("guide")
    parser.add_argument("output")
    parser.add_argument("model")
    parser.add_argument("--max-faces", type=int, default=4)
    args = parser.parse_args()

    sw, sh, source_frames, fps = probe(args.source)
    gw, gh, guide_frames, _ = probe(args.guide)
    if source_frames != guide_frames:
        raise SystemExit(f"Source has {source_frames} frames and guide {guide_frames}; they must match")

    connections = mp.tasks.vision.FaceLandmarksConnections
    groups = [
        (connections.FACE_LANDMARKS_TESSELATION, TESSELATION, 1),
        (connections.FACE_LANDMARKS_LIPS, LIPS, 2),
        (connections.FACE_LANDMARKS_LEFT_EYE, EYES, 2),
        (connections.FACE_LANDMARKS_RIGHT_EYE, EYES, 2),
    ]
    # Thicker lines on large frames so the mesh survives the provider's resize.
    scale = max(1, round(max(gw, gh) / 960))
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=args.model),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=args.max_faces,
        min_face_detection_confidence=0.3,
        min_face_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    writer = subprocess.Popen([
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{gw}x{gh}", "-r", f"{fps}", "-i", "-",
        "-i", args.guide, "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
        "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-shortest", args.output,
    ], stdin=subprocess.PIPE)
    tracked = 0
    most_faces = 0
    with mp.tasks.vision.FaceLandmarker.create_from_options(options) as landmarker:
        for index, (source, guide) in enumerate(zip(reader(args.source, sw, sh), reader(args.guide, gw, gh))):
            result = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(source)),
                round(index * 1000 / fps),
            )
            frame = guide.copy()
            if result.face_landmarks:
                tracked += 1
                most_faces = max(most_faces, len(result.face_landmarks))
            for face in result.face_landmarks:
                points = [(round(point.x * gw), round(point.y * gh)) for point in face]
                for edges, color, width in groups:
                    for edge in edges:
                        cv2.line(frame, points[edge.start], points[edge.end], color, width * scale, cv2.LINE_AA)
            writer.stdin.write(frame.tobytes())
    writer.stdin.close()
    if writer.wait() != 0:
        raise SystemExit("Encoding the meshed guide failed")
    print(json.dumps({"frames": guide_frames, "tracked_frames": tracked, "faces": most_faces}))


if __name__ == "__main__":
    sys.exit(main())
