# History length out of NRD's DIFF FRAMES viewport, with both decoding traps fixed.
#
# Trap 1 (was in histlen.py): f == 0.75 is the shader's "history < 2 frames" marker, not a value.
#   It is drawn only on one phase of a static 4x4-block checkerboard, so the other phase is clean.
# Trap 2 (was in histlen2.py): f == 0 is NOT sky. f = 1 - hl/cap, so f == 0 is a FULL history. Calling
#   it sky and dropping it discarded the most-accumulated pixels -- which is why one camera produced
#   "sky" fractions of 0%, 65% and 27% across three runs. Sky is masked from linearZ instead.
#
# The viewport samples the full image with viewportUv, so the tile is just the frame downscaled and a
# resized depth buffer lines up with it.
import os, sys
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2, numpy as np

CAP = float(os.environ.get("HL_MAXACC", "30"))
RANGE = float(os.environ.get("HL_RANGE", "10000"))   # NRDPass kNRDDepthRange

def report(label, d):
    img = cv2.imread(os.path.join(d, "hv.NRDSurface.validation.%s.png" % FR), cv2.IMREAD_UNCHANGED)
    z = cv2.imread(os.path.join(d, "hv.GBufferRaster.linearZ.%s.exr" % FR), cv2.IMREAD_UNCHANGED)
    if img is None or z is None:
        print("%-24s MISSING" % label); return
    h, w = img.shape[:2]
    vs, vw = int(0.25 * h), int(0.25 * w)
    tile = img[2 * vs:3 * vs, 0:vw, :3].astype(np.float32)
    th, tw = tile.shape[:2]

    bar = tile[int(0.962 * th):int(0.995 * th)].mean(axis=0)
    lut_f = 1.0 - (np.arange(tw) + 0.5) / tw

    y0, y1 = int(0.12 * th), int(0.94 * th)
    body = tile[y0:y1]
    bh = body.shape[0]
    dd = ((body.reshape(-1, 1, 3) - bar.reshape(1, -1, 3)) ** 2).sum(axis=2)
    f = lut_f[dd.argmin(axis=1)].reshape(bh, tw)

    yy, xx = np.mgrid[0:bh, 0:tw]
    phase = ((((yy + y0 + 2 * vs) >> 2) + (xx >> 2)) & 1)

    zt = cv2.resize(np.nan_to_num(z[..., 0].astype(np.float32), posinf=1e9),
                    (tw, th), interpolation=cv2.INTER_NEAREST)[y0:y1]
    sky = np.abs(zt) >= RANGE

    # Pick the phase without the 0.75 spike; that is the one the marker never touched.
    spike = [float(np.mean(np.abs(f[(phase == p) & ~sky] - 0.75) < 0.012)) for p in (0, 1)]
    p = int(np.argmin(spike))
    sel = (phase == p) & ~sky
    hl = (1.0 - f[sel]) * CAP
    print("%-24s history mean %5.2f  median %5.2f  |  under 2 frames %5.1f%%  at full cap %5.1f%%  "
          "|  sky %4.1f%%  sentinel spike %.3f/%.3f"
          % (label, hl.mean(), np.median(hl), 100 * np.mean(hl < 2), 100 * np.mean(hl > CAP - 1),
             100 * sky.mean(), spike[0], spike[1]))

FR = "41"
for l, d in (("RELAX  orbit  d1", "hl_relax_d1"), ("REBLUR orbit  d1", "hl_reblur_d1"),
             ("RELAX  orbit  d35", "hl_relax_d35")):
    report(l, d)
print()
FR = "40"
for l, d in (("RELAX  static d1", "hl_static_relax_d1"), ("REBLUR static d1", "hl_static_reblur_d1"),
             ("RELAX  static d35", "hl_static_relax_d35")):
    report(l, d)
