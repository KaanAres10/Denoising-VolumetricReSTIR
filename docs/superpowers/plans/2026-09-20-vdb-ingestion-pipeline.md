# VDB Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make externally authored VDB sequences first-class in this project — ingested, baked, animated, emissive where appropriate, and rendered to video — proven on two CC0 EmberGen datasets.

**Architecture:** A `datasets.json` manifest is the single source of truth. A pure-Python module (`vdb_pipeline.py`) holds all derivable logic — baked-header parsing, placement and density derivation, frame naming — and is unit tested against real baked files already on disk. A thin CLI orchestrates the three executables per frame. One new minimal C++ tool renames a VDB grid so the fire dataset can carry a temperature channel.

**Tech Stack:** Python 3.14 (stdlib `unittest` only — no pytest in this repo), C++17 with Falcor's OpenVDB from `external/packman/deps`, the prebuilt `gImportVDB.exe` and `GVDBBake.exe`, Falcor 8.0 / Mogwai, ffmpeg 8.1.1.

**Spec:** `docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md`

## Global Constraints

- Frame budget: **32 frames per dataset**. Windows: firePlume `100-131`, dustShockwave `60-91`.
- `numMips = 4` for both datasets.
- `hasVelocity = False` for both datasets. Never synthesize a velocity field.
- Reference world scaling for density derivation: **`0.013`** (fire115). Reference density scale: **`0.1`**.
- Baked header layout: 24-byte `BakedHeader`, then an 11656-byte `BakedInfo`. `bmin` at file offset **4116**, `bmax` at **4476**. Magic `0x42445647`, version `1`.
- `gImportVDB` writes output relative to the **current working directory**, into a folder named after the input file. Always set cwd explicitly.
- No dataset or derived artefact may be tracked by git.
- Tests run with `python -m unittest`; do not add a pip dependency.
- Existing tools are built by hand with `cl`, not CMake (`Source/Tools/CMakeLists.txt` lists only FalcorTest, ImageCompare, RenderGraphEditor). `VDBPrep` follows that pattern.

## Review Focus

1. **A `.bin` left truncated by an interrupted bake is skipped as "already done."** The ingest is an hour-long resumable job, so this is the most likely failure in practice; a truncated file later loads as garbage. Covered in Task 6 by writing to `.bin.part` and renaming atomically on success.
2. **A source frame missing mid-window** should fail loudly naming the frame, not silently yield a short sequence. Covered in Task 6.
3. **`has_emission: true` but the rename matched no grid**, so no `_temperature.vbx` is produced and the volume renders black — indistinguishable from a bad emission tuning. Covered in Task 4 (VDBPrep exits non-zero if a rename matched nothing) and Task 6 (ingest asserts the temperature vbx exists before baking with `hasEmission=1`).
4. **Disk exhaustion mid-ingest** on a 22 GB job must fail with a clear message rather than leaving partial output. Covered in Task 6 by a preflight free-space check against the estimated window cost.
5. **ffmpeg missing or exiting non-zero** must not silently produce no video. Covered in Task 8.

---

### Task 1: Ignore the source data, and add the manifest

**Files:**
- Modify: `.gitignore`
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `datasets.json` with top-level keys `firePlume` and `dustShockwave`, each carrying `source_dir`, `file_pattern`, `start_frame`, `num_frames`, `num_mips`, `grid_renames`, `has_velocity`, `has_emission`, `medium`, `placement`, `provenance`, and an initially absent `baked`.

- [ ] **Step 1: Confirm the hazard is real**

Run: `git status --porcelain | grep -E "FirePlumeVDB|DustShockwaveVDB"`
Expected: two `??` lines. This is 23 GB of untracked data at the repo root.

- [ ] **Step 2: Add the ignore rules**

Append to `.gitignore`, next to the existing `/VolumetricReSTIRData/` rule:

```gitignore
# Source VDB sequences (JangaFX EmberGen, CC0). Multi-GB, kept locally only.
/FirePlumeVDB/
/DustShockwaveVDB/
```

- [ ] **Step 3: Verify they are now ignored**

Run: `git status --porcelain | grep -E "FirePlumeVDB|DustShockwaveVDB"`
Expected: no output.

- [ ] **Step 4: Create the manifest**

Create `Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json`:

