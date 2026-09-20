# Volumetric dataset pipeline: EmberGen VDB sequences end to end

**Date:** 2026-09-20
**Status:** design approved in chat; awaiting spec review
**Branch:** nrd-v4-port

## Intent

Extend the scene variability available to the denoiser research beyond the single `fire115`
plume, by making externally authored VDB sequences first-class citizens of this project:
converted, baked, animated, emissive where appropriate, and renderable to video.

Two CC0 EmberGen (JangaFX) datasets are the first consumers and the proof that the pipeline
generalises:

| Dataset | Frames available | Source size/frame | Grids present |
|---|---|---|---|
| `FirePlumeVDB/fire_plume/fire_plume_VDB/firePlume_NNNN.vdb` | 250 (0000-0249) | ~41 MB, flat across the sequence | `density`, `flames` |
| `DustShockwaveVDB/DustShockwave/DustShockwaveVDB/dustshockwave_NNNN.vdb` | 155 (0000-0154) | 3 MB to 122 MB, monotonically growing | `density` |

### Success criteria

1. One command ingests a named dataset from `datasets.json` and produces baked `.bin` frames.
2. Both datasets play back as animated volumes in Mogwai via `addGVDBVolumeSequence`.
3. The fire plume emits light through the blackbody LUT; it reads as fire, not grey smoke.
4. Both datasets render to an mp4.
5. Re-running ingest is idempotent and skips already-baked frames.
6. No dataset or derived artefact is tracked by git.

## Decisions already taken

| Decision | Choice | Rationale |
|---|---|---|
| Frame budget | 32 frames per dataset | Both full sequences would need ~377 GB derived against ~236 GB free. 32 frames is ~36 GB, doubles the `fire115` 16-frame precedent, and gives a ~1.3 s loop at 24 fps. |
| Emission | Yes, for the fire dataset | An emissive volume stresses denoisers differently from a purely scattering one, which is the point of adding variability. |
| Velocity | Accept `hasVelocity=False` | Neither dataset ships velocity grids. Synthesising a field from consecutive density frames is a research project in itself, and being derived data it risks flattering or penalising the very reprojection being measured. Documented as a known confound. |
| Import tooling | Drive the existing prebuilt executables | `SaveVBX` is called inside `LoadVDB` in the prebuilt `gvdb.dll`, so folding import into `GVDBBake` cannot avoid the intermediate `.vbx` and would only risk a working tool. |

## What already works (verified 2026-09-20)

A single EmberGen frame was taken end to end with no changes to the project:

```
gImportVDB.exe firePlume_0125.vdb 4      -> firePlume_0125/firePlume_0125_mip{0..3}[c].vbx
GVDBBake.exe   firePlume_0125 4 0 0 out  -> firePlume_0125.bin   (maxDensity 0.719)
m.scene.addGVDBVolume(dataFile=..., numMips=4, hasVelocity=False, hasEmission=False)
```

It rendered, and its noise level matched `fire115.0198` rendered through an identical harness at
the same frame count, which rules out a bad bake. Measured cost: 41 MB source to 321 MB `.vbx`
to 317 MB `.bin`.

Two operational facts discovered, worth encoding in the tooling:

- `gImportVDB` writes its output into a folder named after the input file, **relative to the
  current working directory**, not beside the source. The orchestrator must control cwd.
- The loader silently skips a `flames` grid when it is not the first grid in the file
  (`legacy/gvdb-voxel-src/source/gvdb_library/src/gvdb_volume_gvdb.cpp:2458`). This is why the
  fire dataset converts to density only, and is what `VDBPrep` exists to work around.

## Architecture

### Components

