# Is RELAX's frustum-basis round trip exact for the matrices we actually hand NRD?
#
# RELAX reconstructs prevWorldPos from the frustum basis and then transforms it BACK by
# gWorldToViewPrev to get the depth the plane test compares. If that round trip loses a scale, the
# test rejects everywhere -- which was the leading hypothesis. Settle it in float64 instead of an
# 8-bit diagnostic viewport, which has already saturated once.
import numpy as np

# Logged by NRD4_LOGMATRIX on bistro, 1280x720. Falcor rows.
P = np.array([[1.640625, 0, 0, 0],
              [0, 2.916667, 0, 0],
              [0, 0, -1.000001, -0.001],
              [0, 0, -1.0, 0]], dtype=np.float64)
V = np.array([[-0.902811, 0.000320, 0.430037, -10.067480],
              [ 0.140673, 0.945203, 0.294623,  -3.288873],
              [-0.406378, 0.326483, -0.853385, -16.051342],
              [ 0, 0, 0, 1.0]], dtype=np.float64)

R3 = V[:3, :3]
print("view rows orthonormal?  row norms   %s" % np.linalg.norm(R3, axis=1))
print("                        R R^T - I   max %.3e" % np.abs(R3 @ R3.T - np.eye(3)).max())
print("projection off-diagonal xy terms    max %.3e"
      % max(abs(P[0, 1]), abs(P[1, 0]), abs(P[0, 2]), abs(P[1, 2]), abs(P[2, 0]), abs(P[2, 1])))

# NRD makes the matrices camera-relative itself (InstanceImpl.cpp:398-408), so the basis it hands the
# shaders is the pure rotation, and row 2 is negated for the RH->LH conversion (:382-388).
Rlh = R3.copy(); Rlh[2, :] = -Rlh[2, :]

# Relax.cpp:66-71.  Symmetric projection => frustum.x + 0.5*frustum.z == 0 and likewise in y, so
# frustumForwardView is exactly (0,0,1) and frustumForward is the view forward axis in world space.
tanHalfFov = 1.0 / P[0, 0]
aspect = P[0, 0] / P[1, 1]
F = Rlh[2, :]                      # viewToWorld * (0,0,1,0)
Rt = Rlh[0, :] * tanHalfFov
U = Rlh[1, :] * tanHalfFov * aspect

# RELAX_Common.hlsli:91 reconstruction, then the transform back that the plane test does.
worst = 0.0
for clipx in np.linspace(-1, 1, 9):
    for clipy in np.linspace(-1, 1, 9):
        for viewZ in (0.5, 5.0, 21.8, 200.0):
            p = viewZ * (F + Rt * clipx - U * clipy)   # camera-relative world position
            z = Rlh[2, :] @ p                          # AffineTransform(...).z, translation is zero
            worst = max(worst, abs(z / viewZ - 1.0))
print("\nround trip  AffineTransform(gWorldToView, reconstruct(clipXY, viewZ)).z / viewZ")
print("  worst deviation from 1.0 over the frame and 0.5..200 m : %.3e" % worst)
# The matrices were logged to 6 decimals, so the view rotation is only orthonormal to ~5e-7. Anything
# at that level is the printing, not the maths -- the floor has to be the input precision, not zero.
floor = np.abs(R3 @ R3.T - np.eye(3)).max() * 10
print("  input precision floor (10x the logged orthonormality error)  : %.3e" % floor)
print("  -> %s" % ("EXACT to the precision of the inputs: the frustum basis is NOT the fault"
                   if worst < floor else "NOT exact, scale error = %.6f" % (1 + worst)))

# Why it is exact, so this does not have to be re-derived: the plane test only ever uses the .z of the
# round trip, and z = dot(row2, viewZ*(F + R*clipx - U*clipy)). F is row2 itself, while R and U are
# scalar multiples of row0 and row1, which are orthogonal to row2. So the clipXY terms vanish
# identically and z = viewZ for ANY fov, aspect or frame position. A wrong fov could not show up here.
print("\n  dot(row2,row0) = %.3e   dot(row2,row1) = %.3e   -> clipXY terms vanish identically"
      % (Rlh[2] @ Rlh[0], Rlh[2] @ Rlh[1]))