```json
{
  "firePlume": {
    "source_dir": "FirePlumeVDB/fire_plume/fire_plume_VDB",
    "file_pattern": "firePlume_{frame:04d}.vdb",
    "start_frame": 100,
    "num_frames": 32,
    "num_mips": 4,
    "grid_renames": { "flames": "temperature" },
    "has_velocity": false,
    "has_emission": true,
    "medium": {
      "sigma_a": [6, 6, 6], "sigma_s": [14, 14, 14], "g": 0.0,
      "density_scale_ref": 0.1,
      "le_scale": 1.0, "temperature_cutoff": 0.05, "temperature_scale": 2800.0
    },
    "placement": { "centre": [0.77, 2.43, 0.67], "target_height": 1.5 },
    "provenance": {
      "source": "JangaFX EmberGen free VDB animations",
      "url": "https://jangafx.com/software/embergen/download/free-vdb-animations/",
      "licence": "CC0-1.0"
    }
  },
  "dustShockwave": {
    "source_dir": "DustShockwaveVDB/DustShockwave/DustShockwaveVDB",
    "file_pattern": "dustshockwave_{frame:04d}.vdb",
    "start_frame": 60,
    "num_frames": 32,
    "num_mips": 4,
    "grid_renames": {},
    "has_velocity": false,
    "has_emission": false,
    "medium": {
      "sigma_a": [4, 4, 4], "sigma_s": [16, 16, 16], "g": 0.0,
      "density_scale_ref": 0.1,
      "le_scale": 1.0, "temperature_cutoff": 0.0, "temperature_scale": 0.0
    },
    "placement": { "centre": [0.77, 2.43, 0.67], "target_height": 1.5 },
    "provenance": {
      "source": "JangaFX EmberGen free VDB animations",
      "url": "https://jangafx.com/software/embergen/download/free-vdb-animations/",
      "licence": "CC0-1.0"
    }
  }
}
```

- [ ] **Step 5: Verify it parses**

Run: `python -c "import json;d=json.load(open('Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json'));print(sorted(d), d['firePlume']['start_frame'], d['dustShockwave']['start_frame'])"`
Expected: `['dustShockwave', 'firePlume'] 100 60`

- [ ] **Step 6: Commit**

```bash
git add .gitignore Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json
git commit -m "Ignore the EmberGen source sequences and describe them in a manifest"
```

---

### Task 2: Baked-header reader

The `.bin` header carries everything needed to place a volume. Parsing it is pure logic and there
are three real baked files on disk to test against, so this is testable without running anything.

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py`
- Test: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py`

**Interfaces:**
- Consumes: `datasets.json` from Task 1.
- Produces:
  - `BakedHeader` — `NamedTuple(num_mips: int, has_emission: bool, has_velocity: bool, max_density: float, extent: tuple[float, float, float])`
  - `read_baked_header(path: str | Path) -> BakedHeader`
  - `is_bin_complete(path: str | Path) -> bool`
  - Constants `MAGIC = 0x42445647`, `HEADER_BYTES = 24`, `INFO_BYTES = 11656`, `OFF_BMIN = 4116`, `OFF_BMAX = 4476`

- [ ] **Step 1: Write the failing test**

Create `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py`:

```python
import sys, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
REPO = SCRIPTS.parents[3]
DATA = REPO / "VolumetricReSTIRData"

import vdb_pipeline as vp


class TestReadBakedHeader(unittest.TestCase):
    """Asserted against real baked files already in VolumetricReSTIRData."""

    def test_reads_fire115_which_has_velocity(self):
        h = vp.read_baked_header(DATA / "fire115" / "fire115.0100.bin")
        self.assertEqual(h.num_mips, 4)
        self.assertTrue(h.has_velocity)
        self.assertFalse(h.has_emission)
        self.assertAlmostEqual(h.max_density, 0.4590, places=3)
        self.assertEqual(h.extent, (119.0, 114.0, 103.0))

    def test_reads_bunny_cloud_which_has_seven_mips(self):
        h = vp.read_baked_header(DATA / "bunny_cloud.bin")
        self.assertEqual(h.num_mips, 7)
        self.assertFalse(h.has_velocity)
        self.assertAlmostEqual(h.max_density, 2.7923, places=3)
        self.assertEqual(h.extent, (577.0, 572.0, 438.0))

    def test_rejects_a_file_that_is_not_a_bake(self):
        with self.assertRaises(ValueError):
            vp.read_baked_header(SCRIPTS / "datasets.json")


class TestIsBinComplete(unittest.TestCase):
    def test_true_for_a_real_bake(self):
        self.assertTrue(vp.is_bin_complete(DATA / "bunny_cloud.bin"))

    def test_false_for_missing_file(self):
        self.assertFalse(vp.is_bin_complete(DATA / "does_not_exist.bin"))

    def test_false_for_truncated_file(self):
        import tempfile, os
        src = (DATA / "bunny_cloud.bin").read_bytes()[:5000]
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(src)
            name = f.name
        try:
            self.assertFalse(vp.is_bin_complete(name))
        finally:
            os.unlink(name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vdb_pipeline'`

- [ ] **Step 3: Write the minimal implementation**

Create `Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: 6 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py
git commit -m "Read GVDBBake headers from Python, tested against the existing bakes"
```

---

### Task 3: V1 — does GVDB rebase each frame to its own bounding box?

