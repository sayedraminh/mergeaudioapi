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
