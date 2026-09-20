"""Encode a captured PNG sequence to mp4 with ffmpeg.

Mogwai's frameCapture writes `<base>.<pass>.<output>.<frame>.png`, and capture_sequence.py
requests captures at strided frame numbers (STEP, 2*STEP, ...). Neither the naming nor the
stride can be addressed by an ffmpeg printf pattern, and a lexical sort would order .128.
before .32. So frames are discovered, sorted by their trailing integer, and handed to ffmpeg
as a concat list.
"""
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
    return sorted((Path(p) for p in paths), key=frame_index)


def build_ffmpeg_cmd(list_file, out_path, fps, ffmpeg="ffmpeg"):
    return [ffmpeg, "-y", "-r", str(fps), "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "18", "-vsync", "cfr", str(out_path)]


def encode(png_dir, out_path, fps=24, ffmpeg="ffmpeg", pattern="*.png"):
    """Encode png_dir into out_path. Raises RuntimeError rather than failing silently."""
    png_dir = Path(png_dir)
    frames = [p for p in png_dir.glob(pattern) if _TRAILING_INDEX.search(p.name)]
    if not frames:
        raise RuntimeError(f"no capture PNGs in {png_dir}; nothing to encode")
    frames = sort_frames(frames)

    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"ffmpeg not found on PATH (looked for {ffmpeg!r}); cannot encode video")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as lf:
        for p in frames:
            lf.write(f"file '{p.resolve().as_posix()}'\n")
            lf.write(f"duration {1.0 / fps:.6f}\n")
        lf.write(f"file '{frames[-1].resolve().as_posix()}'\n")   # concat needs the last repeated
        list_file = lf.name

    try:
        cmd = build_ffmpeg_cmd(list_file, out_path, fps, ffmpeg)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {r.returncode}):\n{r.stderr[-2000:]}")
    finally:
        Path(list_file).unlink(missing_ok=True)

    print(f"[encode] {len(frames)} frames -> {out_path}")
    return Path(out_path)
