"""Apply affine transformations to PDF page content streams."""

import pikepdf


def _get_mediabox(page):
    """Return [x0, y0, x1, y1] as floats, normalized."""
    mb = page.MediaBox if "/MediaBox" in page else [0, 0, 612, 792]
    coords = [float(x) for x in mb]
    if coords[0] > coords[2]:
        coords[0], coords[2] = coords[2], coords[0]
    if coords[1] > coords[3]:
        coords[1], coords[3] = coords[3], coords[1]
    return coords


def _visual_dimensions(page):
    """Return (x0, y0, w, h) in visual (post-rotation) space."""
    x0, y0, x1, y1 = _get_mediabox(page)
    w, h = x1 - x0, y1 - y0
    rotation = int(page.get("/Rotate", 0)) % 360
    if rotation in (90, 270):
        w, h = h, w
    return x0, y0, w, h


def _unrotated_dimensions(page):
    x0, y0, x1, y1 = _get_mediabox(page)
    return x0, y0, x1 - x0, y1 - y0


def _rotation_matrix(rotation, u_x0, u_y0, u_w, u_h):
    """
    Return (m_u_to_v, m_v_to_u) matrices.

    These matrices map between unrotated content space and visual space, 
    for a given /Rotate value.
    """
    cx, cy = u_x0 + u_w / 2, u_y0 + u_h / 2
    if rotation == 0:
        return pikepdf.Matrix(), pikepdf.Matrix()
    elif rotation == 90:
        # content is rotated 90 CW to get visual; inverse is 90 CCW
        m = (pikepdf.Matrix().translated(-cx, -cy)
             @ pikepdf.Matrix().rotated(-90)
             @ pikepdf.Matrix().translated(cx, cy))
        mi = (pikepdf.Matrix().translated(-cx, -cy)
              @ pikepdf.Matrix().rotated(90)
              @ pikepdf.Matrix().translated(cx, cy))
        return m, mi
    elif rotation == 180:
        m = (pikepdf.Matrix().translated(-cx, -cy)
             @ pikepdf.Matrix().rotated(-180)
             @ pikepdf.Matrix().translated(cx, cy))
        return m, m  # 180 is its own inverse
    elif rotation == 270:
        m = (pikepdf.Matrix().translated(-cx, -cy)
             @ pikepdf.Matrix().rotated(-270)
             @ pikepdf.Matrix().translated(cx, cy))
        mi = (pikepdf.Matrix().translated(-cx, -cy)
              @ pikepdf.Matrix().rotated(270)
              @ pikepdf.Matrix().translated(cx, cy))
        return m, mi
    return pikepdf.Matrix(), pikepdf.Matrix()


def _resolve_anchor(anchor, x0, y0, w, h):
    anchors = {
        "center":       (x0 + w/2, y0 + h/2),
        "top-left":     (x0,       y0 + h),
        "top":          (x0 + w/2, y0 + h),
        "top-right":    (x0 + w,   y0 + h),
        "left":         (x0,       y0 + h/2),
        "right":        (x0 + w,   y0 + h/2),
        "bottom-left":  (x0,       y0),
        "bottom":       (x0 + w/2, y0),
        "bottom-right": (x0 + w,   y0),
    }
    return anchors.get(anchor, (x0 + w/2, y0 + h/2))


def _build_visual_matrix(shift_x, shift_y, scale, spin_deg, anchor, v_x0, v_y0, v_w, v_h):
    """Build the combined transformation matrix in visual space."""
    m = pikepdf.Matrix()

    if scale != 1.0 or spin_deg != 0:
        ax, ay = _resolve_anchor(anchor, v_x0, v_y0, v_w, v_h)
        m = (m
             @ pikepdf.Matrix().translated(-ax, -ay)
             @ pikepdf.Matrix().scaled(scale, scale)
             @ pikepdf.Matrix().rotated(spin_deg)
             @ pikepdf.Matrix().translated(ax, ay))

    if shift_x != 0 or shift_y != 0:
        m = m @ pikepdf.Matrix().translated(shift_x, shift_y)

    return m


def _transform_point(matrix, x, y):
    a, b, c, d, e, f = [float(v) for v in matrix.as_array()]
    return (a*x + c*y + e, b*x + d*y + f)


def _transform_rect(matrix, rect):
    x0, y0, x1, y1 = [float(v) for v in rect]
    corners = [
        _transform_point(matrix, x0, y0),
        _transform_point(matrix, x1, y0),
        _transform_point(matrix, x0, y1),
        _transform_point(matrix, x1, y1),
    ]
    xs, ys = zip(*corners)
    return pikepdf.Array([min(xs), min(ys), max(xs), max(ys)])


def _transform_quadpoints(matrix, qp):
    pts = [float(v) for v in qp]
    result = []
    for i in range(0, len(pts), 2):
        nx, ny = _transform_point(matrix, pts[i], pts[i+1])
        result.extend([nx, ny])
    return pikepdf.Array(result)


def _update_annotations(page, matrix):
    if "/Annots" not in page:
        return
    for annot in page["/Annots"]:
        if "/QuadPoints" in annot:
            annot["/QuadPoints"] = _transform_quadpoints(matrix, annot["/QuadPoints"])
        if "/Rect" in annot:
            annot["/Rect"] = _transform_rect(matrix, annot["/Rect"])
        if "/AP" in annot:
            del annot["/AP"]


def apply_place(page, shift_x=0.0, shift_y=0.0, scale=1.0, spin_deg=0.0, anchor="center"):
    """Apply shift/scale/spin to a page's content stream and annotations.

    Correctly handle pages with a /Rotate entry.
    """
    rotation = int(page.get("/Rotate", 0)) % 360
    u_x0, u_y0, u_w, u_h = _unrotated_dimensions(page)
    v_x0, v_y0, v_w, v_h = _visual_dimensions(page)

    visual_matrix = _build_visual_matrix(
        shift_x, shift_y, scale, spin_deg, anchor,
        v_x0, v_y0, v_w, v_h
    )

    if visual_matrix == pikepdf.Matrix():
        return  # nothing to do

    m_u_to_v, m_v_to_u = _rotation_matrix(rotation, u_x0, u_y0, u_w, u_h)
    content_matrix = m_u_to_v @ visual_matrix @ m_v_to_u

    matrix_str = content_matrix.encode().decode("utf-8")
    page.contents_add(b"Q", prepend=False)
    page.contents_add(f"q {matrix_str} cm ".encode(), prepend=True)

    _update_annotations(page, visual_matrix)
