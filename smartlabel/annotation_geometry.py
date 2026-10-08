"""Pure image-coordinate geometry shared by OBB editing and ORI snapping."""
import math


FIELDS = ("bbox", "points", "obb", "orientation")


def envelope(points):
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def frame(corners):
    if len(corners) != 4:
        return None
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    ux, uy = corners[1][0] - corners[0][0], corners[1][1] - corners[0][1]
    vx, vy = corners[3][0] - corners[0][0], corners[3][1] - corners[0][1]
    w, h = math.hypot(ux, uy), math.hypot(vx, vy)
    if min(w, h) < 1e-6:
        return None
    return cx, cy, ux/w, uy/w, vx/h, vy/h, w, h


def contains(corners, x, y):
    # Convex OBB hit-test, not its (larger) axis-aligned envelope.
    cross = [(b[0]-a[0])*(y-a[1]) - (b[1]-a[1])*(x-a[0])
             for a, b in zip(corners, corners[1:] + corners[:1])]
    return bool(cross) and (min(cross) >= -1e-6 or max(cross) <= 1e-6)


def direction(bbox, corners, point, image_size, snap=True):
    oriented = frame(corners)
    if oriented:
        cx, cy, ux, uy, vx, vy, _, _ = oriented
    else:
        x, y, w, h = bbox
        cx, cy, ux, uy, vx, vy = x+w/2, y+h/2, 1, 0, 0, 1
    dx, dy = point[0]-cx, point[1]-cy
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return None
    if snap:
        axis = max(((ux, uy), (-ux, -uy), (vx, vy), (-vx, -vy)),
                   key=lambda axis: dx*axis[0] + dy*axis[1])
        dx, dy = length*axis[0], length*axis[1]
    # Clip the whole ray, never individual coordinates (would change its angle).
    fraction = 1.0
    for center, delta, limit in ((cx, dx, image_size[0]), (cy, dy, image_size[1])):
        if delta > 0:
            fraction = min(fraction, (limit-center)/delta)
        elif delta < 0:
            fraction = min(fraction, -center/delta)
    if fraction <= 1e-6:
        return None
    return [[cx, cy], [cx+dx*fraction, cy+dy*fraction]]


def all_points(snapshot):
    x, y, w, h = snapshot["bbox"]
    return [[x, y], [x+w, y+h]] + sum(
        (snapshot[name] for name in ("points", "obb", "orientation")), [])


def translate(snapshot, dx, dy, image_size):
    x, y, w, h = envelope(all_points(snapshot))
    dx = min(max(dx, -x), image_size[0]-x-w)
    dy = min(max(dy, -y), image_size[1]-y-h)
    result = {name: [[px+dx, py+dy] for px, py in snapshot[name]]
              for name in ("points", "obb", "orientation")}
    x, y, w, h = snapshot["bbox"]
    result["bbox"] = [x+dx, y+dy, w, h]
    return result


def edit_obb(snapshot, handle, start, point, image_size, snap_rotation=False):
    oriented = frame(snapshot["obb"])
    if oriented is None:
        return None
    cx, cy, ux, uy, vx, vy, w, h = oriented
    if handle == "rotate":
        if min(math.dist(start, (cx, cy)), math.dist(point, (cx, cy))) < 1e-6:
            return None
        angle = math.atan2(point[1]-cy, point[0]-cx) - math.atan2(start[1]-cy, start[0]-cx)
        if snap_rotation:
            initial = math.atan2(uy, ux)
            step = math.pi / 12
            angle = round((initial+angle)/step)*step - initial
        c, s = math.cos(angle), math.sin(angle)

        def transform(px, py):
            return [cx+(px-cx)*c-(py-cy)*s, cy+(px-cx)*s+(py-cy)*c]
    else:
        # Corner/edge edits in the box's own axes keep the opposite side fixed.
        left, right, top, bottom = -w/2, w/2, -h/2, h/2
        px = (point[0]-cx)*ux + (point[1]-cy)*uy
        py = (point[0]-cx)*vx + (point[1]-cy)*vy
        if "w" in handle:
            left = min(px, right-3)
        if "e" in handle:
            right = max(px, left+3)
        if "n" in handle:
            top = min(py, bottom-3)
        if "s" in handle:
            bottom = max(py, top+3)

        def transform(px, py):
            a = ((px-cx)*ux+(py-cy)*uy+w/2)/w
            b = ((px-cx)*vx+(py-cy)*vy+h/2)/h
            a, b = left+a*(right-left), top+b*(bottom-top)
            return [cx+a*ux+b*vx, cy+a*uy+b*vy]

    result = {name: [transform(*p) for p in snapshot[name]]
              for name in ("points", "obb", "orientation")}
    if any(not math.isfinite(p[i]) or not -1e-6 <= p[i] <= image_size[i]+1e-6
           for name in result for p in result[name] for i in (0, 1)):
        return None  # Never clip corners independently and destroy rectangularity.
    result["bbox"] = envelope(result["obb"])
    return result
