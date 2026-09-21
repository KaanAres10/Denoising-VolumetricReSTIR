# Volumetric ReSTIR (Falcor 8.0 port)

Port of the *Denoising-VolumetricReSTIR* render pass (originally Falcor 4.x, based on Lin et al.
2021 *Volumetric ReSTIR*) to the current Falcor 8.0 tree. The algorithm and shaders are preserved;
only the host/engine glue was rewritten for the 8.0 API.

![bunny_cloud rendered in Falcor 8.0](../../../../docs/images/vr_bunny_cloud.png)

## What's here

| Component | Location |
|---|---|
| Render pass | `Source/RenderPasses/VolumetricReSTIR/` (this folder) |
| GVDB volume subsystem in the Scene | `Source/Falcor/Scene/GVDB/` (`SceneGVDB.{h,cpp}`, `GVDBParameterBlock.slang`, `gvdb*.slang`) + `VolumeDesc`/`volume*` fields in `Scene/SceneTypes.slang` & `Scene/Scene.slang` |
| Run scripts | `Scripts/run_bunny_cloud.py` (working demo), plus the original fork scripts |

## The GVDB / OpenVDB situation

The pass uses NVIDIA **GVDB** for the sparse voxel grids, and loads `.vbx` **in-process** via
`gvdb.LoadVBX`, exactly as the Falcor 4.x fork did. The pipeline is the fork's two stages:

```
.vdb  --(gImportVDB, offline, separate process)-->  .vbx  --(in-process)-->  render
```

### There is no ABI conflict — this README used to say there was

An earlier version of this file, and the comment in `SceneGVDB.cpp`, claimed `gvdb.dll` could not
be loaded inside the Falcor process because its OpenVDB is ABI-incompatible with Falcor's, and an
offline `GVDBBake` → `.bin` stage existed to work around it. That was wrong. There are **two
different `gvdb.dll` builds** in this tree and they are not interchangeable:

| File | Size | OpenVDB dependency |
|---|---|---|
| `legacy/GVDBConverter/gvdb.dll` | 1,670,144 B | **yes** — openvdb, tbb, blosc, Half, snappy, zlib |
| `build/windows-vs2022/bin/Release/gvdb.dll` | 1,481,728 B | **none** — OpenGL, CUDA, CRT only |

`dumpbin /dependents Falcor.dll` lists **both `gvdb.dll` and `openvdb.dll`** as load-time imports,
so GVDB has been resident in the Mogwai process all along. Reading `.vbx` never needed OpenVDB —
only `LoadVDB()` (parsing `.vdb`) does, and that stays in the separate `gImportVDB` process, which
ships its own OpenVDB alongside the first DLL above. The conflict is real for *that* build; it was
never relevant to the one Falcor links.

### Converting `.vdb` → `.vbx`

Run `gImportVDB` from its own directory (it resolves both `cuda_gvdb_module.ptx` **and** its output
folder relative to the working directory, so it must run there and have the result moved):

```
gImportVDB.exe <file.vdb> <numMips>
```

It writes `<name>/<name>_mip{0..N}[c].vbx` plus, on first load, the `_level{n}nodes.bin` node cache
that `Scene::addGVDBVolume` reads back on subsequent runs.

### Verifying a change to the loader

`FALCOR_GVDB_DUMP=1` prints the resulting `GVDBInfo`/`VolumeDesc`, so two loaders can be diffed
before rendering a pixel.

Note that the baked path was **not** equivalent to the fork: its atlas zero-clamp lacked the fork's
`typeId == 1` condition, so it lifted near-zero density to 1/255 across the whole normal mip chain
where the fork clamps only the conservative grid. Since the shipped defaults sample mips 1 and 2,
measurements taken through the baked path carry that deviation.

## Running

```
Mogwai.exe --script Source/RenderPasses/VolumetricReSTIR/Scripts/run_bunny_cloud.py
```

Edit `DATA_DIR` in the script to point at your scene data.

## Adding a new volume dataset

External VDB sequences (e.g. the CC0 JangaFX EmberGen packs) are ingested through a
manifest-driven pipeline rather than by hand. Add an entry to
[`Scripts/datasets.json`](Scripts/datasets.json), then:

From the repo root, in PowerShell:

