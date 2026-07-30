# DLSS passes

Two NGX features are used here, and they are **not** the same thing:

| | Feature | What it does |
|---|---|---|
| `DLSSPass` | Super Resolution (`nvngx_dlss.dll`) | Temporal upscaler. Denoises only as a side effect — measured on Bistro it cuts noise ~29% (TV 11.06 → 7.80), which is not enough for 1-spp ReSTIR. |
| `DLSSDPass` | Ray Reconstruction (`nvngx_dlssd.dll`) | A genuine ray-tracing denoiser that also upscales, replacing OIDN/OptiX/NRD. |

## The SDK is vendored manually — this is not optional

**packman has no DLSS newer than 3.5.0**, and 3.5.0 is Super-Resolution only: no
`nvsdk_ngx_*_dlssd.h`, no `nvngx_dlssd.dll`. On GitHub, the `v3.5.0` and `v3.7.x` tags also lack
Ray Reconstruction — **only the `v310.x` line ships it**.

So the SDK comes from a manual fetch into `external/dlss-310/` (gitignored, ~106 MB):

```bash
git clone --depth 1 --branch v310.7.0 --filter=blob:none --sparse \
    https://github.com/NVIDIA/DLSS.git /tmp/dlss310
cd /tmp/dlss310 && git sparse-checkout set include lib/Windows_x86_64

# then, from the repo root:
D=external/dlss-310
mkdir -p $D/include $D/lib/Windows_x86_64/x64 $D/lib/Windows_x86_64/rel
cp /tmp/dlss310/include/*.h                                  $D/include/
cp /tmp/dlss310/lib/Windows_x86_64/x64/nvsdk_ngx_d*.lib      $D/lib/Windows_x86_64/x64/
cp /tmp/dlss310/lib/Windows_x86_64/rel/nvngx_dlss*.dll       $D/lib/Windows_x86_64/rel/
```

**If this directory is missing, CMake silently falls back to the packman 3.5.0 SDK**,
`FALCOR_HAS_DLSSD` goes OFF, and `DLSSDPass` disappears from the plugin list rather than failing
to build — the failure mode is "unknown render pass", not a compile error. Watch for this line at
configure time:

```
-- DLSS SDK: .../external/dlss-310
```

`FALCOR_DLSS_SDK_DIR` overrides the search if you keep the SDK elsewhere.

### Gotcha: the import-lib subdirectory was renamed

3.5.0 uses `lib/Windows_x86_64/x86_64/`, the 310.x line uses `lib/Windows_x86_64/x64/`.
`external/CMakeLists.txt` probes for both; don't hardcode either.

## Checking Ray Reconstruction is available

`NGXWrapper::initializeNGX()` logs a capability probe on startup:

```
[DLSS-D probe] RayReconstruction available=1 needsUpdatedDriver=0 minDriver=537.2
```

`available=0` with `needsUpdatedDriver=0` and `minDriver=0.0` almost certainly means
**`nvngx_dlssd.dll` is not next to the executable** — NGX populates these from the feature DLLs on
its search path, so a missing DLL looks identical to unsupported hardware. Confirm the DLL is in
`build/windows-vs2022/bin/Release/` before concluding your GPU cannot do RR.

