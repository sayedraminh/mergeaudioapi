import pytest

# The worker runs in the face-mesh environment; the API's own one has neither.
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
import guide_composite_worker as worker  # noqa: E402


def frame(height=200, width=120):
    # Depth: a far, black background with a near, bright person on the right.
    depth = np.zeros((height, width, 3), np.uint8)
    mask = np.zeros((height, width), np.uint8)
    depth[40:, 50:] = 220
    mask[40:, 50:] = 255
    return mask, depth


def test_a_far_strip_along_the_edge_is_dropped_whether_detached_or_attached():
    mask, depth = frame()
    mask[10:120, 0:8] = 255  # sky strip down the left edge, on black depth
    mask[0:6, 50:110] = 255  # a band along the top, attached to nothing near
    out, dropped = worker.drop_far_edge_pixels(mask.copy(), depth)
    assert not out[10:120, 0:8].any() and not out[0:6, 50:110].any()
    assert dropped == 110 * 8 + 6 * 60
    assert out[100, 80] == 255, "the person stays"


def test_a_near_person_cut_off_by_the_frame_edge_stays():
    mask, depth = frame()
    mask[60:160, 0:10] = 255  # a head cut off by the left edge, as near as the person
    depth[60:160, 0:10] = 200
    out, dropped = worker.drop_far_edge_pixels(mask.copy(), depth)
    assert dropped == 0 and out[100, 5] == 255


def test_a_far_person_in_the_middle_of_the_frame_is_not_touched():
    mask, depth = frame()
    mask[80:120, 20:30] = 255  # dark depth, but away from the edges
    out, dropped = worker.drop_far_edge_pixels(mask.copy(), depth)
    assert dropped == 0


def test_a_far_person_cut_off_by_the_side_edge_stays_whole():
    mask, depth = frame()
    # A passer-by far behind the subject, cut off by the left edge but reaching past the band.
    mask[60:180, 0:40] = 255
    depth[60:180, 0:40] = 40
    out, dropped = worker.drop_far_edge_pixels(mask.copy(), depth)
    assert dropped == 0 and out[60:180, 0:40].all()


def test_slim_narrows_wide_runs_keeps_arms_and_frame_edges_and_caps():
    # Blocks of 20 identical rows, checked in the middle so the vertical smoothing doesn't matter.
    mask = np.zeros((100, 1000), np.uint8)
    mask[0:20, 100:400] = 255   # torso: 200 px wider than an arm (100 px free), so 12% of 200 = 24 px a side
    mask[20:40, 0:300] = 255    # cut off by the left edge: only the right side moves
    mask[80:100, 12:312] = 255  # SAM stopped 12 px short of the edge (within 2% of 1000 = 20 px): same
    mask[40:60, 300:380] = 255  # an 80 px arm or head keeps its width
    mask[60:80, 100:900] = 255  # 12% of 700 = 84 px is capped at 4% of 1000 = 40 px
    out = worker.slim_mask(mask, 0.12)
    assert np.flatnonzero(out[10])[[0, -1]].tolist() == [124, 375]
    assert np.flatnonzero(out[30])[[0, -1]].tolist() == [0, 275]
    assert np.flatnonzero(out[50])[[0, -1]].tolist() == [300, 379]
    assert np.flatnonzero(out[70])[[0, -1]].tolist() == [140, 859]
    assert np.flatnonzero(out[90])[[0, -1]].tolist() == [12, 287]
    assert not (out & ~mask).any(), "slimming never grows the person"


def test_slim_paints_the_room_over_the_freed_edge():
    for top, bottom, left, right in [(10, 50, 30, 50), (11, 49, 31, 49)]:  # even and odd edges
        original = np.zeros((60, 80, 3), np.uint8)
        original[:] = (0, 0, 200)                      # the room is blue
        original[top:bottom, left:right] = (200, 0, 0)  # the person is red
        person = np.zeros((60, 80), bool)
        person[top:bottom, left:right] = True
        drawn = np.zeros((60, 80), bool)
        drawn[top:bottom, left + 4:right - 4] = True
        out = worker.paint_room(original.copy(), original, person & ~drawn, person)
        freed = out[person & ~drawn]
        assert freed[:, 0].max() < 80 and freed[:, 2].min() > 120, f"no body color in the freed edge ({top},{left})"
        assert (out[drawn] == (200, 0, 0)).all(), "the drawn person is untouched"


def test_depth_background_draws_gray_people_over_the_depth_and_paints_over_their_depth_outline(tmp_path):
    import subprocess
    import sys

    def video(path, color):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=96x64:r=24:d=0.25",
                        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(path)], check=True)

    original, depth, output = tmp_path / "original.mp4", tmp_path / "depth.mp4", tmp_path / "guide.mp4"
    video(original, "0x0000c8")  # the filmed room is blue
    # Depth: far purple, with the hidden person near and orange (wider than the mask, like loose hair).
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x502878:s=96x64:r=24:d=0.25",
                    "-vf", "drawbox=x=30:y=10:w=36:h=54:color=0xf0a028:t=fill", "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(depth)], check=True)
    masks = tmp_path / "masks"
    masks.mkdir()
    mask = np.zeros((64, 96), np.uint8)
    mask[16:64, 36:60] = 255
    for index in range(6):
        cv2.imwrite(str(masks / f"mask_{index:05d}.png"), mask)
    subprocess.run([sys.executable, worker.__file__, str(original), str(masks), str(output), "--frames", "6", "--fps", "24",
                    "--width", "96", "--height", "64", "--depth", str(depth), "--depth-background", "--fill-holes"], check=True, capture_output=True)
    frames = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                          check=True, capture_output=True).stdout, np.uint8).reshape(-1, 64, 96, 3).astype(int)
    assert len(frames) == 6
    last = frames[-1]
    assert np.abs(last[40, 48] - 126).max() <= 6, "the person is flat gray"
    assert np.abs(last[5, 5] - (0x50, 0x28, 0x78)).max() <= 12, "the background is the depth video, not the filmed room"
    outline = last[30:60, 31:34]  # the depth's own orange person, just outside the mask
    assert np.abs(outline - (0x50, 0x28, 0x78)).max(axis=2).max() <= 40, "the depth outline of the hidden person is painted over"


def test_depth_background_needs_a_depth_video(tmp_path):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, worker.__file__, "v.mp4", str(tmp_path), "o.mp4", "--frames", "1", "--fps", "24",
                             "--width", "8", "--height", "8", "--depth-background"], capture_output=True, text=True)
    assert result.returncode != 0 and "--depth-background needs --depth" in result.stderr