This is the spec's highest risk (R1) and a decision gate. The dust shockwave expands ~40x across
its sequence; if GVDB rebases every frame to its active bbox, a fixed transform will anchor it
instead of letting it expand, and the dust half of this plan changes shape. Ten minutes here
prevents an hour of wasted baking.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md` (append findings)

**Interfaces:**
- Consumes: `read_baked_header` from Task 2.
- Produces: a recorded go/no-go decision. No code.

- [ ] **Step 1: Convert dust frames 60 and 91 into the scratch area**

Run each from the converter directory so its output lands there, then move it aside:

```bash
SCRATCH="$TMPDIR/v1"; mkdir -p "$SCRATCH"
cp DustShockwaveVDB/DustShockwave/DustShockwaveVDB/dustshockwave_0060.vdb "$SCRATCH/"
cp DustShockwaveVDB/DustShockwave/DustShockwaveVDB/dustshockwave_0091.vdb "$SCRATCH/"
(cd legacy/GVDBConverter && ./gImportVDB.exe "$(cygpath -w $SCRATCH/dustshockwave_0060.vdb)" 4 && mv dustshockwave_0060 "$SCRATCH/")
(cd legacy/GVDBConverter && ./gImportVDB.exe "$(cygpath -w $SCRATCH/dustshockwave_0091.vdb)" 4 && mv dustshockwave_0091 "$SCRATCH/")
```

- [ ] **Step 2: Bake both**

```bash
(cd Denoising-VolumetricReSTIR/GVDBConverter && ./GVDBBake.exe "$(cygpath -w $SCRATCH/dustshockwave_0060)" 4 0 0 "$(cygpath -w $SCRATCH/dustshockwave_0060.bin)")
(cd Denoising-VolumetricReSTIR/GVDBConverter && ./GVDBBake.exe "$(cygpath -w $SCRATCH/dustshockwave_0091)" 4 0 0 "$(cygpath -w $SCRATCH/dustshockwave_0091.bin)")
```

- [ ] **Step 3: Compare the baked extents**

```bash
python -c "
import sys; sys.path.insert(0, 'Source/RenderPasses/VolumetricReSTIR/Scripts')
import vdb_pipeline as vp, os
s = os.environ['SCRATCH']
for n in ('dustshockwave_0060', 'dustshockwave_0091'):
    print(n, vp.read_baked_header(f'{s}/{n}.bin'))
"
```

Expected if the risk is dismissed: frame 91's `extent` is materially larger than frame 60's,
consistent with their source sizes (78 MB vs ~101 MB).
Expected if the risk is real: the two extents are equal or near-equal.

- [ ] **Step 4: Record the finding in the spec and decide**

Append a `## Verification results` section to the spec stating both extents verbatim and the
decision. If extents grow, write "R1 dismissed" and continue to Task 4 unchanged. If they do not,
write "R1 confirmed" and **stop** — Task 7 needs a per-frame transform and this plan must be
revised before any bulk ingest.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md
git commit -m "Record V1: whether GVDB rebases each animation frame to its own bbox"
```

---

### Task 4: VDBPrep — rename a grid inside a VDB

The fire dataset ships `density` + `flames`, and the loader skips a non-leading `flames` grid
(`legacy/gvdb-voxel-src/source/gvdb_library/src/gvdb_volume_gvdb.cpp:2458`). Renaming it to
`temperature` is what unlocks emission. No value remapping — the Kelvin conversion is a runtime
affine transform in `VolumeBase.slang:278`.

**Files:**
- Create: `Source/Tools/VDBPrep/VDBPrep.cpp`

**Interfaces:**
- Consumes: nothing.
- Produces: `VDBPrep.exe <in.vdb> <out.vdb> <old>=<new> [<old>=<new> ...]`. Exit 0 on success;
  exit 2 if any requested rename matched no grid in the file (Review Focus item 3).

- [ ] **Step 1: Write the tool**

Create `Source/Tools/VDBPrep/VDBPrep.cpp`:

```cpp
/***************************************************************************
 # Volumetric ReSTIR port -- standalone VDB grid renamer.
 #
 # EmberGen exports a combustion field named "flames", which GVDB's loader skips unless it is
 # the first grid in the file. Renaming it to "temperature" routes it into the emission slot.
 # Values are NOT modified: the 0-1 -> Kelvin mapping is a runtime affine transform applied in
 # VolumeBase.slang (temp = min(6400, (v - temperatureCutOff) * temperatureScale)), so fire
 # colour stays tunable without re-baking.
 #
 # Runs as its own process, so Falcor's OpenVDB and the gvdb.dll OpenVDB never meet.
 #
 # Build (from the repo root):
 #   cl /std:c++17 /EHsc /MD /I external\packman\deps\include
 #      Source\Tools\VDBPrep\VDBPrep.cpp external\packman\deps\lib\openvdb.lib
 #      /Fe:Denoising-VolumetricReSTIR\GVDBConverter\VDBPrep.exe
 #
 # Usage: VDBPrep <in.vdb> <out.vdb> <oldName>=<newName> [...]
 **************************************************************************/
#include <openvdb/openvdb.h>

#include <cstdio>
#include <cstring>
#include <map>
#include <string>