```
python Source\RenderPasses\VolumetricReSTIR\Scripts\ingest_vdb_sequence.py <dataset>

$env:VR_DATASET="<dataset>"
build\windows-vs2022\bin\Release\Mogwai.exe --script Source\RenderPasses\VolumetricReSTIR\Scripts\run_volume_dataset.py
build\windows-vs2022\bin\Release\Mogwai.exe --script Source\RenderPasses\VolumetricReSTIR\Scripts\capture_sequence.py

python -c "import sys; sys.path.insert(0, r'Source\RenderPasses\VolumetricReSTIR\Scripts'); import encode_video; encode_video.encode(r'shots\<dataset>', r'shots\<dataset>.mp4')"
```

Ingest is resumable: a frame counts as done only when every expected `_mip{0..N}[c].vbx` exists
and is non-empty, so an import killed part way is redone rather than skipped. The `.vbx` set is
what Falcor loads, so it is kept; the measured mip0 extent is written back into the manifest under
`imported`. Derived cost is roughly **7.8x** the source frame, so budget accordingly.

Derivable values are not hand-tuned. [`Scripts/vdb_pipeline.py`](Scripts/vdb_pipeline.py) parses
the bake header and computes placement and density; it is unit tested against the bakes already
on disk (`python -m unittest discover -s Scripts/tests`).

Five things that are easy to get wrong, all learned the hard way:

- **`gImportVDB` resolves both its CUDA module and its output folder against the working
  directory.** Those pull in opposite directions, so it must run from its own directory and have
  its output moved.
- **`VDBPrep.exe` must live in Falcor's `bin/Release`, never in a `GVDBConverter` folder.** Those
  ship the 2021 GVDB-era `openvdb.dll`, and Windows searches the executable's own directory
  first — it would load exactly the OpenVDB whose ABI is incompatible with the one it links.
- **`worldTranslation` is the volume's CENTRE, not its min corner.** The scene matrix alone reads
  as a min corner, but GVDB's per-volume `xform` already centres the grid and the two compose.
- **`densityScale` cannot be copied between datasets.** Optical thickness is
  `densityScale / worldScaling`, and it also scales with the grid's own density values, so a
  dataset whose max density differs from the reference needs `density_scale_ref` adjusted too.
- **The emission channel needs a rename.** EmberGen calls it `flames`, and GVDB's loader skips a
  `flames` grid that is not first in the file; `VDBPrep` renames it to `temperature`. Values are
  untouched — the Kelvin mapping is a runtime affine transform, so fire colour is tunable in the
  manifest without re-baking.

**Known limitations of these datasets.** Neither EmberGen pack ships velocity grids, so they run
with `hasVelocity=false` and get no velocity-based temporal reprojection — unlike `fire115`.
Treat that as a confound when comparing denoiser results across these scenes and that one. Also
see the open emission defect in
[the design spec](../../../docs/superpowers/specs/2026-09-20-volumetric-dataset-pipeline-design.md):
final radiance is near-invariant to `LeScale`, so the fire does not yet read as fire.

## Denoisers

The three research denoisers are ported and build/run against Falcor 8.0. Chain any of them after
`VolumetricReSTIR.accumulated_color` (denoise HDR radiance) and before `ToneMapper`:

| Pass | Location | Backend | Enable gate |
|---|---|---|---|
| `OptixDenoiser` | `Source/RenderPasses/OptixDenoiser/` (native, migrated to the **OptiX 8.0+ API**; validated on **OptiX 9.1**) | CUDA + OptiX AI denoiser | `FALCOR_HAS_CUDA AND FALCOR_HAS_OPTIX` |
| `OIDNCPUPass` | `Source/RenderPasses/OIDNCPUPass/` | Intel OIDN 2.3.3, CPU (readback→denoise→upload) | `FALCOR_HAS_OIDN` |
| `OIDNGPUPass` | `Source/RenderPasses/OIDNGPUPass/` | Intel OIDN 2.3.3, CUDA (zero-copy via Falcor `InteropBuffer`) | `FALCOR_HAS_OIDN AND FALCOR_HAS_CUDA` |

OIDN is wired in `external/CMakeLists.txt` as `FALCOR_HAS_OIDN`, pointing at the cache var
`FALCOR_OIDN_DIR` (default `C:/oidn-2.3.3.x64.windows`). Each OIDN pass copies its required runtime
DLLs (`OpenImageDenoise*.dll` + `tbb12.dll`) next to the executables at build time. Example graph
in `Scripts/run_bunny_cloud.py` comments / the scratchpad `test_oidn_{cpu,gpu}.py`.

## Status

