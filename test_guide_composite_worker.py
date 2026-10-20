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
    mask = np.zeros((80, 1000), np.uint8)
    mask[0:20, 100:400] = 255   # torso: 200 px wider than an arm (100 px free), so 12% of 200 = 24 px a side
    mask[20:40, 0:300] = 255    # cut off by the left edge: only the right side moves
    mask[40:60, 300:380] = 255  # an 80 px arm or head keeps its width
    mask[60:80, 100:900] = 255  # 12% of 700 = 84 px is capped at 4% of 1000 = 40 px
    out = worker.slim_mask(mask, 0.12)
    assert np.flatnonzero(out[10])[[0, -1]].tolist() == [124, 375]
    assert np.flatnonzero(out[30])[[0, -1]].tolist() == [0, 275]
    assert np.flatnonzero(out[50])[[0, -1]].tolist() == [300, 379]
    assert np.flatnonzero(out[70])[[0, -1]].tolist() == [140, 859]
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
