"""Pure logic for the VDB ingestion pipeline.

Everything derivable lives here so it can be unit tested without running gImportVDB or
Mogwai. See docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md
"""
import json
import re
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPTS_DIR / "datasets.json"
DERIVED_BYTES_PER_SOURCE_BYTE = 7.8   # measured: 41 MB source .vdb -> 321 MB .vbx set


def load_manifest(path=None) -> dict:
    with open(Path(path) if path else MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_dataset(name, manifest=None) -> dict:
    m = manifest if manifest is not None else load_manifest()
    if name not in m:
        raise KeyError(f"unknown dataset {name!r}; manifest has: {', '.join(sorted(m))}")
    return m[name]


def frame_numbers(dataset) -> list:
    start = dataset["start_frame"]
    return list(range(start, start + dataset["num_frames"]))


def playback_frame_numbers(dataset) -> list:
    """Frames to PLAY, which can be fewer than the frames ingested.

    addGVDBVolumeSequence uploads every frame's GPU resources up front, so a window that imports
    fine can still exceed VRAM at playback. Measured on an 8 GB RTX 5070 Laptop: dustShockwave
    at 677 MB/frame plays 16 frames and dies with DXGI_ERROR_DEVICE_REMOVED at 24, while
    firePlume at 334 MB/frame plays all 32. An optional "playback_frames" key caps playback
    without touching the ingest window, so the extra frames stay on disk for a larger GPU.
    """
    frames = frame_numbers(dataset)
    cap = dataset.get("playback_frames")
    return frames[:cap] if cap else frames


def source_frame_path(dataset, frame, repo_root) -> Path:
    name = dataset["file_pattern"].format(frame=frame)
    return Path(repo_root) / dataset["source_dir"] / name


def estimate_window_bytes(dataset, repo_root) -> int:
    """Estimate derived cost by sampling real source frames in the window."""
    frames = frame_numbers(dataset)
    sample = [frames[0], frames[len(frames) // 2], frames[-1]]
    sizes = [source_frame_path(dataset, f, repo_root).stat().st_size
             for f in sample if source_frame_path(dataset, f, repo_root).exists()]
    if not sizes:
        return 0
    return int(sum(sizes) / len(sizes) * len(frames) * DERIVED_BYTES_PER_SOURCE_BYTE)


_RES_LINE = re.compile(r"^res:\s+(\d+)\s+(\d+)\s+(\d+)\s*$", re.MULTILINE)


def parse_import_res(stdout) -> tuple:
    """The mip0 voxel resolution from gImportVDB's stdout, or None if it printed none.

    With no bake there is no .bin header to read, so this is where placement metadata comes from.
    gImportVDB prints `res: X Y Z` once per mip as it converts; the first is mip0, and it equals
    the bake header's bmax-bmin (verified against dustShockwave frame 60: 801 796 140 both ways).
    """
    m = _RES_LINE.search(str(stdout))
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None


def expected_vbx_names(stem, num_mips) -> list:
    """Every .vbx gImportVDB writes for one frame: each mip in both the normal family and the
    conservative one ("c" suffix), which SceneGVDB loads into slots N and N+kNumMaxMips."""
    return [f"{stem}_mip{m}{suffix}.vbx" for m in range(num_mips) for suffix in ("", "c")]


def vbx_complete(vbx_dir, stem, num_mips) -> bool:
    """The integrity gate for a resumable import, replacing is_bin_complete.

    A frame counts as done only when every expected .vbx exists and is non-empty. An import killed
    part way leaves some of them absent, and without this a later run would skip the frame as
    finished -- the same trap the baked pipeline had.
    """
    vbx_dir = Path(vbx_dir)
    for name in expected_vbx_names(stem, num_mips):
        p = vbx_dir / name
        if not p.exists() or p.stat().st_size == 0:
            return False
    return True


def imported_extent(dataset) -> tuple:
    """The mip0 extent recorded by ingest. Raises if the dataset was never ingested."""
    imported = dataset.get("imported")
    if not imported or "extent" not in imported:
        raise KeyError(
            "dataset has no 'imported' metadata; run ingest_vdb_sequence.py for it first")
    return tuple(float(v) for v in imported["extent"])


REFERENCE_WORLD_SCALING = 0.013     # fire115, the tuned reference


def derive_placement(extent, centre, target_height):
    """Return (worldScaling, worldTranslation) to put a volume of `extent` voxels at `centre`.

    worldTranslation behaves as the volume's CENTRE, not its min corner. Reading
    computeVolumeExternalModelToWorldMatrix (SceneGVDB.cpp:219) alone suggests min corner -- it is
    T*R*S over local coords starting at the origin -- but GVDB's own per-volume xform already
    centres the grid, so the two compose to a centre. Measured at runtime: passing
    translation (0.0153, 1.68, 0.538) for an 801x796x140 volume at scale 0.0018844 makes Falcor
    log worldBB min(-0.735, 0.958, 0.360), i.e. translation minus half the scaled extent.

    Only the scale is derived here; the translation passes straight through.
    """
    scale = target_height / extent[1]
    return scale, tuple(float(c) for c in centre)


def derive_density_scale(density_scale_ref, scale, reference_scale=REFERENCE_WORLD_SCALING):
    """Optical thickness is densityScale/worldScaling (SceneGVDB.cpp:624), so a volume placed at a
    different world scale needs densityScale rescaled or it changes thickness."""
    return density_scale_ref * (scale / reference_scale)


def placement_frame(frames):
    """Which frame's import to derive placement from.

    V1 measured that GVDB rebases every frame's local origin to (0,0,0) while its extent grows,
    and addGVDBVolumeSequence takes a single worldTranslation, which the transform treats as the
    min corner. Anchoring on the first frame therefore makes a growing volume expand away from
    one corner; centring on the middle frame splits that error either side of centre.
    """
    return frames[len(frames) // 2]


def write_imported_back(name, extent, path=None) -> None:
    """Record the mip0 extent measured during import under the dataset's "imported" key.

    Derived data: ingest is the only writer, so nobody hand-maintains it. Replaces the old
    "baked" key, which was read out of a .bin header that no longer exists.
    """
    p = Path(path) if path else MANIFEST_PATH
    manifest = load_manifest(p)
    manifest[name]["imported"] = {"extent": [float(v) for v in extent]}
    # Write-then-replace: datasets.json is tracked, and truncating it in place means a Ctrl-C at
    # the end of a long ingest can leave it empty.
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    tmp.replace(p)