int main(int argc, char** argv)
{
    if (argc < 4)
    {
        printf("Usage: VDBPrep <in.vdb> <out.vdb> <oldName>=<newName> [...]\n");
        return 1;
    }

    std::map<std::string, std::string> renames;
    for (int i = 3; i < argc; i++)
    {
        const char* eq = strchr(argv[i], '=');
        if (!eq) { printf("Bad rename '%s', expected old=new\n", argv[i]); return 1; }
        renames[std::string(argv[i], eq)] = std::string(eq + 1);
    }

    openvdb::initialize();

    openvdb::io::File in(argv[1]);
    in.open();
    openvdb::GridPtrVecPtr grids = in.getGrids();
    in.close();

    std::map<std::string, int> hits;
    for (auto& g : *grids)
    {
        auto it = renames.find(g->getName());
        if (it != renames.end())
        {
            printf("  renaming '%s' -> '%s'\n", it->first.c_str(), it->second.c_str());
            g->setName(it->second);
            hits[it->first]++;
        }
    }

    // A rename that matched nothing would silently produce a volume with no temperature grid,
    // which renders black and looks like a tuning problem. Fail loudly instead.
    int missed = 0;
    for (auto& r : renames)
        if (hits[r.first] == 0) { printf("ERROR: no grid named '%s' in %s\n", r.first.c_str(), argv[1]); missed++; }
    if (missed) return 2;

    openvdb::io::File out(argv[2]);
    out.write(*grids);
    out.close();
    printf("Wrote %s\n", argv[2]);
    return 0;
}
```

- [ ] **Step 2: Build it**

Run from a Visual Studio x64 developer prompt at the repo root:

```
cl /std:c++17 /EHsc /MD /I external\packman\deps\include Source\Tools\VDBPrep\VDBPrep.cpp external\packman\deps\lib\openvdb.lib /Fe:Denoising-VolumetricReSTIR\GVDBConverter\VDBPrep.exe
```

Expected: `VDBPrep.exe` appears next to `GVDBBake.exe`, where `openvdb.dll` is already resolvable.

- [ ] **Step 3: Verify the success path on a real frame**

```bash
cp FirePlumeVDB/fire_plume/fire_plume_VDB/firePlume_0100.vdb "$SCRATCH/"
(cd Denoising-VolumetricReSTIR/GVDBConverter && ./VDBPrep.exe "$(cygpath -w $SCRATCH/firePlume_0100.vdb)" "$(cygpath -w $SCRATCH/firePlume_0100_prepped.vdb)" flames=temperature)
```

Expected: prints `renaming 'flames' -> 'temperature'`, writes the file, exit 0.

- [ ] **Step 4: Verify the failure path (Review Focus item 3)**

```bash
(cd Denoising-VolumetricReSTIR/GVDBConverter && ./VDBPrep.exe "$(cygpath -w $SCRATCH/firePlume_0100.vdb)" "$(cygpath -w $SCRATCH/nope.vdb)" nosuchgrid=temperature); echo "exit=$?"
```

Expected: `ERROR: no grid named 'nosuchgrid'` and `exit=2`. No output file written.

- [ ] **Step 5: Commit**

```bash
git add Source/Tools/VDBPrep/VDBPrep.cpp
git commit -m "Add VDBPrep, a standalone VDB grid renamer for the emission channel"
```

---

### Task 5: V2 — prove emission survives the rename

The rename route was derived by reading the loader, not by observing it. Prove it on one frame
before committing to a 13 GB bake.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md` (append findings)

**Interfaces:**
- Consumes: `VDBPrep.exe` from Task 4.
- Produces: a recorded go/no-go. No code.

- [ ] **Step 1: Import the prepped frame**

```bash
(cd legacy/GVDBConverter && ./gImportVDB.exe "$(cygpath -w $SCRATCH/firePlume_0100_prepped.vdb)" 4 && mv firePlume_0100_prepped "$SCRATCH/")
ls "$SCRATCH/firePlume_0100_prepped/" | grep temperature
```

Expected: a `firePlume_0100_prepped_temperature.vbx` exists. If it does not, the rename did not
route into the emission slot and R2 is confirmed — stop and revise.

- [ ] **Step 2: Bake with emission enabled**

```bash
(cd Denoising-VolumetricReSTIR/GVDBConverter && ./GVDBBake.exe "$(cygpath -w $SCRATCH/firePlume_0100_prepped)" 4 0 1 "$(cygpath -w $SCRATCH/firePlume_0100_prepped.bin)")
python -c "
import sys; sys.path.insert(0,'Source/RenderPasses/VolumetricReSTIR/Scripts')
import vdb_pipeline as vp, os
print(vp.read_baked_header(os.environ['SCRATCH'] + '/firePlume_0100_prepped.bin'))
"
```

Expected: `has_emission=True` in the parsed header.

- [ ] **Step 3: Render it and look**

Reuse the probe script pattern from the spike: load `default.obj`, set the `hansaplatz_8k.hdr`
env map, `addGVDBVolume(..., hasEmission=True, LeScale=1.0, temperatureCutoff=0.05,
temperatureScale=2800.0)` with `worldScaling = 1.5/679` and `densityScale = 0.1 * (worldScaling/0.013)`,
camera at `(1.977354, 2.411630, 2.242076)` targeting `(1.366226, 2.220231, 1.474033)`, capture at
frame 128.

Expected: the plume shows orange-yellow emission in its core rather than reading as grey smoke.

- [ ] **Step 4: Record the finding and decide**

Append to the spec's `## Verification results`: whether `_temperature.vbx` was produced, whether
`has_emission` round-tripped, and whether the render is visibly emissive. Write "R2 dismissed" or
"R2 confirmed" and, if confirmed, stop.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md
git commit -m "Record V2: emission through a renamed flames grid"
```

---

### Task 6: Ingest orchestrator

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py`
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py`
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py`

