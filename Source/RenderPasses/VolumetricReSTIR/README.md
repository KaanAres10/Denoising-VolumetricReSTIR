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
