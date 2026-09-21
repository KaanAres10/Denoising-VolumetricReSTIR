"""Encode a captured PNG sequence to mp4 with ffmpeg.

Mogwai's frameCapture writes `<base>.<pass>.<output>.<frame>.png`, which no ffmpeg printf pattern
can address, and which sorts wrongly lexically (`.128.` before `.32.`). Frames are therefore
discovered, ordered by their trailing integer, and staged into a temporary directory under
sequential names so the plain image2 demuxer can read them.

image2 rather than the concat demuxer, deliberately: concat emitted one extra trailing frame
(33 encoded for 32 captured, a visible hitch at the loop point) and its `file '<path>'` syntax
has no escaping, so a path containing a quote mis-parses. Staging is by hardlink, so nothing is
copied.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_TRAILING_INDEX = re.compile(r"\.(\d+)\.png$", re.IGNORECASE)


def frame_index(path) -> int:
    """The capture frame number embedded before the .png extension."""
    m = _TRAILING_INDEX.search(str(path))
    if not m:
        raise ValueError(f"cannot find a frame index in {path!r}")
    return int(m.group(1))


def sort_frames(paths) -> list:
    """Order captures numerically by trailing frame index, not lexically."""
    return sorted((Path(p) for p in paths), key=lambda p: frame_index(p.name))


def build_ffmpeg_cmd(pattern, out_path, fps, ffmpeg="ffmpeg"):
    return [ffmpeg, "-y", "-framerate", str(fps), "-start_number", "0",
            "-i", str(pattern), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "18", str(out_path)]


def _stage(frames, stage_dir):
    """Hardlink (or copy) frames into stage_dir as 000000.png, 000001.png, ..."""
    for i, src in enumerate(frames):
        dst = stage_dir / f"{i:06d}.png"
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


def encode(png_dir, out_path, fps=24, ffmpeg="ffmpeg", pattern="*.png"):
    """Encode png_dir into out_path. Raises RuntimeError rather than failing silently."""
    png_dir = Path(png_dir)
    frames = [p for p in png_dir.glob(pattern) if _TRAILING_INDEX.search(p.name)]
    if not frames:
        raise RuntimeError(f"no capture PNGs in {png_dir}; nothing to encode")
    frames = sort_frames(frames)

    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"ffmpeg not found on PATH (looked for {ffmpeg!r}); cannot encode video")

    with tempfile.TemporaryDirectory() as stage:
        stage_dir = Path(stage)
        _stage(frames, stage_dir)
        cmd = build_ffmpeg_cmd(stage_dir / "%06d.png", out_path, fps, ffmpeg)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {r.returncode}):\n{r.stderr[-2000:]}")

    # Exit 0 is not proof of output: ffmpeg can succeed having written nothing.
    if not Path(out_path).exists() or Path(out_path).stat().st_size == 0:
        raise RuntimeError(f"ffmpeg reported success but {out_path} is missing or empty")

    print(f"[encode] {len(frames)} frames -> {out_path}")
    return Path(out_path)
