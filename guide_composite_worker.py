"""Composite a depth guide: depth people over the original frames.

Reads the normalized clip, its depth video and one SAM mask PNG per frame,
cleans each mask and writes the guide. Runs in the face-mesh environment
(setup-face-mesh.sh) because it needs NumPy and OpenCV; main.py calls it as a
subprocess and falls back to its FFmpeg-only composite without it.

Mask cleanup, per frame:
- Thin bands along the frame border are dropped. SAM 3 sometimes returns a
  ragged strip down an edge where nobody is, which became a depth stripe.
  Specks are dropped too.
- Far-depth mask pieces lying wholly within a band along the top or side
  edges are dropped. SAM sometimes gives a person a band of sky or
  trees along the frame edge, attached to them, which the depth paints black.
  A person cut off by the frame edge is near, so they stay.
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
import struct
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
# How far in from the top and side edges the far-depth check reaches, as a
# share of the short side, and how much darker (farther) than the person's
# median depth a pixel must be to count as background.
EDGE_BAND_SHARE = 0.08
FAR_DEPTH_RATIO = 0.35
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
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


def read_mask(path, width, height):
    """Decodes a mask only if it is a PNG of sane size: zip entries are untrusted bytes."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise SystemExit(f"{os.path.basename(path)} is not a PNG image")
    mask_width, mask_height = struct.unpack(">II", data[16:24])
    if not (0 < mask_width <= 4 * width and 0 < mask_height <= 4 * height):
        raise SystemExit(f"{os.path.basename(path)} is {mask_width}x{mask_height}, too large for the video")
    raw = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if raw is None:
        raise SystemExit(f"{os.path.basename(path)} could not be decoded")
    return raw


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


def drop_far_edge_pixels(mask, depth):
    """Clears far-depth mask pieces that lie wholly within the top or side edge band."""
    height, width = mask.shape
    band = max(1, round(EDGE_BAND_SHARE * min(width, height)))
    near_edge = np.zeros(mask.shape, bool)
    near_edge[:band] = True
    near_edge[:, :band] = True
    near_edge[:, -band:] = True
    masked = mask > 0
    if not (masked & near_edge).any():
        return mask, 0
    # The depth colors run from black (far) to bright (near), so brightness
    # orders depth. The colormap isn't linear: the ratio is on brightness, not
    # on depth. The people's median is the reference, since a detached strip
    # has no body of its own to compare with.
    nearness = depth[masked].astype(np.float32).mean(axis=1)
    far = np.zeros(mask.shape, np.uint8)
    far[masked] = nearness < FAR_DEPTH_RATIO * float(np.median(nearness))
    count, labels = cv2.connectedComponents(far, connectivity=8)
    if count <= 1:
        return mask, 0
    # A strip of sky lies wholly inside the band; a far person cut off by the
    # frame edge reaches past it and stays.
    inside = np.bincount(labels[near_edge], minlength=count) == np.bincount(labels.ravel(), minlength=count)
    inside[0] = False
    drop = inside[labels]
    mask[drop] = 0
    return mask, int(drop.sum())


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
        raw = read_mask(os.path.join(args.mask_dir, f"mask_{index:05d}.png"), width, height)
        if raw.shape != (height, width):
            raw = cv2.resize(raw, (width, height), interpolation=cv2.INTER_NEAREST)
        mask = np.where(raw > 127, 255, 0).astype(np.uint8)
        mask, dropped = drop_stray_pieces(mask)
        dropped_total += dropped
        if mask.any():
            mask, dropped = drop_far_edge_pixels(mask, depth)
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