**Interfaces:**
- Consumes: `read_baked_header`, `is_bin_complete` from Task 2; `VDBPrep.exe` from Task 4.
- Produces:
  - `load_manifest(path=None) -> dict`
  - `get_dataset(name, manifest=None) -> dict` — raises `KeyError` naming valid datasets if absent
  - `frame_numbers(dataset) -> list[int]`
  - `source_frame_path(dataset, frame, repo_root) -> Path`
  - `estimate_window_bytes(dataset, repo_root) -> int`
  - CLI: `python ingest_vdb_sequence.py <dataset> [--frames N] [--keep-intermediates] [--force]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vdb_pipeline.py`:

```python
class TestManifest(unittest.TestCase):
    def test_loads_both_datasets(self):
        m = vp.load_manifest()
        self.assertEqual(sorted(m), ["dustShockwave", "firePlume"])

    def test_unknown_dataset_names_the_valid_ones(self):
        with self.assertRaises(KeyError) as ctx:
            vp.get_dataset("nope")
        self.assertIn("firePlume", str(ctx.exception))

    def test_frame_numbers_span_the_window(self):
        ds = vp.get_dataset("firePlume")
        frames = vp.frame_numbers(ds)
        self.assertEqual(len(frames), 32)
        self.assertEqual((frames[0], frames[-1]), (100, 131))

    def test_source_frame_path_applies_the_pattern(self):
        ds = vp.get_dataset("firePlume")
        p = vp.source_frame_path(ds, 125, REPO)
        self.assertEqual(p.name, "firePlume_0125.vdb")
        self.assertTrue(p.exists(), "real source frame should be on disk")

    def test_missing_source_frame_is_detectable(self):
        ds = vp.get_dataset("firePlume")
        self.assertFalse(vp.source_frame_path(ds, 9999, REPO).exists())

    def test_estimate_window_bytes_is_positive_and_scales(self):
        ds = vp.get_dataset("dustShockwave")
        self.assertGreater(vp.estimate_window_bytes(ds, REPO), 0)

    def test_write_baked_back_records_measured_values(self):
        """The ingest script is the only writer of "baked"; never hand-maintained."""
        import json, shutil, tempfile
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "datasets.json"
            shutil.copy(vp.MANIFEST_PATH, copy)
            h = vp.BakedHeader(4, True, False, 0.719238, (202.0, 679.0, 456.0))
            vp.write_baked_back("firePlume", h, path=copy)
            written = json.load(open(copy))["firePlume"]["baked"]
            self.assertEqual(written["extent"], [202.0, 679.0, 456.0])
            self.assertAlmostEqual(written["max_density"], 0.719238, places=6)
            self.assertTrue(written["has_emission"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: FAIL — `AttributeError: module 'vdb_pipeline' has no attribute 'load_manifest'`

- [ ] **Step 3: Implement the manifest helpers**

Append to `vdb_pipeline.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: 13 tests, all PASS.

- [ ] **Step 5: Write the orchestrator CLI**

Create `Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py`:

```python
"""Ingest one dataset from datasets.json: VDBPrep -> gImportVDB -> GVDBBake, per frame.

  python ingest_vdb_sequence.py firePlume [--frames N] [--keep-intermediates] [--force]

Resumable: a frame whose .bin already parses is skipped unless --force. The bake writes to
<frame>.bin.part and is renamed on success, so an interrupted run never leaves a .bin that a
later run would mistake for finished work.
"""
import argparse, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vdb_pipeline as vp

REPO = Path(__file__).resolve().parents[4]
GIMPORT_DIR = REPO / "legacy" / "GVDBConverter"
BAKE_DIR = REPO / "Denoising-VolumetricReSTIR" / "GVDBConverter"


def run(cmd, cwd):
    print("   $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd))
    if r.returncode != 0:
        raise SystemExit(f"FAILED (exit {r.returncode}): {cmd[0]}")


def ingest_frame(ds, frame, out_dir, keep, force):
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
        run([BAKE_DIR / "VDBPrep.exe", src, work] + args, cwd=BAKE_DIR)

    # gImportVDB writes into a folder named after the input, relative to cwd.
    run([GIMPORT_DIR / "gImportVDB.exe", work, ds["num_mips"]], cwd=out_dir)
    vbx_dir = out_dir / work.stem

    if ds["has_emission"]:
        temp_vbx = vbx_dir / f"{work.stem}_temperature.vbx"
        if not temp_vbx.exists():
            raise SystemExit(f"FAILED: has_emission is set but {temp_vbx.name} was not produced")

    part = out_dir / f"{stem}.bin.part"
    run([BAKE_DIR / "GVDBBake.exe", vbx_dir, ds["num_mips"],
         int(ds["has_velocity"]), int(ds["has_emission"]), part], cwd=BAKE_DIR)
    if not vp.is_bin_complete(part):
        raise SystemExit(f"FAILED: {part.name} is not a valid bake")
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

    need = vp.estimate_window_bytes(ds, REPO)
    free = shutil.disk_usage(out_dir).free
    print(f"[ingest] {a.dataset}: {len(frames)} frames, ~{need/2**30:.1f} GB needed, "
          f"{free/2**30:.1f} GB free")
    if need > free:
        raise SystemExit(f"FAILED: need ~{need/2**30:.1f} GB but only {free/2**30:.1f} GB free")

    for i, f in enumerate(frames, 1):
        print(f"[{i}/{len(frames)}] frame {f}")
        ingest_frame(ds, f, out_dir, a.keep_intermediates, a.force)

    first = out_dir / f"{vp.source_frame_path(ds, frames[0], REPO).stem}.bin"
    h = vp.read_baked_header(first)
    vp.write_baked_back(a.dataset, h)
    print(f"[ingest] done. extent={h.extent} max_density={h.max_density:.4f} "
          f"has_emission={h.has_emission} (written to datasets.json)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Smoke test on a two-frame window**

Run: `python Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py dustShockwave --frames 2`
Expected: preflight line prints the estimate and free space; two frames bake; `.vbx` folders are
gone; two `.bin` files remain; final line prints extent and max density.

- [ ] **Step 7: Verify resume is idempotent**

Run the same command again.
Expected: both frames print `already baked, skipping` and nothing is re-baked.

- [ ] **Step 8: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py
git commit -m "Add a resumable per-frame VDB ingest driven by the manifest"
```

