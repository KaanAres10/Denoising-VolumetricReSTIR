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