Minimum driver for RR is **537.2** (SR's is lower). `build_scripts/deploycommon.bat` copies both
DLLs; robocopy skips missing ones, so it stays correct against either SDK.

---

# DLSS Ray Reconstruction: results and gotchas

## What it buys

Measured on Bistro, native 1920x1080 (DLAA), frame 200, no upscaling on any row so the denoisers
are compared like for like. TV = mean absolute difference between horizontally adjacent pixels, a
proxy for per-frame noise.

| Denoiser | mean | TV (noise) | vs raw | stages |
|---|---|---|---|---|
| none (raw ReSTIR) | 15.90 | 13.872 | -- | -- |
| OIDN GPU | 10.84 | 2.827 | -80% | 1 (+ SR to upscale) |
| OptiX (temporal) | 11.07 | 2.248 | -84% | 1 (+ SR to upscale) |
| **DLSS Ray Reconstruction** | 12.90 | **0.976** | **-93%** | **1, upscales too** |

RR is the cleanest *and* the only one that also upscales, so at matched frame time the others still
need DLSS SR chained after them.

**TV rewards smoothness**, so it cannot by itself distinguish "cleaner" from "blurrier". Measured
properly against a converged reference (`Scripts/compare_denoisers_plume.py`, static plume, HDR --
never tone-mapped PNGs, whose clamping discards energy in proportion to variance -- single denoised
frame vs 3000 spp brute-force path tracing):

| Denoiser | MSE | MAPE | vs raw |
|---|---|---|---|
| raw ReSTIR (1 frame) | 1.523e-3 | 10.35 | -- |
| OIDN GPU | 3.590e-4 | 5.20 | 4.2x |
| OptiX (temporal) | 5.207e-4 | 5.80 | 2.9x |
| **DLSS Ray Reconstruction** | **1.560e-4** | **3.43** | **9.8x** |

RR is best on both metrics. This matters because MSE against ground truth **cannot be gamed by
blurring** -- an over-smoothed result scores worse, not better -- so RR is genuinely closer to the
truth (2.3x vs OIDN, 3.3x vs OptiX), not merely smoother. And it upscales in the same stage.

For contrast, DLSS **Super Resolution** alone only reaches TV 7.80 (-29%) -- it is a temporal
upscaler whose denoising is incidental. That is why the SR scripts chain OIDN in front.

## Supplying the optional inputs matters

Passing the camera matrices and frame-time hint improved RR measurably:

| | TV (noise) |
|---|---|
| RR without matrices / frame time | 1.194 |
| RR with them | **0.976** (-18%) |

`pInWorldToViewMatrix` / `pInViewToClipMatrix` (use the **NoJitter** projection -- jitter is reported
separately via `InJitterOffset*`, so a jittered matrix double-counts it) and `InFrameTimeDeltaInMsec`
are all optional in the sense that RR runs without them, and all worth setting.

## Volumetric guides (Stage 2)

RR's albedo/normal/roughness guides describe a *surface*; a participating medium has none. Rather
than use RR's `colorBeforeFog`/`colorAfterFog` pair -- which this renderer cannot produce, because
`FinalShading.cs.slang` evaluates one reservoir sample per pixel that is *either* a medium scatter or
a surface hit, so there is no surface+medium sum to split -- the guides are **blended** by the
medium's own coverage:

    alpha        = 1 - accuTransmittance          (VolumetricReSTIR "mediumAlpha" output)
    diffuse      = lerp(surfaceAlbedo, sigma_s/sigma_t, alpha)
    specular     = lerp(surfaceSpecular, 0, alpha)     medium has no specular lobe
    roughness    = lerp(surfaceRoughness, 1, alpha)    isotropic; stops RR sharpening smoke to streaks
    normal       = normalize(lerp(surfaceN, -rayDir, alpha))

`-rayDir` is deliberate: an isotropic scatterer has no meaningful orientation, and a camera-facing
normal with roughness 1 reads to RR as "diffuse blob facing the viewer". It costs nothing and has no
failure mode, unlike a density-gradient normal (noisy in the plume core, and risks brick-aligned
artifacts from the 1-voxel GVDB apron).

`sigma_s/sigma_t` is a **uniform, not a texture** -- only density varies spatially in this renderer.

### Effect

| Scene | mse(guides on vs off) | TV | verdict |
|---|---|---|---|
| Plume (alpha ~ 1) | 4.05e-5 | 3.361 -> **3.117** (-7.3%) | real improvement |
| Bistro (alpha ~ 0 mostly) | 0.0129 | within noise | no measurable effect |

Bistro showing nothing is the design working: `lerp(x, y, 0) == x`, and most Bistro pixels have no
smoke in front of them. Note the run-to-run noise floor is ~0.014 -- RR's temporal history plus
jitter makes repeat runs non-deterministic at that magnitude, so anything smaller is not a result.

### Estimator safety

`bias_test_plume.py` gives **mse 0.000100567 before and after** the Stage 2 shader edits -- identical
to every digit. The guide writes consume no random numbers and target only new optional textures.

## Two bugs worth not repeating

**`needGuides` must include the volume flag.** `GenerateFeatures.cs.slang` gates the guide block on
`gOutputDepth || gOutputDeterministicMV || gOutputVolumeGuides`. A DLSS-D graph takes depth and
motion vectors from a GBuffer, so the first two are false there; omitting the third silently skipped
every volumetric write and produced a constant `mediumAlpha`. The symptom was `mse(on, off) == 0`
exactly -- if an A/B is *bit*-identical, the feature is not running.

**Watch backslash escapes when generating scripts.** `"\fire115"` contains a formfeed; the path
became `VolumetricReSTIRDataire115ire115.0198`, the volume silently failed to load, and the scene
rendered with no smoke at all. Always use raw strings for Windows paths.