---

### Task 7: Placement derivation and the animated run script

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py`
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py`
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/run_volume_dataset.py`

> **Deviation from the spec, deliberate:** the spec named `run_firePlume.py` and
> `run_dustShockwave.py`. One manifest-driven script selected by `VR_DATASET` is DRY and serves
> the same success criterion; two near-identical scripts would drift.

**Interfaces:**
- Consumes: `read_baked_header`, `get_dataset` from earlier tasks.
- Produces:
  - `derive_placement(extent, centre, target_height) -> (scale: float, translation: tuple)`
  - `derive_density_scale(density_scale_ref, scale, reference_scale=0.013) -> float`
  - `VR_DATASET=<name> Mogwai.exe --script run_volume_dataset.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vdb_pipeline.py`:

```python
class TestPlacement(unittest.TestCase):
    def test_reproduces_the_fire115_transform(self):
        """The known-good reference: extent 119x114x103 at scale 0.013 sits at y=1.686."""
        extent = (119.0, 114.0, 103.0)
        scale, trans = vp.derive_placement(extent, (0.77, 2.43, 0.67), 114.0 * 0.013)
        self.assertAlmostEqual(scale, 0.013, places=6)
        self.assertAlmostEqual(trans[1], 1.686, places=2)
        self.assertAlmostEqual(trans[0], 0.0, places=2)
        self.assertAlmostEqual(trans[2], 0.0, places=2)

    def test_scale_sets_the_target_height(self):
        scale, _ = vp.derive_placement((202.0, 679.0, 456.0), (0, 0, 0), 1.5)
        self.assertAlmostEqual(679.0 * scale, 1.5, places=6)

    def test_density_scale_preserves_reference_thickness(self):
        """densityScale/worldScaling is what the shader uses, so the ratio must be held."""
        self.assertAlmostEqual(vp.derive_density_scale(0.1, 0.013), 0.1, places=6)
        self.assertAlmostEqual(vp.derive_density_scale(0.1, 1.5 / 679.0), 0.017, places=3)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: FAIL — `AttributeError: module 'vdb_pipeline' has no attribute 'derive_placement'`

- [ ] **Step 3: Implement the derivation**

Append to `vdb_pipeline.py`:

```python
REFERENCE_WORLD_SCALING = 0.013     # fire115, the tuned reference


def derive_placement(extent, centre, target_height):
    """worldTranslation is the MIN CORNER: the matrix is T*R*S over local coords from the origin
    (SceneGVDB.cpp:219). So centring means subtracting half the scaled extent."""
    scale = target_height / extent[1]
    translation = tuple(centre[i] - extent[i] * scale * 0.5 for i in range(3))
    return scale, translation


def derive_density_scale(density_scale_ref, scale, reference_scale=REFERENCE_WORLD_SCALING):
    """Optical thickness is densityScale/worldScaling (SceneGVDB.cpp:624), so a volume placed at a
    different world scale needs densityScale rescaled or it changes thickness."""
    return density_scale_ref * (scale / reference_scale)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: 16 tests, all PASS.

- [ ] **Step 5: Write the run script**

Create `Source/RenderPasses/VolumetricReSTIR/Scripts/run_volume_dataset.py`:

```python
"""Animated playback of an ingested dataset.

  VR_DATASET=firePlume Mogwai.exe --script run_volume_dataset.py

Transform and density come from the baked header, not from hand-tuned constants.
"""
import os, sys
from pathlib import Path
from falcor import *

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import vdb_pipeline as vp

REPO = SCRIPTS.parents[3]
DATA_DIR = REPO / "VolumetricReSTIRData"
NAME = os.environ.get("VR_DATASET", "firePlume")

ds = vp.get_dataset(NAME)
# VR_NUM_FRAMES lets a partially ingested window be played back without editing the manifest.
if os.environ.get("VR_NUM_FRAMES"):
    ds = dict(ds, num_frames=int(os.environ["VR_NUM_FRAMES"]))
frames = vp.frame_numbers(ds)
out_dir = DATA_DIR / NAME
prefix = ds["file_pattern"].split("{")[0]