- ✅ Pass + Scene GVDB subsystem + all compute shaders compile against Falcor 8.0.
- ✅ Volume loads (via prebake) and renders — validated against the paper's `bunny_cloud` result.
- ✅ Full temporal + spatial ReSTIR reuse.
- ✅ Denoisers ported and **all three runtime-validated** on `bunny_cloud`: `OptixDenoiser`,
  `OIDNCPUPass`, `OIDNGPUPass` (clean output, no CUDA-interop errors).
- ✅ **Surface scenes work** (`Scripts/run_bistro.py`): the Bistro exterior geometry is shaded and lit
  by its many emissive lights, with the smoke plume scattering that light. This required porting the
  previously-stubbed surface path onto the 8.0 material system — see "Surface-scene path" below.
- ✅ Animated volume sequences (the `fire115` plume) render and play via `addGVDBVolumeSequence`
  (`Scripts/run_plume.py`): each frame is imported to `.vbx` by `gImportVDB`, the sequence
  advances one frame per rendered frame (`Scene::update` → `advanceVolumeAnimation`), and
  velocity-based temporal reprojection works. Set the pass property
  `mVolumeAnimationSelectedFrameId` (0-based) to pause on a frame and converge to a clean still.

### Surface-scene path (`mUseSurfaceScene`)

Used by the Bistro / Emerald Square scenes, where the medium sits inside real geometry lit by many
emissive lights. The Falcor 4.x material API this relied on (`evalBSDF`, `ShadingData.emissive/.N`,
`prepareShadingData(materials[], …)`) is gone in 8.0, so `InlineRayTracingHelpers.slang` now bridges
the pass's original interface onto the 8.0 material system:

- Ray tracing uses the scene's own `gScene.rtAccel` (no separate acceleration-structure binding).
- `computeSurfaceShadingInfo` → `getVertexData` + `getMaterialID` + `materials.prepareShadingData`,
  returning a small `SurfaceShadingData` wrapper (`sd`, `posW`, `N`, `emissive`) so the shaders'
  `shadingInfo.posW/.N/.emissive` accesses keep working.
- `evalBSDFCosine` / `sampleBSDF` → `IMaterialInstance.eval` / `.sample` (note `BSDFSample.wo`).

Two host-side requirements are easy to miss:

1. **Bind the scene for ray tracing.** Plain `bindShaderData()` does *not* build/bind the TLAS — only
   `bindShaderDataForRaytracing(pRenderContext, var, 0)` does. Without it `FindSurfaceHit` finds
   nothing and only the medium renders.
2. **Link the material system.** The programs need the scene's shader modules *and* material type
   conformances (`createSceneComputePass` in `Utils.cpp`); the passes are therefore recreated in
   `setScene()` when the surface path is enabled.

Also note `gScene.emissiveIntensityMultiplier` must be set explicitly (see `SceneGVDB.cpp`) — the
shader's `= 1.f` default does not apply to constant-buffer-backed data, and if it stays 0 emissive
lights render their own emission but illuminate nothing.

### Note on OptiX version / driver

The `OptixDenoiser` pass targets the OptiX 8.0+ API and is validated against **OptiX 9.1**. The SDK
and the driver must agree on the ABI (8.1 → 93, 9.0 → 105, 9.1 → 118): a driver that predates the
SDK's ABI fails at `optixInit()` with `OPTIX_ERROR_UNSUPPORTED_ABI_VERSION`. OptiX 9.1 needs a
suitably recent driver (validated on 610.74). After changing SDK or driver, clear
`%localappdata%\NVIDIA\OptixCache` and force a rebuild of the pass (the OptiX function-table symbol
is ABI-versioned, so stale objects produce `unresolved external g_optixFunctionTable_*`).

### Note on the world transform (transpose)

GVDB's `Matrix4F` is column-major and the verbatim shaders consume `gvdb.xform` with a row-vector
`mul(v, M)`. Falcor 8.0's `float4x4` is the transpose of that layout, so the `volumeExternal*Matrix`
values built with Falcor math helpers are **transposed before binding** (see `SceneGVDB.cpp`) to stay
consistent with `gvdb.xform` in the shader. This is a no-op for a static volume placed with the
default transform (identity), which is why `bunny_cloud` worked before the plume exposed it.

## DLSS integration and guide buffers

The pass can feed NVIDIA DLSS (`Source/RenderPasses/DLSSPass/`). DLSS requires `color`, `depth` and
`mvec` and treats **all three as non-optional** — an unconnected input is a graph compile error, and
mismatched input sizes throw at runtime. It also needs motion vectors that are sub-pixel accurate and
*deterministic*, which the original `mvec` output is not (it is integer-pixel quantised and its
reprojection anchor is drawn stochastically, which is correct for ReSTIR resampling and wrong for a
temporal upscaler).