| Component | Kind | Responsibility | Depends on |
|---|---|---|---|
| `Source/RenderPasses/VolumetricReSTIR/Scripts/datasets.json` | data | Single source of truth per dataset | - |
| `Source/Tools/VDBPrep/` | new C++ tool | Rename one or more grids inside a `.vdb` | Falcor OpenVDB (`external/packman/deps`) |
| `Source/RenderPasses/VolumetricReSTIR/Scripts/ingest_vdb_sequence.py` | new script | Orchestrate prep, import, bake per frame; write back baked bounds | `VDBPrep`, `gImportVDB`, `GVDBBake` |
| `Scripts/run_firePlume.py`, `Scripts/run_dustShockwave.py` | new scripts | Animated playback with derived transform | manifest, baked `.bin` |
| `Scripts/capture_sequence.py` | new script | Frame capture to mp4 | ffmpeg 8.1.1 (on PATH) |

Each unit is independently testable: `VDBPrep` against a single file, the ingest script against a
two-frame window, the run scripts against an already-baked window, and capture against an
existing PNG sequence.

### Data flow

```
   *.vdb
     |  (fire only) VDBPrep: rename "flames" -> "temperature"
     v
   *_prepped.vdb
     |  gImportVDB <file> 4
     v
   <frame>/<frame>_mip{0..3}[c].vbx  (+ <frame>_temperature.vbx when prepped)
     |  GVDBBake <folder> 4 <hasVel> <hasEm> <frame>.bin
     v
   <frame>.bin        <- .vbx folder and prepped .vdb deleted here
     |  addGVDBVolumeSequence
     v
   PNG sequence -> ffmpeg -> mp4
```

## The manifest