header = vp.read_baked_header(out_dir / f"{prefix}{frames[0]:04d}.bin")
scale, trans = vp.derive_placement(header.extent, ds["placement"]["centre"],
                                   ds["placement"]["target_height"])
density = vp.derive_density_scale(ds["medium"]["density_scale_ref"], scale)
print(f"[{NAME}] extent={header.extent} scale={scale:.6g} density={density:.6g} "
      f"emission={header.has_emission} frames={len(frames)}")

m.loadScene(str(DATA_DIR / "default.obj"))
m.scene.setEnvMap(str(DATA_DIR / "hansaplatz_8k.hdr"))

med = ds["medium"]
m.scene.addGVDBVolumeSequence(
    sigma_a=float3(*med["sigma_a"]), sigma_s=float3(*med["sigma_s"]), g=med["g"],
    dataFilePrefix=str(out_dir / prefix), numberFixedLength=4,
    startFrame=frames[0], numFrames=len(frames), numMips=ds["num_mips"],
    densityScale=density, hasVelocity=ds["has_velocity"], hasEmission=ds["has_emission"],
    LeScale=med["le_scale"], temperatureCutoff=med["temperature_cutoff"],
    temperatureScale=med["temperature_scale"],
    worldTranslation=float3(*trans), worldRotation=float3(0, 0, 0), worldScaling=scale)

m.scene.camera.position = float3(1.977354, 2.411630, 2.242076)
m.scene.camera.target = float3(1.366226, 2.220231, 1.474033)
m.scene.camera.up = float3(0.0, 1.0, 0.0)


def render_graph():
    g = RenderGraph("Volume dataset " + NAME)
    vr = createPass("VolumetricReSTIR", {'mParams': {
        'mEnableTemporalReuse': True, 'mEnableSpatialReuse': True,
        'mUseEnvironmentLights': True, 'mUseEmissiveLights': False}})
    g.addPass(vr, "VolumetricReSTIR")
    tm = createPass("ToneMapper", {'autoExposure': False, 'exposureCompensation': 0.0})
    g.addPass(tm, "ToneMapper")
    g.addEdge("VolumetricReSTIR.accumulated_color", "ToneMapper.src")
    g.markOutput("ToneMapper.dst")
    g.markOutput("VolumetricReSTIR.mvec")
    return g


m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
```

- [ ] **Step 6: Verify playback on the two frames ingested in Task 6**

Run: `VR_DATASET=dustShockwave VR_NUM_FRAMES=2 Mogwai.exe --script run_volume_dataset.py`
Expected: the diagnostic line prints `extent=(...)` with a plausible voxel extent, a scale near
`1.5 / extent.y`, and `frames=2`; the volume is visible, framed by the camera, and neither a
near-opaque block nor invisible. A `.bin`-not-found error here means Task 6 was run with a
different window than `VR_NUM_FRAMES` selects.

- [ ] **Step 7: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/vdb_pipeline.py Source/RenderPasses/VolumetricReSTIR/Scripts/run_volume_dataset.py Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py
git commit -m "Derive volume placement and density from the bake, and play datasets back"
```

---

### Task 8: Video capture

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/capture_sequence.py`
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/encode_video.py`
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py`

**Interfaces:**
- Consumes: `run_volume_dataset.py` conventions from Task 7.
- Produces:
  - `encode_video.build_ffmpeg_cmd(pattern, out_path, fps) -> list[str]`
  - `encode_video.encode(png_dir, out_path, fps) -> Path` — raises `RuntimeError` if ffmpeg is
    missing or exits non-zero (Review Focus item 5)
  - `VR_DATASET=<name> VR_STEP_FRAMES=<n> Mogwai.exe --script capture_sequence.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vdb_pipeline.py`:

```python
class TestEncodeVideo(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import encode_video
        self.ev = encode_video

    def test_command_uses_the_pattern_and_fps(self):
        cmd = self.ev.build_ffmpeg_cmd("shot.%04d.png", "out.mp4", 24)
        self.assertIn("shot.%04d.png", cmd)
        self.assertIn("24", cmd)
        self.assertEqual(cmd[-1], "out.mp4")

    def test_missing_ffmpeg_raises_rather_than_silently_doing_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                self.ev.encode(d, Path(d) / "out.mp4", 24, ffmpeg="definitely_not_ffmpeg")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'encode_video'`

- [ ] **Step 3: Implement the encoder**

Create `Source/RenderPasses/VolumetricReSTIR/Scripts/encode_video.py`:

```python
"""Encode a captured PNG sequence to mp4 with ffmpeg."""
import shutil, subprocess
from pathlib import Path


def build_ffmpeg_cmd(pattern, out_path, fps, ffmpeg="ffmpeg"):
    return [ffmpeg, "-y", "-framerate", str(fps), "-i", str(pattern),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out_path)]


