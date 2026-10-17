"""Composite a depth guide: depth people over the original frames.

Reads the normalized clip, its depth video and one SAM mask PNG per frame,
cleans each mask and writes the guide. Runs in the face-mesh environment
(setup-face-mesh.sh) because it needs NumPy and OpenCV; main.py calls it as a
subprocess and falls back to its FFmpeg-only composite without it.

Mask cleanup, per frame:
- Thin bands along the frame border are dropped. SAM 3 sometimes returns a
  ragged strip down an edge where nobody is, which became a depth stripe.
  Specks are dropped too.
- Background the mask closes off is filled, counting the bottom edge as
  closed: SAM leaves some clothing (a tie, a bag strap) and, in extreme
  close-ups, the lips out of the person.
- The grown ring around each person takes that person's nearest depth color,
  not the background's depth, so the guide has no dark outline.

usage: guide_composite_worker.py VIDEO DEPTH MASK_DIR OUTPUT --frames N --fps F
       [--spread PX] [--fill-holes] [--audio PATH]
Prints one JSON line: {"frames": n, "masked_frames": n, "dropped_border_pixels": n}
"""
import argparse
import json
import os
import subprocess
import sys

import cv2
import numpy as np

# Specks smaller than this share of the frame are dropped (SAM scatters a few
# in letterbox bars and on busy textures).
SPECK_SHARE = 0.0003
# Border components thinner than this share of the short side are dropped.
BORDER_SLIVER_RADIUS = 0.02
# A border component hugging the edge for this many times its thickness is a
# band, not a person cut off by the frame.
BORDER_BAND_RATIO = 12
# Depth at a mask's very edge blends into the background; colors are sampled
# this far inside.
EDGE_INSET = 2


def reader(path, width, height, frames, video_filter=None):
    command = ["ffmpeg", "-v", "error", "-i", path]
    if video_filter:
        command += ["-vf", video_filter]
    command += ["-frames:v", str(frames), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    size = width * height * 3
    try:
        for _ in range(frames):
            data = process.stdout.read(size)
            if len(data) < size:
                raise SystemExit(f"{os.path.basename(path)} ended early")
            yield np.frombuffer(data, np.uint8).reshape(height, width, 3)
    finally:
        process.stdout.close()
        process.wait()


def drop_stray_pieces(mask):
    """Removes specks, and components that touch the frame border and are only a thin band there."""
    height, width = mask.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask, 0
    edge = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    contact = np.bincount(edge, minlength=count)
    distance = None
    min_radius = BORDER_SLIVER_RADIUS * min(width, height)
    min_area = SPECK_SHARE * width * height
    dropped = 0
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area < min_area:
            mask[y:y + h, x:x + w][labels[y:y + h, x:x + w] == label] = 0
            dropped += int(area)
            continue
        if not contact[label]:
            continue
        if distance is None:
            distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        component = labels[y:y + h, x:x + w] == label
        radius = float(distance[y:y + h, x:x + w][component].max())
        if radius < min_radius or contact[label] >= BORDER_BAND_RATIO * 2 * radius:
            mask[y:y + h, x:x + w][component] = 0
            dropped += int(area)
    return mask, dropped


def fill_holes(mask):
    """Fills background the mask closes off; the bottom edge counts as closed."""
    background = (mask == 0).astype(np.uint8)
    _, labels = cv2.connectedComponents(background, connectivity=4)
    open_labels = np.unique(np.concatenate([labels[0], labels[:, 0], labels[:, -1]]))
    mask[(labels > 0) & ~np.isin(labels, open_labels)] = 255
    return mask


def depth_with_ring(depth, mask, grown):
    """Depth inside `grown`; pixels outside the mask's inset core take the nearest core pixel's color."""
    core = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=EDGE_INSET)
    if not core.any():
        core = mask
    # Each non-core pixel gets the label of its nearest core pixel; labels
    # number the core pixels in row-major order from 1.
    _, nearest = cv2.distanceTransformWithLabels((core == 0).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    core_pixels = np.flatnonzero(core.ravel())
    ring = (grown > 0) & (core == 0)
    filled = depth.copy()
    filled.reshape(-1, 3)[np.flatnonzero(ring.ravel())] = depth.reshape(-1, 3)[core_pixels[nearest[ring] - 1]]
    return filled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("depth")
    parser.add_argument("mask_dir")
    parser.add_argument("output")
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--spread", type=int, default=0)
    parser.add_argument("--fill-holes", action="store_true")
    parser.add_argument("--audio")
    args = parser.parse_args()
    width, height, frames, fps = args.width, args.height, args.frames, args.fps

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * args.spread + 1, 2 * args.spread + 1)) if args.spread else None
    command = [
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
    ]
    if args.audio:
        command += ["-i", args.audio, "-map", "0:v", "-map", "1:a:0", "-af", f"apad,atrim=duration={frames / fps:.6f}", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        command += ["-an"]
    command += [
        "-frames:v", str(frames), "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.output,
    ]
    writer = subprocess.Popen(command, stdin=subprocess.PIPE)
    masked = 0
    dropped_total = 0
    originals = reader(args.video, width, height, frames)
    depths = reader(args.depth, width, height, frames, f"fps={fps},scale={width}:{height}:flags=bilinear,tpad=stop_mode=clone:stop_duration=1")
    for index, (original, depth) in enumerate(zip(originals, depths)):
        raw = cv2.imread(os.path.join(args.mask_dir, f"mask_{index:05d}.png"), cv2.IMREAD_GRAYSCALE)
        if raw is None:
            raise SystemExit(f"Mask {index} is missing or not an image")
        if raw.shape != (height, width):
            raw = cv2.resize(raw, (width, height), interpolation=cv2.INTER_NEAREST)
        mask = np.where(raw > 127, 255, 0).astype(np.uint8)
        mask, dropped = drop_stray_pieces(mask)
        dropped_total += dropped
        frame = original
        if mask.any():
            masked += 1
            if args.fill_holes:
                mask = fill_holes(mask)
            grown = cv2.dilate(mask, kernel) if kernel is not None else mask
            frame = np.where(grown[..., None] > 0, depth_with_ring(depth, mask, grown), original)
        writer.stdin.write(np.ascontiguousarray(frame).tobytes())
    writer.stdin.close()
    if writer.wait() != 0:
        raise SystemExit("Encoding the composite failed")
    print(json.dumps({"frames": frames, "masked_frames": masked, "dropped_border_pixels": dropped_total}))


if __name__ == "__main__":
    sys.exit(main())