`datasets.json` is what every downstream script reads, so a dataset is described exactly once.

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
    },
    "baked": { "extent": [202, 679, 456], "max_density": 0.719238 }
  }
}
```

`baked` is written back by the ingest script from the first baked frame; it is derived data, not
hand-authored. `provenance` exists so the thesis can cite the datasets without re-deriving where
they came from.

The `dustShockwave` entry has the same shape with three differences: an empty `grid_renames`,
`has_emission: false`, and no `le_scale` / `temperature_*` values, since it ships only a `density`
grid. Its `start_frame` is 60.

## VDBPrep

A standalone tool, deliberately minimal:

```
VDBPrep <in.vdb> <out.vdb> <oldGridName>=<newGridName> [...]
```

It opens the file with OpenVDB, renames the named grids via `setName`, and writes the result. It
does **not** modify voxel values.

Value remapping is unnecessary because the renderer already applies an affine transform at
shading time (`Source/RenderPasses/VolumetricReSTIR/VolumeBase.slang:278`):

```
temp       = min(6400, (gridValue - temperatureCutOff) * temperatureScale)
queryPoint = (temp - 25) / 6400
colour     = LeScale * blackbodyLUT.Sample(queryPoint)
```

So the normalised 0-1 `flames` field maps to Kelvin purely through manifest parameters:
`temperature_cutoff` acts as a combustion threshold and `temperature_scale` sets peak temperature
(2800 K gives an orange-yellow flame; 6400 K would be white-hot). Fire colour is therefore
tunable without re-baking, which is the main reason to keep `VDBPrep` a pure rename.

It links the OpenVDB headers and `openvdb.lib` from `external/packman/deps`, and runs as its own
process, so the OpenVDB ABI conflict that motivated the `GVDBBake` prebake does not apply.

## Ingest script

```
python ingest_vdb_sequence.py <dataset-name> [--frames N] [--keep-intermediates] [--force]
```

Per frame: optionally run `VDBPrep`; run `gImportVDB` with cwd set to the destination directory;
run `GVDBBake` with the manifest `has_velocity` and `has_emission` values; then delete the `.vbx`
folder and any prepped `.vdb` unless `--keep-intermediates`. Deleting intermediates roughly halves
peak disk use, and they are reproducible from source at any time.

Idempotency: a frame whose `.bin` already exists is skipped unless `--force`. This matters because
a 32-frame ingest is a long job and must be resumable.

Output lands in `VolumetricReSTIRData/<dataset>/`, which is already gitignored.

## Transform and density derivation

`computeVolumeExternalModelToWorldMatrix` composes `T * Rx * Ry * Rz * S`
(`Source/Falcor/Scene/GVDB/SceneGVDB.cpp:219`) and local coordinates start at the origin, so
`worldTranslation` is the **min corner**, not the centre. The run scripts therefore compute:

```
scale       = target_height / extent.y
translation = centre - extent * scale / 2
```

This formula was validated against the existing reference: applied to the `fire115` extent it
reproduces its hand-authored `worldTranslation` of `(0, 1.686, 0)` to three decimal places.

Effective optical thickness is `densityScale / worldScaling`
(`Source/Falcor/Scene/GVDB/SceneGVDB.cpp:624`), so `densityScale` cannot be copied between
datasets of different voxel resolution. The run scripts preserve the reference thickness:

```
density_scale = density_scale_ref * (scale / 0.013)
```

where `0.013` is the `fire115` world scaling. Without this, the first probe render came out
roughly six times too optically thick.

## Frame windows and storage

With intermediates deleted, derived cost is roughly 7.7x the source frame.

| Dataset | Window | Why this window | Estimated |
|---|---|---|---|
| firePlume | 100-131 | Sequence is steady state throughout, so any window is equivalent; this one contains frame 125, already validated | ~13 GB (estimate; includes the temperature channel, which is not yet measured) |
| dustShockwave | 60-91 | The shockwave expands continuously and frame cost grows ~40x across the sequence; mid-expansion gives visible shock structure without the late-frame cost cliff | ~22 GB (estimate, extrapolated from the one measured frame) |

Roughly 35 GB total against ~236 GB free. Both figures are extrapolations from a single measured
frame and are expected to be refined by verification step V1.

## Video output

`capture_sequence.py` drives Mogwai over the baked window, accumulating a fixed number of frames
per animation step before capturing, then invokes ffmpeg (8.1.1, confirmed on PATH) to encode the
PNG sequence. Frames-per-step is a parameter: the denoiser comparisons need a low value to show
temporal behaviour honestly, while a presentation clip wants a high one.

## Risks and early verification

**R1 - per-frame rebasing (highest).** Every volume read back so far reports `bmin = (0,0,0)` -
`fire115`, `firePlume` and `bunny_cloud` alike - which suggests GVDB rebases each frame to its own
active bounding box. Harmless for a steady-state plume, but the dust shockwave expands ~40x across
the sequence and could end up anchored or jittering instead of expanding.

> **V1:** bake dust frames 60 and 91, compare their baked `extent`, and render both. About ten
> minutes. If the extents differ as the source sizes imply they should, the risk is dismissed; if
> they are identical, the dust dataset needs a per-frame transform correction and that part of the
> work is reshaped before any 32-frame bake is started.

**R2 - emission through a renamed grid is unproven.** The rename route follows from reading the
loader, not from observation.

> **V2:** prep one fire frame, import, bake with `hasEmission=1`, confirm a `_temperature.vbx` is
> produced and that the frame renders as emissive. Before any bulk ingest.

**R3 - ingest is a long job.** A 32-frame window is on the order of an hour per dataset. Mitigated
by idempotent resume, and by V1 and V2 running first so a failure surfaces in minutes rather than
after an hour of baking.

**R4 - untracked source data.** `FirePlumeVDB/` and `DustShockwaveVDB/` are 23 GB of untracked
files at the repo root; a stray `git add -A` would attempt to commit them. Both are added to
`.gitignore` as the first task of implementation.

## Out of scope

- The scene-parameterised denoiser comparison matrix. `compare_denoisers_plume.py` stays
  single-scene; extending it is a separate piece of work that should follow this one.
- Velocity synthesis, per the decision above.
- Ingesting the remaining frames of either sequence. The manifest makes the window a parameter,
  so extending later costs no redesign.
