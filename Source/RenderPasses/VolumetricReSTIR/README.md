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
| Offline GVDB bake tool | `Source/Tools/GVDBBake/` + shared format `Source/Falcor/Scene/GVDB/GVDBBakeFormat.h` |
| Run scripts | `Scripts/run_bunny_cloud.py` (working demo), plus the original fork scripts |

## The GVDB / OpenVDB situation (important)

The pass uses NVIDIA **GVDB** to represent the sparse voxel grids. The prebuilt `gvdb.dll` (shipped
in the fork) is linked against an **OpenVDB build that is ABI-incompatible with the OpenVDB that
Falcor 8.0 ships**, and two `openvdb.dll` versions cannot coexist in one process. So `gvdb.dll`
cannot be loaded inside the Falcor process.

Solution: **offline prebake.** A standalone tool (`GVDBBake`) runs `gvdb.dll` *in isolation* (its
own OpenVDB, no Falcor, no conflict) to parse each `.vbx` and serialize everything Falcor needs
(repacked sparse node pools, child lists, the dense density atlas, and per-mip metadata) into a
plain `.bin`. Falcor then just reads the `.bin` and uploads it to the GPU — **no `gvdb.dll` in the
Falcor process at all.**

### Baking a volume

Build `GVDBBake` (once) and run it from a directory where `gvdb.dll` can find its own OpenVDB/TBB
(the fork's `Bin\x64\Release`):

```
GVDBBake.exe <vbxFolder> <numMips> <hasVelocity 0|1> <hasEmission 0|1> <out.bin>
# e.g.
GVDBBake.exe "Data\bunny_cloud" 7 0 0 "Data\bunny_cloud.bin"
```

Place the resulting `<name>.bin` next to the volume folder. At runtime, `Scene::addGVDBVolume`
(and `addGVDBVolumeSequence`) automatically load `<dataFile>.bin` if present.

## Running

```
Mogwai.exe --script Source/RenderPasses/VolumetricReSTIR/Scripts/run_bunny_cloud.py
```

Edit `DATA_DIR` in the script to point at your scene data.

## Adding a new volume dataset

External VDB sequences (e.g. the CC0 JangaFX EmberGen packs) are ingested through a
manifest-driven pipeline rather than by hand. Add an entry to
[`Scripts/datasets.json`](Scripts/datasets.json), then:

```
python Scripts/ingest_vdb_sequence.py <dataset>          # VDBPrep -> gImportVDB -> GVDBBake
VR_DATASET=<dataset> Mogwai.exe --script Scripts/run_volume_dataset.py       # play it back
VR_DATASET=<dataset> Mogwai.exe --script Scripts/capture_sequence.py         # capture PNGs
python -c "import encode_video; encode_video.encode('shots/<dataset>', 'shots/<dataset>.mp4')"
```

Ingest is resumable: it bakes to `<frame>.bin.part` and renames on success, so an interrupted
run never leaves a truncated `.bin` that a later run would skip as finished. It deletes the
`.vbx` intermediates (reproducible from source) and writes the measured `baked` values back into
the manifest. Derived cost is roughly **7.7x** the source frame, so budget accordingly.

Derivable values are not hand-tuned. [`Scripts/vdb_pipeline.py`](Scripts/vdb_pipeline.py) parses
the bake header and computes placement and density; it is unit tested against the bakes already
on disk (`python -m unittest discover -s Scripts/tests`).

Five things that are easy to get wrong, all learned the hard way:

- **`gImportVDB` resolves both its CUDA module and its output folder against the working
  directory.** Those pull in opposite directions, so it must run from its own directory and have
  its output moved.
- **`VDBPrep.exe` must live in Falcor's `bin/Release`, never beside `GVDBBake.exe`.** That folder
  ships the 2021 GVDB-era `openvdb.dll`, and Windows searches the executable's own directory
  first — it would load exactly the OpenVDB whose ABI conflict the prebake design avoids.
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
  (`Scripts/run_plume.py`): each frame is pre-baked with `GVDBBake` (incl. velocity), the sequence
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
- **Temporal reuse is biased while the camera moves**, at thin medium. `TemporalReuse.cs.slang` picks
  last frame's pixel from the canonical sample's own depth when that sample scattered in the medium,
  so the temporal neighbour depends on the sample, and the Talbot weights (which assume it does not)
  stop summing to one. A still camera maps every choice to the same pixel, so a static bias test
  cannot see it; under motion, parallax sends medium and surface to different pixels. Bistro,
  stop-and-go path, scene animation frozen, 8 seeds against a 256-frame temporal-reuse-off truth at
  the same pose -- the medium's own light (`volumeColor`):

  | | thin medium (1-30% coverage) | silhouette (30-90%) | deep |
  |---|---|---|---|
  | moving, as shipped | **0.60** | **0.80** | 0.99 |
  | still | 0.99 | 1.01 | 1.00 |
  | moving, `mTemporalReprojectIndependent` | 0.99 | 1.00 | 1.00 |
  | still, `mTemporalReprojectIndependent` | 1.01 | 1.02 | 1.00 |

  That reference (temporal reuse off, 256 frames at the same pose) is itself within 1% of brute-force
  volumetric path tracing there -- thin 1.009, edge 0.994, deep 1.027 against `mUseReference`, 256
  frames x 4 spp. The repo's static bias tests cannot see any of this: with a still camera every depth
  reprojects to the same pixel, so the dependence disappears.

  `mTemporalReprojectIndependent` (default **off**; `VR_TR_INDEPENDENT=1` in `vr_graph`) draws the
  point from the pixel alone -- the surface with probability T, else a point by density, as the
  surface-sample branch already did. Off is byte-identical to before. Cost: +0.06 ms (temporal reuse,
  960x540; +0.28 ms at 1080p), and ~1.7-2x the per-pixel noise at a moving silhouette, where the
  history now matches less often; still frames and deep medium are unchanged.

  `mTemporalReprojectByLightShare` (`VR_TR_LIGHT_SHARE=1`, needs the switch above) follows the surface
  with its share of the pixel's LIGHT instead of T -- the guides' light-share statistics, read from last
  frame, so the neighbour still does not depend on this frame's sample. It buys back part of that noise
  (medium light at a moving silhouette 1.08 -> 0.89 of the true light, thin medium 1.76 -> 1.62, against
  0.65 / 0.90 as shipped; in the TOTAL light, edge 0.90 -> 0.84 and thin 0.72 -> 0.70, against
  0.82 / 0.68) and keeps the correction (moving 1.03 thin / 1.00 edge). The statistics pass, which
  otherwise only runs for the guides, then runs whenever this is on. With no reprojection at all (another
  neighbour that cannot depend on the sample) the loss also mostly goes -- 0.98 / 0.98 moving with
  `mTemporalReprojectionMode = kReprojectionNone`, which is a shipped setting and needs no code change
  at all. That pins the cause on the dependence rather than on temporal reuse as such, and it is a
  usable fallback: it blotches less on screen than either switch, at the price of deep medium, which
  loses motion compensation entirely (noise 0.73 against 0.53 of the true light). Beware that an orbit
  centred on the medium flatters it -- the medium barely moves on screen there, so "the same pixel" is
  nearly right for it; a pan is untested. Shortening the history cap instead (10x -> 2x) only halves the
  loss (0.77 / 0.92) and costs noise in every frame, still ones included.

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