New outputs and properties, **all defaulting to today's behaviour**:

| Property | Default | Meaning |
|---|---|---|
| `outputSize` / `fixedOutputSize` | `Default` | Render scale. `Default` = swapchain size, identical to before. |
| `mOutputDepth` | `false` | Write the `linearZ` output. |
| `mDepthAsNDC` | `false` | `false` = linear view Z (matches `GBufferRT.linearZ`); `true` = NDC depth. |
| `mMotionVecMode` | `Off` | `Legacy` = the original stochastic writer (what `mOutputMotionVec: True` maps to); `Deterministic` = the sub-pixel writer in `GenerateFeatures`. |
| `samplePattern` / `sampleCount` | `Center` / 32 | Camera jitter. `Center` installs no generator. |

`linearZ` is the **transmittance-weighted mean scattering distance** `E[t] = Σ t·w / Σ w`, where
`w = T(t)·(1-exp(-σₜ·dt))` is the per-step scattering weight the feature march already computes. It
consumes no random numbers, so unlike `Reservoir::depth` it is temporally stable. Falls back to the
opaque surface hit (`SURFACE_SCENE`) and then the far plane.

### Bias-sensitive configuration

Everything above is **estimator-neutral except camera jitter**:

- `outputSize`, `mOutputDepth`, `mMotionVecMode`, `mDepthAsNDC` — verified byte-identical on the
  reference-vs-ReSTIR HDR comparison (`Scripts/bias_test_plume.py`): `mse 0.000100567`,
  `rmse 0.000506544`, `mape 0.747974`, unchanged with the guides enabled.
- `samplePattern != Center` **is not neutral, and its exact cost is still open.**
  `computeNonNormalizedRayDirPinholeWithFrame` must reconstruct the previous frame'''s ray with the
  jitter that frame was rendered with, otherwise `p̂` is evaluated on the wrong domain. Talbot weights
  renormalise, so the usual cost is variance — but where the wrong ray flips a hit to a miss
  (silhouettes) `p̂` is exactly zero, the weights stop summing to one, and the result is biased.
  `mPrevJitter` is snapshotted and threaded through as `gPrevJitter`; `mApplyPrevJitter` (default on)
  can disable it to reproduce the pre-fix behaviour.

  Measured against a brute-force volumetric path-traced ground truth (`Scripts/bias_test_plume.py`,
  single analytic light, 4096 accumulated frames, HDR — never a tone-mapped PNG, whose clamping
  would discard energy in proportion to variance):

  | config | MSE vs ground truth | |
  |---|---|---|
  | jitter off (baseline) | 1.006e-4 | — |
  | jitter on, `mApplyPrevJitter=false` | 1.368e-4 | **36% worse** |
  | jitter on, `mApplyPrevJitter=true` | **9.205e-5** | **8% better** |

  Jitter **without** the fix is measurably worse than no jitter at all; **with** it, jitter is the most
  accurate of the three. So the fix is necessary, not cosmetic, and jitter is safe to enable for DLSS
  as long as `mApplyPrevJitter` stays on (the default).

  Supporting evidence: a single frame with temporal reuse disabled differs by 2.0e-4 between
  jitter on/off, confirming the forward path really does consume jitter (so the previous frame'''s
  reservoirs were generated on jittered rays); and on Bistro the fixed and unfixed configurations
  converge to *different* images (difference asymptotes rather than decaying with sample count),
  which is the signature of one of them being biased.

### Note on the previous-frame matrices (transpose)

`TemporalReuse.cs.slang` reprojects with the Falcor 4.x row-vector convention `mul(v, M)`. Under
Falcor 8's row-major Slang layout (`ProgramManager` requests `MatrixLayoutRow`, and `ParameterBlock`
uploads matrices verbatim) that evaluates `Mᵀ·v`, while Falcor 8's own matrices are built for
`mul(M, v)`. They are therefore **transposed on upload** (`mTransposePrevMatrices`, default on) —
the same fix `SceneGVDB.cpp` applies to the GVDB matrices.

Measured on a panning camera with temporal reuse only: **33.6% less per-frame noise** (total
variation 3.16 → 2.10) and a 13% smaller PNG. A static camera cannot show this, because the
reprojection is the identity either way. It is a variance fix, not a bias fix — the Talbot MIS
weights are re-derived from whichever tap is selected, and the HDR bias test is unchanged.
