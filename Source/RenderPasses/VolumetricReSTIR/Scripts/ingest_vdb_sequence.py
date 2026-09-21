"""Ingest one dataset from datasets.json: VDBPrep -> gImportVDB, per frame.

  python ingest_vdb_sequence.py firePlume [--frames N] [--force]

Two stages, which is what the Falcor 4.x fork had. There is no bake: Falcor loads the .vbx
in-process via gvdb.dll (see the GVDB/OpenVDB section of the pass README), so the GVDBBake ->
.bin stage this pipeline used to run has been removed along with the claim that motivated it.

Resumable: a frame whose .vbx set is complete is skipped unless --force. gImportVDB writes into a
folder named after the input, so a killed import leaves a partial folder; vbx_complete() checks
every expected mip of both families rather than just the folder's existence.
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
# VDBPrep links Falcor's OpenVDB and MUST run from Falcor's runtime directory. The GVDBConverter
# folders ship the 2021 GVDB-era openvdb.dll, and Windows searches the executable's own directory
# first, so running it from there would load the wrong OpenVDB.
VDBPREP_DIR = REPO / "build" / "windows-vs2022" / "bin" / "Release"


def run(cmd, cwd, capture=False):
    print("   $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd),
                       capture_output=capture, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FAILED (exit {r.returncode}): {cmd[0]}")
    return r.stdout if capture else ""


def preflight(ds, repo_root):
    """Fail in seconds, not fifty minutes: every source frame and every executable, up front.

    The executable check is not paranoia -- VDBPrep.exe lives in build/windows-vs2022/bin/Release
    because it must resolve Falcor's OpenVDB, and nothing rebuilds it (Source/Tools/CMakeLists.txt
    does not list it), so a clean rebuild silently removes it.
    """
    missing = [str(vp.source_frame_path(ds, f, repo_root))
               for f in vp.frame_numbers(ds)
               if not vp.source_frame_path(ds, f, repo_root).exists()]
    if missing:
        raise SystemExit(f"FAILED: {len(missing)} source frame(s) missing, first: {missing[0]}")

    tools = [GIMPORT_DIR / "gImportVDB.exe"]
    if ds["grid_renames"]:
        tools.append(VDBPREP_DIR / "VDBPrep.exe")
    absent = [str(t) for t in tools if not t.exists()]
    if absent:
        raise SystemExit("FAILED: missing executable(s): " + ", ".join(absent)
                         + "\n  (VDBPrep is hand-built; see the header of Source/Tools/VDBPrep/VDBPrep.cpp)")


def ingest_frame(ds, frame, out_dir, force, runner=run):
    """Convert one .vdb to its .vbx set. Returns the mip0 extent if this frame was converted."""
    src = vp.source_frame_path(ds, frame, REPO)
    stem = src.stem
    vbx_dir = out_dir / stem

    if vp.vbx_complete(vbx_dir, stem, ds["num_mips"]) and not force:
        print(f"-- {stem}: already imported, skipping")
        return None

    if not src.exists():
        raise SystemExit(f"FAILED: source frame missing: {src}")

    work = src
    if ds["grid_renames"]:
        # The prepped copy keeps the SAME stem, in a scratch subdirectory. gImportVDB names its
        # output folder after the input file, and addGVDBVolumeSequence builds paths as
        # prefix + zero-padded frame -- so a "_prepped" suffix here would produce folders the
        # sequence loader cannot find.
        prep_dir = out_dir / "_prep"
        prep_dir.mkdir(exist_ok=True)
        work = prep_dir / f"{stem}.vdb"
        args = [f"{o}={n}" for o, n in ds["grid_renames"].items()]
        runner([VDBPREP_DIR / "VDBPrep.exe", src, work] + args, cwd=VDBPREP_DIR)

    # gImportVDB resolves BOTH its CUDA module (cuda_gvdb_module.ptx) and its output folder
    # relative to cwd, and those pull in opposite directions: run it from the output directory and
    # it cannot find the .ptx. So run it from its own directory and move the result.
    staged = GIMPORT_DIR / work.stem
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    stdout = runner([GIMPORT_DIR / "gImportVDB.exe", work, ds["num_mips"]],
                    cwd=GIMPORT_DIR, capture=True)
    if vbx_dir.exists():
        shutil.rmtree(vbx_dir, ignore_errors=True)
    shutil.move(str(staged), str(vbx_dir))

    if not vp.vbx_complete(vbx_dir, stem, ds["num_mips"]):
        raise SystemExit(f"FAILED: {vbx_dir.name} is missing expected .vbx files after import")
    if ds["has_emission"]:
        temp_vbx = vbx_dir / f"{stem}_temperature.vbx"
        if not temp_vbx.exists():
            raise SystemExit(f"FAILED: has_emission is set but {temp_vbx.name} was not produced")

    # The prepped .vdb is a throwaway intermediate; the .vbx set is what Falcor loads.
    if work != src:
        work.unlink(missing_ok=True)

    return vp.parse_import_res(stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--start", type=int, default=None,
                    help="override the manifest's start_frame (for importing a frame outside the window)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    ds = vp.get_dataset(a.dataset)
    if a.frames:
        ds = dict(ds, num_frames=a.frames)
    if a.start is not None:
        # Importing outside the manifest window is a one-off, so do not write the extent back:
        # "imported" must keep describing the window playback actually uses.
        ds = dict(ds, start_frame=a.start, playback_frames=None)
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

    extent = None
    for i, f in enumerate(frames, 1):
        print(f"[{i}/{len(frames)}] frame {f}")
        res = ingest_frame(ds, f, out_dir, a.force)
        # Record the frame playback derives placement from, not frames[0]: a different frame's
        # extent would quietly disagree with what the renderer uses.
        if f == vp.placement_frame(vp.playback_frame_numbers(ds)) and res:
            extent = res

    if extent and a.start is None:
        vp.write_imported_back(a.dataset, extent)
        print(f"[ingest] done. mip0 extent={extent} (written to datasets.json)")
    elif extent:
        print(f"[ingest] done. mip0 extent={extent} (one-off --start import; manifest unchanged)")
    else:
        print("[ingest] done. Nothing re-imported, so datasets.json is unchanged.")


if __name__ == "__main__":
    main()
