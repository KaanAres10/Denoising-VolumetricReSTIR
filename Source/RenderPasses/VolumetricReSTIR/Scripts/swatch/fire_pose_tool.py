"""Pose the swatch fire by hand against the user's reference picture (2026-10-13): sliders for the volume's rotation
(SceneGVDB's worldRotation, x / y / z degrees), its scale (cm a voxel) and where its middle and bottom stand (the anchor,
cm); the flames grid projected through the shot's camera (the .blend's RenderManCam, as vr_graph.load_teapot_fire pins
it) and shown as Falcor shows it -- RenderMan's emission, density x 2^10 per cm in its deep red, through Blender's
Standard view -- without its absorption (it is thin: optical depth 0.1 on a median ray) or the pot in front of it.

    python fire_pose_tool.py

Left: the reference with the flame's outline (green: where its red passes 2). Right: the flame over the reference,
dimmed (t: the reference alone, to blink between them). s: save the pose to VolumetricReSTIRData/swatch/fire_pose.json
(swatch_fire.py's ROTATION, SCALE and ANCHOR); q or Esc: quit.
"""
import json
import os
import sys

import cv2
import numpy as np

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)
import make_volumes as mv  # noqa: E402
import swatch_fire as sf  # noqa: E402

SWATCH = os.path.join(mv.REPO, "VolumetricReSTIRData", "swatch")
SIZE = 512
CAMERA = (np.array([0.0, 39.5, 150.0]), np.array([0.0, 13.45, 2.28]), 100.0, 23.01)  # position, target, mm, frame mm
RED_PER_DENSITY = 2.0 ** 10  # radiance per unit density per cm (make_volumes.RMAN_FIRE_RGB, the PxrBlackBody exposure)


def reference_frame():
    """The reference picture in the shot's square frame (its page margins cropped)."""
    ref = cv2.imread(os.path.join(SWATCH, "reference_teapot_fire.png"))
    return cv2.resize(ref[10:625, 5:620], (SIZE, SIZE), interpolation=cv2.INTER_AREA)


def camera_basis():
    pos, tgt, mm, frame = CAMERA
    f = (tgt - pos) / np.linalg.norm(tgt - pos)
    r = np.cross(f, (0.0, 1.0, 0.0))
    r /= np.linalg.norm(r)
    return pos, f, r, np.cross(r, f), frame / 2 / mm


def matrix(rotation):
    cols = [sf.rotate(e, rotation) for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    return np.array(cols).T


def flame_radiance(points, values, scale, rotation, anchor):
    """Red radiance per pixel: 2^10 x the density integrated along each camera ray, each voxel splatted at its
    centre with its share of the ray length (scale) and of the pixel's area (voxel / pixel footprint)."""
    pos, f, r, u, tan = camera_basis()
    world = np.array(sf.translation(scale, rotation, anchor)) + scale * points @ matrix(rotation).T
    d = world - pos
    z = d @ f
    px = ((d @ r) / z / tan + 1) * SIZE / 2
    py = (1 - (d @ u) / z / tan) * SIZE / 2
    ok = (px >= 0) & (px < SIZE) & (py >= 0) & (py < SIZE) & (z > 0)
    pixel_cm = 2 * tan * np.median(z) / SIZE
    flat = py[ok].astype(int) * SIZE + px[ok].astype(int)
    img = np.bincount(flat, weights=values[ok] * scale * (scale / pixel_cm) ** 2, minlength=SIZE * SIZE).reshape(SIZE, SIZE)
    return RED_PER_DENSITY * cv2.GaussianBlur(img, (0, 0), max(0.5 * scale / pixel_cm, 0.5))


def standard_view(rgb):
    x = np.clip(rgb, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - 0.055)


def flame_bgr(red):
    rgb = np.stack([red, red * mv.RMAN_FIRE_RGB[1], red * mv.RMAN_FIRE_RGB[2]], -1)
    return (standard_view(rgb)[..., ::-1] * 255).astype(np.uint8)


def main():
    lo, flames = mv.read_swatch_flames()
    keep = flames > 1e-4
    points = np.argwhere(keep) + np.array(lo) + np.array(mv.FIRE_OFFSET) + 0.5  # the .vbx's voxel coordinates
    values = flames[keep].astype(np.float64)
    ref = reference_frame()
    win = "fire pose (s: save, t: blink, q: quit)"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    rx, ry, rz = sf.ROTATION
    bars = (("rot x +180", int(rx) + 180, 360), ("rot y +90", int(ry) + 90, 180), ("rot z", int(rz) % 360, 359),
            ("scale x1000", int(round(sf.SCALE * 1000)), 250),
            ("x mm +100", int(round(sf.ANCHOR[0] * 10)) + 100, 200), ("bottom mm", int(round(sf.ANCHOR[1] * 10)), 350),
            ("z mm +100", int(round(sf.ANCHOR[2] * 10)) + 100, 200))
    for name, value, top in bars:
        cv2.createTrackbar(name, win, value, top, lambda _: None)
    blink, last, frame = False, None, None
    while True:
        v = [cv2.getTrackbarPos(name, win) for name, _, _ in bars]
        rotation = (v[0] - 180.0, v[1] - 90.0, float(v[2]))
        scale = max(v[3], 20) / 1000.0
        anchor = ((v[4] - 100) / 10.0, v[5] / 10.0, (v[6] - 100) / 10.0)
        state = (rotation, scale, anchor, blink)
        if state != last:
            red = flame_radiance(points, values, scale, rotation, anchor)
            left = ref.copy()
            contours, _ = cv2.findContours((red > 2.0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(left, contours, -1, (0, 255, 0), 1)
            if blink:
                right = ref.copy()
            else:
                alpha = np.clip(red / 3.0, 0, 1)[..., None]
                right = (alpha * flame_bgr(red) + (1 - alpha) * 0.4 * ref).astype(np.uint8)
            frame = np.concatenate([left, right], 1)
            text = "rot (%.0f, %.0f, %.0f)  scale %.3f cm  anchor (%.1f, %.1f, %.1f) cm" % (*rotation, scale, *anchor)
            cv2.putText(frame, text, (10, SIZE - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
            cv2.putText(frame, text, (10, SIZE - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imshow(win, frame)
            last = state
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27) or cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key == ord("t"):
            blink = not blink
        if key == ord("s"):
            pose = {"rotation": list(rotation), "scale": scale, "anchor": list(anchor)}
            path = os.path.join(SWATCH, "fire_pose.json")
            with open(path, "w") as fh:
                json.dump(pose, fh, indent=1)
            cv2.imwrite(os.path.join(SWATCH, "fire_pose.png"), frame)
            print("saved", path, pose, flush=True)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
