# Encode each captured orbit to H.264 at the capture's own framerate and resolution.
#
# Frame filenames are NOT zero-padded (.30.png ... .329.png), so any glob-ordered read runs
# 100..329 before 30..99. That silently scrambles the video, and it is the same trap that corrupted
# the published instability table. Order numerically and hand ffmpeg an explicit list.
#
# crf 16 because the subject of these clips is temporal stability: a thriftier encode smooths exactly
# the artifact being judged, which would flatter the denoiser rather than show it.
import os, re, subprocess, sys

FPS = 30
for tag in ("relax", "reblur", "rr", "oidn", "optix"):
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orbit_%s" % tag)
    fs = [f for f in os.listdir(d) if f.endswith(".png")]
    fs.sort(key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    if not fs:
        print("%-7s no frames" % tag); continue
    lst = os.path.join(d, "_frames.txt")
    with open(lst, "w") as fh:
        for f in fs:
            fh.write("file '%s'\n" % os.path.join(d, f).replace("\\", "/"))
    out = os.path.join(os.path.dirname(d), "bistro_orbit_%s_1080p30.mp4" % tag)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-r", str(FPS), "-i", lst,
                    "-c:v", "libx264", "-crf", "16", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), out], check=True)
    mb = os.path.getsize(out) / 1e6
    print("%-7s %3d frames -> %s  (%.1f MB, %.1f s at %d fps)"
          % (tag, len(fs), os.path.basename(out), mb, len(fs) / float(FPS), FPS))