def encode(png_dir, out_path, fps=24, ffmpeg="ffmpeg", pattern=None):
    """Encode png_dir into out_path. Raises RuntimeError rather than failing silently."""
    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"ffmpeg not found on PATH (looked for {ffmpeg!r}); cannot encode video")
    png_dir = Path(png_dir)
    if pattern is None:
        pngs = sorted(png_dir.glob("*.png"))
        if not pngs:
            raise RuntimeError(f"no PNG frames in {png_dir}; nothing to encode")
        pattern = png_dir / "frame.%04d.png"
    cmd = build_ffmpeg_cmd(pattern, out_path, fps, ffmpeg)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {r.returncode}):\n{r.stderr[-2000:]}")
    return Path(out_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s Source/RenderPasses/VolumetricReSTIR/Scripts/tests -v`
Expected: 18 tests, all PASS.

- [ ] **Step 5: Write the capture script**

Create it from the run script, which is already correct up to the graph:

```bash
cp Source/RenderPasses/VolumetricReSTIR/Scripts/run_volume_dataset.py \
   Source/RenderPasses/VolumetricReSTIR/Scripts/capture_sequence.py
```

Then in `capture_sequence.py`, replace these three trailing lines:

```python
m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True
```

with exactly this:

```python
m.addGraph(render_graph())
m.resizeSwapChain(1920, 1080)
m.ui = True

# One capture per animation frame, taken after STEP rendered frames so each has accumulated.
# Low STEP shows honest temporal behaviour for denoiser work; high STEP gives a clean clip.
STEP = int(os.environ.get("VR_STEP_FRAMES", "32"))
out = REPO / "shots" / NAME
os.makedirs(out, exist_ok=True)
m.frameCapture.outputDir = str(out)
m.frameCapture.baseFilename = "frame"
m.frameCapture.addFrames(m.activeGraph, [STEP * (i + 1) for i in range(len(frames))])
# Margin: captureToFile writes asynchronously, so quitting on the last capture truncates it.
m.clock.exitFrame = STEP * len(frames) + 60
```

Also change the docstring's usage line to
`VR_DATASET=firePlume VR_STEP_FRAMES=32 Mogwai.exe --script capture_sequence.py`.

- [ ] **Step 6: Verify capture and encode on the two-frame window**

```bash
VR_DATASET=dustShockwave VR_STEP_FRAMES=8 Mogwai.exe --script capture_sequence.py
python -c "
import sys; sys.path.insert(0,'Source/RenderPasses/VolumetricReSTIR/Scripts')
import encode_video; print(encode_video.encode('shots/dustShockwave', 'shots/dustShockwave.mp4', fps=24))
"
```

Expected: PNGs appear under `shots/dustShockwave/`, and an mp4 is produced.

- [ ] **Step 7: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/capture_sequence.py Source/RenderPasses/VolumetricReSTIR/Scripts/encode_video.py Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vdb_pipeline.py
git commit -m "Capture an ingested dataset to a PNG sequence and encode it to mp4"
```

---

### Task 9: Ingest both full windows and produce the videos

The long job. Everything before this exists so that a failure here is a surprise rather than the
expected case.

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json` (the ingest script writes `baked`)
- Modify: `Source/RenderPasses/VolumetricReSTIR/README.md` — document the pipeline

- [ ] **Step 1: Ingest the fire window**

Run: `python Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py firePlume`
Expected: 32 frames baked; final line reports extent, max density and `has_emission=True`.

- [ ] **Step 2: Ingest the dust window**

Run: `python Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py dustShockwave`
Expected: 32 frames baked.

- [ ] **Step 3: Confirm the manifest recorded itself**

The ingest script writes the `baked` key; nothing is pasted by hand.

Run: `python -c "import json;d=json.load(open('Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json'));print(d['firePlume']['baked'], d['dustShockwave']['baked'])"`
Expected: both datasets carry an `extent`, a `max_density` and a `has_emission`, with
`firePlume.baked.has_emission` true and `dustShockwave.baked.has_emission` false.

- [ ] **Step 4: Produce both videos**

```bash
VR_DATASET=firePlume Mogwai.exe --script capture_sequence.py
VR_DATASET=dustShockwave Mogwai.exe --script capture_sequence.py
python -c "
import sys; sys.path.insert(0,'Source/RenderPasses/VolumetricReSTIR/Scripts')
import encode_video
for n in ('firePlume','dustShockwave'):
    print(encode_video.encode(f'shots/{n}', f'shots/{n}.mp4', fps=24))
"
```

Expected: two mp4s. The fire one shows visible emission; the dust one shows an expanding
shockwave.

- [ ] **Step 5: Verify against the spec's success criteria**

Confirm each of the six criteria in the spec holds, and that
`git status --porcelain | grep -E "VolumetricReSTIRData|FirePlumeVDB|DustShockwaveVDB|shots"`
returns nothing.

- [ ] **Step 6: Document it**

Add a "Adding a new volume dataset" section to `Source/RenderPasses/VolumetricReSTIR/README.md`:
the manifest entry, `ingest_vdb_sequence.py`, `run_volume_dataset.py`, `capture_sequence.py`, the
`gImportVDB` cwd gotcha, the `flames` rename, and the fact that `hasVelocity` is false for these
datasets and why that is a confound when comparing against `fire115`.

- [ ] **Step 7: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json Source/RenderPasses/VolumetricReSTIR/README.md
git commit -m "Ingest both EmberGen windows and document the dataset pipeline"
```
