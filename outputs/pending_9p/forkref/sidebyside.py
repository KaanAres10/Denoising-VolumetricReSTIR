"""Side-by-side video of two orbit captures, left | right, each labelled.
   sidebyside.py <left dir> <left label> <right dir> <right label> <out.mp4> [fps]

Frame names are not zero-padded (.30.png ... .329.png), so the frames are ordered numerically and handed to
ffmpeg as explicit lists (see outputs/encode.py). crf 16: the point is to show noise, which a thriftier encode
smooths away."""
import os, re, subprocess, sys

left, llabel, right, rlabel, out = sys.argv[1:6]
fps = int(sys.argv[6]) if len(sys.argv) > 6 else 30

def listing(d):
    d = os.path.abspath(d)  # ffmpeg resolves a concat list's relative paths against the list's own folder
    fs = [f for f in os.listdir(d) if f.endswith(".png")]
    fs.sort(key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    lst = os.path.join(d, "_frames.txt")
    with open(lst, "w") as fh:
        for f in fs:
            fh.write("file '%s'\n" % os.path.join(d, f).replace("\\", "/"))
    return lst, len(fs)

(ll, nl), (rl, nr) = listing(left), listing(right)
assert nl == nr and nl > 0, (nl, nr)
font = "C\\:/Windows/Fonts/arial.ttf"
label = lambda text: ("drawtext=fontfile='%s':text='%s':x=24:y=24:fontsize=40:fontcolor=white:"
                      "box=1:boxcolor=black@0.6:boxborderw=12" % (font, text))
graph = "[0:v]%s[l];[1:v]%s[r];[l][r]hstack=inputs=2[v]" % (label(llabel), label(rlabel))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-r", str(fps), "-i", ll,
                "-f", "concat", "-safe", "0", "-r", str(fps), "-i", rl,
                "-filter_complex", graph, "-map", "[v]",
                "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-r", str(fps), out],
               check=True)
print("%d frames -> %s (%.1f MB, %.1f s at %d fps)" % (nl, out, os.path.getsize(out) / 1e6, nl / float(fps), fps))
