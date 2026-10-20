"""Draw a face mesh on a guide video.

Faces are found on the ORIGINAL frames and the mesh is drawn on the matching
GUIDE frames, where the people are hidden, so a video model can follow mouth
and expression movement without seeing who they are. Runs in its own
environment (setup-face-mesh.sh) because MediaPipe pulls in OpenCV; main.py
calls it as a subprocess.

MediaPipe's own face detector only finds faces that fill a good part of the
frame, so on a wide 1280 px shot it missed nearly everyone. Faces are found
with OpenCV's YuNet, which handles small faces, and the 478-point Face
Landmarker runs on an enlarged crop of each one. Every frame is detected on
its own, so nothing carries over a cut. Faces turned past MAX_YAW are left
out: the mesh of a profile lands on the cheek or the back of the head. Faces
the guide shows as filmed (it hides only the people being replaced) are left
out too, so no mesh is drawn onto a real face.

usage: face_mesh_worker.py SOURCE GUIDE OUTPUT MODEL --detector YUNET [--max-faces N]
Prints one JSON line: {"frames": n, "tracked_frames": n, "faces": max_faces_seen}
"""
import argparse
import json
import subprocess
import sys
import types

# MediaPipe imports sounddevice for its microphone tasks, and sounddevice starts
# PortAudio on import, which fails on a server with no audio system. The face
# mesh never records audio, so an empty module stands in for it.
sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))

import cv2  # noqa: E402
import mediapipe as mp  # noqa: E402
import numpy as np  # noqa: E402

# YuNet scores below this are not faces.
DETECT_SCORE = 0.7
# Each face is cropped this many times its box size and resized to CROP_SIZE
# for the landmarker.
CROP_SCALE = 2.2
CROP_SIZE = 384
MAX_YAW = 60
# A face box moving less than this share of its size since the previous frame
# is averaged with it, which steadies the crop and so the mesh.
SMOOTH_DISTANCE = 0.25

# A face whose guide pixels differ from the source by less than this (mean, 0-255)
# is shown as filmed, not hidden under a silhouette, and gets no mesh.
FILMED_DIFF = 25

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


def steady(box, previous):
    """Averages a face box with the nearest one from the previous frame when it barely moved."""
    cx, cy, size = box
    for px, py, psize in previous:
        if abs(px - cx) + abs(py - cy) < SMOOTH_DISTANCE * size and abs(psize - size) < SMOOTH_DISTANCE * size:
            return ((cx + px) / 2, (cy + py) / 2, (size + psize) / 2)
    return box


def hidden(source, guide, cx, cy, size):
    """True when the guide hides this face under a silhouette. A guide may keep
    some people as filmed; a mesh on a real face would be drawn into the result."""
    sh, sw = source.shape[:2]
    gh, gw = guide.shape[:2]
    half = max(2, size / 4)
    x0, x1, y0, y1 = int(max(0, cx - half)), int(min(sw, cx + half)), int(max(0, cy - half)), int(min(sh, cy + half))
    if x1 <= x0 or y1 <= y0:
        return False
    patch = source[y0:y1, x0:x1].astype(np.int16)
    covered = guide[y0 * gh // sh:max(y0 * gh // sh + 1, y1 * gh // sh), x0 * gw // sw:max(x0 * gw // sw + 1, x1 * gw // sw)]
    covered = cv2.resize(covered, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA).astype(np.int16)
    return float(np.abs(patch - covered).mean()) >= FILMED_DIFF


def landmarks_in_crop(landmarker, frame, cx, cy, side):
    """478 face points in frame pixels from a square crop around (cx, cy), or None for no face or a profile."""
    ratio = CROP_SIZE / side
    transform = np.float32([[ratio, 0, CROP_SIZE / 2 - cx * ratio], [0, ratio, CROP_SIZE / 2 - cy * ratio]])
    crop = cv2.warpAffine(frame, transform, (CROP_SIZE, CROP_SIZE), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop)))
    if not result.face_landmarks:
        return None
    rotation = np.array(result.facial_transformation_matrixes[0])[:3, :3]
    if abs(np.degrees(np.arctan2(rotation[0, 2], rotation[2, 2]))) > MAX_YAW:
        return None
    left, top = cx - side / 2, cy - side / 2
    return [(left + point.x * side, top + point.y * side) for point in result.face_landmarks[0]]


def main():
    if sys.argv[1:2] == ["--check"]:
        # Loading the landmarker also loads its native libraries (EGL), so a
        # missing system package shows up here rather than on the first job.
        if len(sys.argv) > 2:
            options = mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=sys.argv[2]))
            with mp.tasks.vision.FaceLandmarker.create_from_options(options):
                pass
        if len(sys.argv) > 3:
            cv2.FaceDetectorYN.create(sys.argv[3], "", (320, 320))
        print(f"face mesh ready: mediapipe {mp.__version__}, opencv {cv2.__version__}")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("guide")
    parser.add_argument("output")
    parser.add_argument("model")
    parser.add_argument("--detector", required=True)
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
    detector = cv2.FaceDetectorYN.create(args.detector, "", (sw, sh), DETECT_SCORE, 0.3, 5000)
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=args.model),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        output_facial_transformation_matrixes=True,
    )
    writer = subprocess.Popen([
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{gw}x{gh}", "-r", f"{fps}", "-i", "-",
        "-i", args.guide, "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
        "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-shortest", args.output,
    ], stdin=subprocess.PIPE)
    tracked = 0
    most_faces = 0
    previous = []
    with mp.tasks.vision.FaceLandmarker.create_from_options(options) as landmarker:
        for source, guide in zip(reader(args.source, sw, sh), reader(args.guide, gw, gh)):
            _, found = detector.detect(cv2.cvtColor(source, cv2.COLOR_RGB2BGR))
            boxes = [] if found is None else sorted(found.tolist(), key=lambda face: -face[14])
            # Filmed faces never take one of the max_faces slots.
            boxes = [box for box in boxes if hidden(source, guide, box[0] + box[2] / 2, box[1] + box[3] / 2, max(box[2], box[3]))][:args.max_faces]
            boxes = [steady((x + w / 2, y + h / 2, max(w, h)), previous) for x, y, w, h, *_ in boxes]
            previous = boxes
            frame = guide.copy()
            faces = 0
            for cx, cy, size in boxes:
                points = landmarks_in_crop(landmarker, source, cx, cy, size * CROP_SCALE)
                if points is None:
                    continue
                faces += 1
                points = [(round(x * gw / sw), round(y * gh / sh)) for x, y in points]
                for edges, color, width in groups:
                    for edge in edges:
                        cv2.line(frame, points[edge.start], points[edge.end], color, width * scale, cv2.LINE_AA)
            if faces:
                tracked += 1
                most_faces = max(most_faces, faces)
            writer.stdin.write(frame.tobytes())
    writer.stdin.close()
    if writer.wait() != 0:
        raise SystemExit("Encoding the meshed guide failed")
    print(json.dumps({"frames": guide_frames, "tracked_frames": tracked, "faces": most_faces}))


if __name__ == "__main__":
    sys.exit(main())
