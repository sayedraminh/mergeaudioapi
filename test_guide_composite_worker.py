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


def test_slim_narrows_each_row_toward_its_middle_and_caps_long_runs():
    mask = np.zeros((4, 1000), np.uint8)
    mask[0, 100:200] = 255   # a 100 px torso row loses 12 px a side
    mask[1, 100:900] = 255   # an 800 px arm-and-body row loses only the cap (4% of 1000 = 40 px)
    mask[2, 10:12] = 255     # a 2 px sliver keeps its pixels
    out = worker.slim_mask(mask, 0.12)
    assert np.flatnonzero(out[0]).tolist() == list(range(112, 188))
    assert np.flatnonzero(out[1])[[0, -1]].tolist() == [140, 859]
    assert np.flatnonzero(out[2]).tolist() == [10, 11]
    assert not out[3].any()


def test_slim_paints_the_room_over_the_freed_edge():
    original = np.zeros((60, 80, 3), np.uint8)
    original[:] = (0, 0, 200)            # the room is blue
    original[10:50, 30:50] = (200, 0, 0)  # the person is red
    person = np.zeros((60, 80), bool)
    person[10:50, 30:50] = True
    drawn = np.zeros((60, 80), bool)
    drawn[10:50, 34:46] = True
    frame = original.copy()
    out = worker.paint_room(frame, original, person & ~drawn, person)
    freed = out[20:40, 30:33]
    assert freed[..., 2].min() > 120 and freed[..., 0].max() < 80, "the freed edge shows the room, not the person"
    assert (out[25, 40] == (200, 0, 0)).all(), "the drawn person is untouched"
