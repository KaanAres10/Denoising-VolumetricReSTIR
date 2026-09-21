"""Ingest one dataset from datasets.json: VDBPrep -> gImportVDB -> GVDBBake, per frame.

  python ingest_vdb_sequence.py firePlume [--frames N] [--keep-intermediates] [--force]

Resumable: a frame whose .bin already parses is skipped unless --force. The bake writes to
<frame>.bin.part and is renamed on success, so an interrupted run never leaves a .bin that a
later run would mistake for finished work.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vdb_pipeline as vp

REPO = Path(__file__).resolve().parents[4]
GIMPORT_DIR = REPO / "legacy" / "GVDBConverter"
BAKE_DIR = REPO / "Denoising-VolumetricReSTIR" / "GVDBConverter"
# VDBPrep links Falcor's OpenVDB and MUST run from Falcor's runtime directory. BAKE_DIR ships the
# 2021 GVDB-era openvdb.dll, and Windows searches the executable's own directory first, so running
# it from there would load the very OpenVDB whose ABI conflict the prebake design exists to avoid.
VDBPREP_DIR = REPO / "build" / "windows-vs2022" / "bin" / "Release"


def run(cmd, cwd):
    print("   $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd))
    if r.returncode != 0:
        raise SystemExit(f"FAILED (exit {r.returncode}): {cmd[0]}")


def preflight(ds, repo_root):
    """Fail in seconds, not fifty minutes. Checks every source frame in the window and the three
    executables before any baking starts.

    The executable check is not paranoia: VDBPrep.exe lives in build/windows-vs2022/bin/Release
    because it must resolve Falcor's OpenVDB, and nothing rebuilds it -- Source/Tools/CMakeLists.txt
    does not list it -- so a clean rebuild or `git clean -xfd` silently removes it.
    """
    missing = [str(vp.source_frame_path(ds, f, repo_root))
               for f in vp.frame_numbers(ds)
               if not vp.source_frame_path(ds, f, repo_root).exists()]
    if missing:
        raise SystemExit(f"FAILED: {len(missing)} source frame(s) missing, first: {missing[0]}")

    tools = [GIMPORT_DIR / "gImportVDB.exe", BAKE_DIR / "GVDBBake.exe"]
    if ds["grid_renames"]:
        tools.append(VDBPREP_DIR / "VDBPrep.exe")
    absent = [str(t) for t in tools if not t.exists()]
    if absent:
        raise SystemExit("FAILED: missing executable(s): " + ", ".join(absent)
                         + "\n  (VDBPrep is hand-built; see the header of Source/Tools/VDBPrep/VDBPrep.cpp)")


def ingest_frame(ds, frame, out_dir, keep, force, runner=run):
    stem = vp.source_frame_path(ds, frame, REPO).stem
    final_bin = out_dir / f"{stem}.bin"
    if final_bin.exists() and vp.is_bin_complete(final_bin) and not force:
        print(f"-- {stem}: already baked, skipping")
        return

    src = vp.source_frame_path(ds, frame, REPO)
    if not src.exists():
        raise SystemExit(f"FAILED: source frame missing: {src}")

    work = src
    if ds["grid_renames"]:
        work = out_dir / f"{stem}_prepped.vdb"
        args = [f"{o}={n}" for o, n in ds["grid_renames"].items()]
        runner([VDBPREP_DIR / "VDBPrep.exe", src, work] + args, cwd=VDBPREP_DIR)

    # gImportVDB resolves BOTH its CUDA module (cuda_gvdb_module.ptx) and its output folder
    # relative to cwd, and those two pull in opposite directions: run it from the output
    # directory and it cannot find the .ptx. So run it from its own directory and move the
    # result, which is the only arrangement that satisfies both.
    staged = GIMPORT_DIR / work.stem
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    runner([GIMPORT_DIR / "gImportVDB.exe", work, ds["num_mips"]], cwd=GIMPORT_DIR)
    vbx_dir = out_dir / work.stem
    if vbx_dir.exists():
        shutil.rmtree(vbx_dir, ignore_errors=True)
    shutil.move(str(staged), str(vbx_dir))

    if ds["has_emission"]:
        temp_vbx = vbx_dir / f"{work.stem}_temperature.vbx"
        if not temp_vbx.exists():
            raise SystemExit(f"FAILED: has_emission is set but {temp_vbx.name} was not produced")

    part = out_dir / f"{stem}.bin.part"
    runner([BAKE_DIR / "GVDBBake.exe", vbx_dir, ds["num_mips"],
            int(ds["has_velocity"]), int(ds["has_emission"]), part], cwd=BAKE_DIR)
    if not vp.is_bin_complete(part):
        part.unlink(missing_ok=True)
        raise SystemExit(
            f"FAILED: {part.name} is not a valid bake (truncated? GVDBBake exits 0 even when a "
            f"write fails, so check free disk space)")
    # The .vbx check above proves the grid reached the importer; this proves it reached the bake.
    # GVDBBake silently zeroes hasEmission when it cannot load the temperature slot, which would
    # otherwise surface only as a volume that renders black and reads like bad tuning.
    baked = vp.read_baked_header(part)
    if baked.has_emission != bool(ds["has_emission"]):
        part.unlink(missing_ok=True)
        raise SystemExit(f"FAILED: manifest has_emission={ds['has_emission']} but the bake "
                         f"reports has_emission={baked.has_emission}")
    part.replace(final_bin)

    if not keep:
        shutil.rmtree(vbx_dir, ignore_errors=True)
        if work != src:
            work.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--keep-intermediates", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    ds = vp.get_dataset(a.dataset)
    if a.frames:
        ds = dict(ds, num_frames=a.frames)
    frames = vp.frame_numbers(ds)

    out_dir = REPO / "VolumetricReSTIRData" / a.dataset
    out_dir.mkdir(parents=True, exist_ok=True)

    preflight(ds, REPO)

    need = vp.estimate_window_bytes(ds, REPO)
    free = shutil.disk_usage(out_dir).free
    print(f"[ingest] {a.dataset}: {len(frames)} frames, ~{need/2**30:.1f} GB needed, "
          f"{free/2**30:.1f} GB free")
    if need > free:
        raise SystemExit(f"FAILED: need ~{need/2**30:.1f} GB but only {free/2**30:.1f} GB free")

    for i, f in enumerate(frames, 1):
        print(f"[{i}/{len(frames)}] frame {f}")
        ingest_frame(ds, f, out_dir, a.keep_intermediates, a.force)

    # Record the frame playback actually derives placement from, not frames[0]: recording a
    # different frame's extent would quietly disagree with what the renderer uses.
    pframe = vp.placement_frame(vp.playback_frame_numbers(ds))
    h = vp.read_baked_header(out_dir / f"{vp.source_frame_path(ds, pframe, REPO).stem}.bin")
    vp.write_baked_back(a.dataset, h)
    print(f"[ingest] done. extent={h.extent} max_density={h.max_density:.4f} "
          f"has_emission={h.has_emission} (written to datasets.json)")


if __name__ == "__main__":
    main()
