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
