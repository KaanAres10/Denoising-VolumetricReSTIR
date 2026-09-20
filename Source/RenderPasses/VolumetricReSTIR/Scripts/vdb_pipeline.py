"""Pure logic for the VDB ingestion pipeline.

Everything derivable lives here so it can be unit tested without running gImportVDB,
GVDBBake or Mogwai. See docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md
"""
import json
import struct
from pathlib import Path
from typing import NamedTuple

MAGIC = 0x42445647          # "GVDB"
HEADER_BYTES = 24           # BakedHeader: magic, version, numMips, hasEmission, hasVelocity, maxDensity
INFO_BYTES = 11656          # sizeof(BakedInfo), see Source/Falcor/Scene/GVDB/GVDBBakeFormat.h
OFF_BMIN = HEADER_BYTES + 4092
OFF_BMAX = HEADER_BYTES + 4452
MIN_BIN_BYTES = HEADER_BYTES + INFO_BYTES


class BakedHeader(NamedTuple):
    num_mips: int
    has_emission: bool
    has_velocity: bool
    max_density: float
    extent: tuple


def read_baked_header(path) -> BakedHeader:
    """Parse the fixed-size head of a GVDBBake .bin. Raises ValueError if it is not one."""
    path = Path(path)
    with open(path, "rb") as f:
        head = f.read(MIN_BIN_BYTES)
    if len(head) < MIN_BIN_BYTES:
        raise ValueError(f"{path} is shorter than a baked header ({len(head)} bytes)")
    magic, version, num_mips, has_em, has_vel, max_density = struct.unpack_from("<IIiiif", head, 0)
    if magic != MAGIC:
        raise ValueError(f"{path} is not a GVDBBake file (magic {magic:#x})")
    if version != 1:
        raise ValueError(f"{path} has unsupported bake version {version}")
    bmin = struct.unpack_from("<3f", head, OFF_BMIN)
    bmax = struct.unpack_from("<3f", head, OFF_BMAX)
    extent = tuple(bmax[i] - bmin[i] for i in range(3))
    return BakedHeader(num_mips, bool(has_em), bool(has_vel), max_density, extent)


def is_bin_complete(path) -> bool:
    """True if path looks like a finished bake. Cheap guard against a truncated file."""
    try:
        read_baked_header(path)
        return True
    except (OSError, ValueError):
        return False


SCRIPTS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPTS_DIR / "datasets.json"
DERIVED_BYTES_PER_SOURCE_BYTE = 7.7   # measured: 41 MB source -> 317 MB .bin


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

    addGVDBVolumeSequence uploads every frame's GPU resources up front, so a window that bakes
    fine can still exceed VRAM at playback. Measured on an 8 GB RTX 5070 Laptop: dustShockwave
    at 677 MB/frame plays 16 frames and dies with DXGI_ERROR_DEVICE_REMOVED at 24, while
    firePlume at 334 MB/frame plays all 32. An optional "playback_frames" key caps playback
    without touching the ingest window, so the extra bakes stay on disk for a larger GPU.
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
    """Which frame's bake to derive placement from.

    V1 measured that GVDB rebases every frame's local origin to (0,0,0) while its extent grows,
    and addGVDBVolumeSequence takes a single worldTranslation, which the transform treats as the
    min corner. Anchoring on the first frame therefore makes a growing volume expand away from
    one corner; centring on the middle frame splits that error either side of centre.
    """
    return frames[len(frames) // 2]


def write_baked_back(name, header, path=None) -> None:
    """Record measured bake results under the dataset's "baked" key. Derived data: the spec makes
    the ingest script the only writer of this key, so nobody hand-maintains it."""
    p = Path(path) if path else MANIFEST_PATH
    manifest = load_manifest(p)
    manifest[name]["baked"] = {
        "extent": list(header.extent),
        "max_density": header.max_density,
        "has_emission": header.has_emission,
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
