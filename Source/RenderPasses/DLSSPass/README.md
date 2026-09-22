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

Two SDKs are vendored, both gitignored, same layout:

| Directory | Tag | Role |
|---|---|---|
| `external/dlss-310.9.1/` (~111 MB) | `v310.9.1` | What the build links and deploys beside the executable. Ships **RR2** (preset F, the new default). |
| `external/dlss-310/` (~106 MB) | `v310.7.0` | The previous DLLs, deployed to `bin/.../dlss_310_7/` for the `Previous310_7` SDK variant. The Ray Reconstruction numbers recorded before 310.9.1 was vendored (2026-09-17) used these. |

```bash
# TAG=v310.9.1 D=external/dlss-310.9.1    or    TAG=v310.7.0 D=external/dlss-310
git clone --depth 1 --branch $TAG --filter=blob:none --sparse \
    https://github.com/NVIDIA/DLSS.git /tmp/dlss
# No-cone with explicit files fetches only what is used; a cone checkout of lib/Windows_x86_64 also
# pulls every static/UWP/khr/vs20xx variant of the libraries and the frame-generation DLL. In Git
# Bash, MSYS_NO_PATHCONV=1 is required, or the leading slashes are rewritten into
# "C:/Program Files/Git/..." and nothing is checked out.
cd /tmp/dlss && MSYS_NO_PATHCONV=1 git sparse-checkout set --no-cone '/LICENSE.txt' '/include/*' \
    '/lib/Windows_x86_64/x64/nvsdk_ngx_d.lib' '/lib/Windows_x86_64/x64/nvsdk_ngx_d_dbg.lib' \
    '/lib/Windows_x86_64/rel/nvngx_dlss.dll' '/lib/Windows_x86_64/rel/nvngx_dlssd.dll'

# then, from the repo root:
mkdir -p $D/include $D/lib/Windows_x86_64/x64 $D/lib/Windows_x86_64/rel
cp /tmp/dlss/include/*.h                                  $D/include/
cp /tmp/dlss/lib/Windows_x86_64/x64/nvsdk_ngx_d*.lib      $D/lib/Windows_x86_64/x64/
cp /tmp/dlss/lib/Windows_x86_64/rel/nvngx_dlss*.dll       $D/lib/Windows_x86_64/rel/
cp /tmp/dlss/LICENSE.txt                                  $D/
```

CMake prefers `dlss-310.9.1`, then `dlss-310`. **If neither exists, it silently falls back to the
packman 3.5.0 SDK**, `FALCOR_HAS_DLSSD` goes OFF, and `DLSSDPass` disappears from the plugin list
rather than failing to build — the failure mode is "unknown render pass", not a compile error.
Watch for this line at configure time:

```
-- DLSS SDK: .../external/dlss-310.9.1
```

`FALCOR_DLSS_SDK_DIR` overrides the search if you keep the SDK elsewhere.

### Selecting the SDK variant at runtime

Both passes take `sdkVariant` (env `VR_SDK` in `run.py`, `capture_orbit.py`,
`compare_denoisers_plume.py`), which sets the NGX feature search path — and therefore which DLL, and
which networks, the presets choose between:

| `sdkVariant` | DLL | RR presets | SR presets |
|---|---|---|---|
| `Current` | beside the executable (310.9.1) | D, E, **F = RR2** (default) | J, K, L, M |
| `Previous310_7` | `dlss_310_7/` (310.7.0) | D (default), E | J, K, L, M |
| `LegacyCNN` (SR only) | `dlss_cnn/` (3.7.20) | — | A..F |

The search path beats the executable directory — verified by the log, which is the only thing to
trust here: `[NGX] loaded nvngx_dlssd.dll version 310.7.0.0 from ...\dlss_310_7\nvngx_dlssd.dll`,
followed on RR by `preset hint N`. A preset the loaded DLL does not implement **does not fail**: NGX
runs that DLL's default and returns a plausible image of the wrong network. F on `Previous310_7` is
exactly that case, and the pass warns about it. One NGX session serves every DLSS pass on a device,
so all DLSS passes in a graph must pick the same variant.

### What changed in 310.9.1, for this integration

* `NVSDK_NGX_RayReconstruction_Hint_Render_Preset_F` went from "Do not use. reverts to default
  behavior" to **"Default model RR2"**; D went from "Default model (transformer)" to "Transformer
  model". Same integer values — only the DLL decides what they mean.
* `nvsdk_ngx_helpers_dlssd.h` is now a deprecated shim for `nvsdk_ngx_helpers_dlssd_d3d.h` (and
  `nvsdk_ngx_helpers.h` is split into `_d3d.h`/`_cuda.h`). No function or struct changed;
  `NGXWrapper.cpp` includes the new name when present.
* New optional RR inputs, none wired here: responsivity mask (F only), depth-of-field guide and
  colour-before-transparency (E and F), alpha upscaling (E and F).
* Needs driver 580+ for RR2. NVIDIA's own table: F allocates ~27% more VRAM than D/E at 1080p on
  RTX 40/50 (154 vs 121 MB).
* `nvngx_dlssd.dll` grew 40.9 → 48.3 MB; both 310.9.1 DLLs are Authenticode-signed by NVIDIA.

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

> **Caveats found 2026-09-18** (details in the RR2 section below). `ImageCompare` **clamps every value
> to [0, 1]** before scoring (constant 0 vs 2 scores 1, not 4), so this table is an LDR-range error,
> not an HDR one; on this scene 2.8% of the reference exceeds 1, mostly directly visible lamps in the
> environment map. And these runs fed RR two broken inputs: `compare_denoisers_plume.py` never set the
> camera's depth range (far plane 0.35), and `DLSSDGuides` handed RR **NaN normals** on the whole
> environment-map background. The RR row barely moves: the 310.7.0 model's output is bit-identical
> with NaN or zero normals, and the depth-range fix changes 94% of its pixels but its error by <1%.
> Re-measured with both fixed (plus NVIDIA's sky albedo) it is 1.555e-4 / 3.55. RR2 is not so
> tolerant: NaN normals change 99.98% of its pixels.

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

> **Superseded (2026-09-18):** with the scene time pinned (`vr.pin_clock`) or a static scene, repeat RR
> runs are **byte-identical** -- 300/300 orbit frames, both SDK versions -- even though the frame-time
> hint RR receives is wall-clock. The spread above most likely came from wall-clock-driven scene time,
> which this note predates. The noise floor for a like-for-like A/B is now exactly zero.

### Estimator safety

`bias_test_plume.py` gives **mse 0.000100567 before and after** the Stage 2 shader edits -- identical
to every digit. The guide writes consume no random numbers and target only new optional textures.

## Bugs worth not repeating

**Never hand RR a NaN guide.** A pixel with no geometry (sky, environment map) is cleared to zero in the
G-buffer, and the medium blend's `normalize(lerp(0, mediumNormal, 0))` turned that into a NaN normal:
0.003% of Bistro, but 79% of the plume scene. The 310.7.0 model shrugged it off; RR2 darkened the
whole background ~12% and scored 2.7x worse against ground truth. `DLSSDGuides` now writes NVIDIA's
documented sky guides there (`skyDefaults`, `VR_RR_SKY=0` to reproduce the old ones bit for bit).
Check guides for NaN (`VR_V11_INPUTS=1` captures them) before believing any RR result.

**`needGuides` must include the volume flag.** `GenerateFeatures.cs.slang` gates the guide block on
`gOutputDepth || gOutputDeterministicMV || gOutputVolumeGuides`. A DLSS-D graph takes depth and
motion vectors from a GBuffer, so the first two are false there; omitting the third silently skipped
every volumetric write and produced a constant `mediumAlpha`. The symptom was `mse(on, off) == 0`
exactly -- if an A/B is *bit*-identical, the feature is not running.

**Watch backslash escapes when generating scripts.** `"\fire115"` contains a formfeed; the path
became `VolumetricReSTIRDataire115ire115.0198`, the volume silently failed to load, and the scene
rendered with no smoke at all. Always use raw strings for Windows paths.

---

# RR2 (DLSS 310.9.1, preset F) vs the previous RR (310.7.0, preset E)

Measured 2026-09-17/18 on an RTX 5070 Laptop GPU, driver 610.74. "Previous" is exactly what every
earlier RR number here used: the 310.7.0 DLL, preset E (`DLSSDPass`'s default). Both run from one
binary, selected by `sdkVariant` (see above). Scripts: `outputs/m_rr2*.py`, `outputs/video_rr2.py`,
`outputs/sheet_rr2.py`; side-by-side video `outputs/video/rr_vs_rr2*.mp4`.

**Verdict: not a quality upgrade for this renderer -- a speed and sharpness trade.** RR2 is 12%
cheaper and resolves more structure in the smoke, but it is slightly less stable and slightly less
accurate per pixel than preset E on both scenes, and it dims the brightest highlights. `preset E`
stays the default. Upgrading the SDK itself costs nothing: 310.9.1's E is bit-identical to 310.7.0's.

## Controls -- all exact, so every difference below is the network

| check | result |
|---|---|
| pre-upgrade build vs new build running `Previous310_7` + E | 300/300 orbit frames byte-identical PNGs |
| repeat runs, either version | 300/300 byte-identical (the noise floor is exactly 0) |
| 310.9.1 E vs 310.7.0 E | 300/300 byte-identical -- E did not change |
| 310.9.1 `Default` vs explicit F | 300/300 byte-identical -- RR2 is the new default |
| `VR_RR_SKY=0` vs the pre-fix guides | bit-identical EXR (plume, RR2) |

## Cost (bistro orbit, 1080p DLAA, 300 frames, 2 interleaved runs each)

| | `DLSSDPass` GPU, median | frame, wall clock |
|---|---|---|
| 310.7.0 E | 7.78 / 7.80 ms | 143.9 / 144.7 ms |
| 310.9.1 E | 7.80 / 7.83 ms | 144.0 / 144.2 ms |
| **310.9.1 F (RR2)** | **6.85 / 6.83 ms** | 142.5 / 142.6 ms |

RR2 is 0.96 ms (12%) cheaper. From Falcor's profiler (`capture_orbit.py VR_TIME=1 VR_PASS_TIMES=1`);
a difference this size is invisible in the wall clock. NVIDIA's own table has F slightly *slower*
than D/E in Performance mode on desktop RTX 50 -- at DLAA here it is faster than E (D not measured).

## Stability and detail (bistro orbit, 300 frames at 1080p, shipped config, `m_rr2.py`)

| | s=32 | plume | surfaces | detail | plume detail | mean |
|---|---|---|---|---|---|---|
| previous RR (E) | **8.97** | **14.55** | **26.65** | 0.0628 | 0.0490 | 0.1971 |
| RR2 (F) | 9.29 (+3.6%) | 15.27 (+4.9%) | 27.33 (+2.6%) | 0.0672 (+7%) | 0.0537 (+10%) | 0.1933 (-1.9%) |

37% of pixels differ by more than 2/255. At 1:1 RR2 visibly resolves more billow structure inside the
smoke; surfaces differ mostly at edges. "Detail" cannot tell detail from noise -- the ground truth
below says the extra structure is not closer to the truth.

## Accuracy against converged references

**Plume** (`compare_denoisers_plume.py`, static, frame 200 vs 3000 spp, env-lit so the reference
converges). relMSE on images divided by the reference mean; `[0,1]` columns via ImageCompare, which
clamps (see caveat above); bias = mean ratio over pixels below 1.

| | relMSE | relMSE, jittered ref | MSE[0,1] | MAPE[0,1] | bias |
|---|---|---|---|---|---|
| raw ReSTIR | 2.59e-2 | 2.68e-2 | 1.51e-3 | 10.36 | 1.005 |
| DLAA, previous RR | **1.69e-3** | **1.99e-3** | **1.56e-4** | **3.55** | 1.006 |
| DLAA, RR2 | 2.05e-3 | 2.42e-3 | 2.02e-4 | 3.82 | 1.001 |
| Balanced 34%, previous RR | **1.80e-3** | **1.73e-3** | **1.40e-4** | 3.78 | 1.002 |
| Balanced 34%, RR2 | 1.90e-3 | 1.90e-3 | 1.46e-4 | **3.62** | 0.994 |

**Bistro** (`run.py VR_HOLD_AT=200`, 12000-sample jittered reference, `m_rr2_bistro.py`). Per-pixel
statistics, because the mean relMSE is decided by ~0.1% of pixels in smoke lit by the small magenta
bulb, where even the 12000-sample reference is still visibly noisy.

| | median rel. error | p90 | relMSE, worst 0.1% trimmed | highlight bias (top 0.1%) |
|---|---|---|---|---|
| raw ReSTIR | 0.0645 | 0.258 | 0.258 | +2% |
| DLAA, previous RR | **0.0184** | **0.0726** | **0.0162** | -20% |
| DLAA, RR2 | 0.0217 | 0.0851 | 0.0197 | -50% |
| Balanced 34%, previous RR | **0.0229** | **0.0895** | **0.0175** | -52% |
| Balanced 34%, RR2 | 0.0251 | 0.0959 | 0.0211 | -28% |

Surfaces alone: median 0.0160 vs 0.0194 (RR2 +21%); medium alone: trimmed relMSE 0.089 vs 0.102
(+14%). Note the previous RR at 34% of the pixels is about as accurate as RR2 at 100%. RR2's
untrimmed mean relMSE is 15x lower -- that is the unconverged reference, not a visible defect: the
previous RR's worst pixels are exactly where the reference is still speckled, and they look the
same as RR2's.

## RR2 needs valid guides; the previous model did not care

Before the `DLSSDGuides` sky fix, the plume told the opposite story -- RR2 2.7x worse than E, the whole
environment-map background ~12% dark. Cause: NaN normals on every no-geometry pixel (see "Bugs worth
not repeating"). DLAA relMSE on the plume through each fix:

| inputs | previous RR | RR2 |
|---|---|---|
| as recorded before (depth range unset, NaN normals, sky albedo 0.01) | 1.99e-3 | 6.99e-3 |
| + camera depth range set (`compare_denoisers_plume.py`) | 1.99e-3 | 5.38e-3 |
| + normals 0 instead of NaN | 1.99e-3 (bit-identical) | **1.91e-3** |
| + sky diffuse 0.5 (NVIDIA's value; the shipped fix) | 1.69e-3 | 2.05e-3 |

The normal fix is what matters, and only to RR2. The albedo half is NVIDIA's documented value but
measures mixed: it moves E's relMSE -15% and its MAPE +3%, and costs RR2 ~7% against normals alone.
Also ruled out on the way, with the pre-fix guides: feeding RR the estimator's depth (far plane off the
medium, expected scattering depth in it) instead of the G-buffer's zeros -- no help to either model
(`VR_V11_RR_DEPTH=estimator`; E 1.99e-3 -> 1.99e-3, RR2 5.38e-3 -> 7.15e-3).

## The halo around the smoke in motion

A smoke-coloured haze around the plume's silhouette whenever the camera moves -- both versions, gone
once the camera stops. It had two causes, fixed in turn; the second is the one that remained visible.

### 1. RR was given the wall's motion

RR's motion vectors (and depth) came from GBufferRaster, which contains only surfaces, so at every
smoke pixel RR was told the pixel moves like **the wall behind the smoke**. Orbiting the plume, the
smoke barely moves on screen while that wall sweeps past, and RR dragged the smoke's history along
with the wall.

The estimator already writes motion vectors (and depth) at the medium's expected scattering depth,
the surface hit elsewhere -- TAA_LDR has used them since the volume-mvec change. RR now does too
(`VR_RR_VOLMV`, on by default; `VR_RR_VOLMV=0` restores the G-buffer's). Bistro orbit at 960x540
(`Scripts/record_look.py`), instability lower = steadier:

| | plume | whole | surfaces | detail |
|---|---|---|---|---|
| previous RR (E), G-buffer mvec | 16.83 | 9.74 | 27.19 | 0.0471 |
| previous RR (E), volume mvec | **15.51** | **9.48** | **27.08** | **0.0484** |
| + volume depth (`VR_RR_VOLDEPTH=1`) | 15.45 | 9.45 | 27.04 | 0.0482 |
| RR2 (F), G-buffer mvec | 17.74 | 10.10 | 27.80 | 0.0506 |
| RR2 (F), volume mvec | **16.50** | **9.83** | **27.62** | **0.0514** |

Both gain about 7-8% in the plume, so the RR2-vs-E ranking above stands; the tables above were
measured with the G-buffer mvec. Depth adds ~0.4% and stays opt-in.

That fixed the smoke's own smear, not the halo: a smooth veil ~50 px wide still lay over the ground
beside the silhouette while moving.

### 2. The ground was given the smoke's motion

The estimator's depth/mvec switch to the medium's expected scattering depth wherever the primary ray
meets **any** medium. So the plume's whole faint outer fringe -- mid-orbit, 28k pixels, 11k of them
below 0.1% coverage, i.e. pixels that show the ground almost unattenuated -- carried the smoke's
motion, 6.9 px/frame away from the ground's. RR reprojected that ground as if it were smoke and laid
smoke history over it. The veil is not in the raw input, and neither volume depth nor TAA off
changes it.

Fix: depth and mvec follow the medium only where the medium supplies at least a given share of the
pixel's **light** (estimator property `mGuideMediumMinShare`; `vr_graph` sets 5% when RR takes the
estimator's mvec, `VR_RR_MV_MIN_SHARE`, 0 restores). The share is `a*Lm / (a*Lm + T*Ls)` with the
pixel's own coverage `a` and transmittance `T` (exact, from the march) and the two layers' local
brightness from the previous frame: a small guide-only pass (`GuideLightStats.cs.slang`) keeps a running
average of (medium light, coverage, surface light, transmittance) using the same volume/surface
classification as final shading's split, and its mips give neighbourhood means, whose ratios are the
medium's light per unit coverage `Lm` and the surface's per unit transmittance `Ls`. The estimator's
own default stays 0, which is right for NRD's volume half: it denoises only the medium's light.

**Volumetric ReSTIR itself is untouched.** The pass reads finished results and nothing in the estimator
reads what it writes. Verified over 60 frames of motion: the estimator's `accumulated_color` (HDR) and
`mediumAlpha` are byte-identical with the rule on and off; only `mvec`/`linearZ` differ, and only on
pixels whose ray meets the medium.

Why light and not coverage: a coverage threshold tuned on one scene is wrong on another, because the
same coverage is most of a pixel's light where the medium outshines what is behind it and almost none
where it does not. First measured the hard way -- 2% coverage was best on bistro, and I first explained
it with "the lit smoke outshines the ground ~50x", which the estimator's own light split refuted (~2x
per unit coverage; the smoke's light overtakes the ground's only at 10-30% coverage). Stop-and-go
(`record_look.py`, `VR_RECORD_STOPS=3`), mean |frame arriving at a stop - same pose 5 s later| /255 over
the fringe (0 < coverage < 0.9; `outputs/m_halo_alpha.py`), previous RR (E), four scenes:

| rule | bistro (night, lamp-lit smoke) | plume, night env | plume, daylight env | explosion (emissive) |
|---|---|---|---|---|
| any medium (before) | 6.34 | 2.91 | 2.87 | 4.78 |
| coverage 2% (tuned on bistro) | 5.16 | 2.96 | 2.75 | 4.56 |
| **light share 5%** | **5.09** | **2.89** | 2.72 | **4.49** |
| light share 10% | 5.13 | 2.92 | 2.68 | **4.49** |
| light share 20% | 5.32 | 3.02 | **2.63** | 4.56 |

5% is the one setting that helps, or is neutral on, every scene; the bistro-tuned coverage threshold
makes the night plume worse than doing nothing. Bistro by coverage (ground beside the fringe 3.1):

| | 0-1% | 1-10% | 10-30% | 30-50% | 50-70% |
|---|---|---|---|---|---|
| E, before | 5.61 | 6.31 | 6.53 | 7.41 | 7.98 |
| E, light share 5% | **3.39** | **4.78** | 6.58 | 7.93 | 8.26 |
| RR2, before (ground 3.9) | 5.60 | 6.85 | 9.39 | 11.84 | 12.56 |
| RR2, light share 5% (ground 4.1) | **4.71** | **6.23** | 9.45 | 11.98 | 12.43 |

Orbit instability (`outputs/m_look_orbit.py`, lower = steadier): whole frame E 9.47 -> 9.43, RR2 9.82
-> 9.69; surfaces 27.05 -> 27.02 and 27.59 -> 27.45; the central plume columns E 15.50 -> 15.77 (+1.7%),
RR2 16.49 -> 16.47. `VR_RR_MV_SHARE_STATS=0` ignores the statistics, which turns the threshold into a
plain coverage threshold (reproduces the coverage rows byte for byte). The two plume variants and the
explosion are new `vr_graph` scenes for this test: `VR_PLUME_ENV=lakeside_8k.hdr` for daylight,
`VR_SCENE=explosion` (the paper's LGHExplosion, which also needed the emission fix under "Found along
the way"). Videos: `outputs/video/halo_fix_before_after_{E,RR2}.mp4`.

### 3. The rim dims while moving: the estimator, not RR

With the veil gone, the smoke's thin rim still came out dimmer while the camera moved -- the lamp-lit
glow at the silhouette disappears, and returns seconds after stopping. Neither a second RR for the
medium (`VR_RR_LAYERS=1`) nor a motion-compensated pre-accumulation of that layer
(`MediumAccumulation`) fixed it, because the light was already missing from RR's INPUT: the
estimator's temporal reuse loses thin medium at a moving silhouette (VolumetricReSTIR/README.md,
"Bias-sensitive configuration"). `VR_TR_INDEPENDENT=1` switches on the estimator-side fix. Bistro stop
3, lanterns frozen, 8 seeds, one RR, vs a 256-frame truth (typical pixel, thin / edge):

| | moving | still |
|---|---|---|
| as shipped | 0.87 / 0.89 | 1.02 / 1.02 |
| `VR_TR_INDEPENDENT=1` | **1.03 / 1.00** | 1.02 / 1.02 |
| two-layer RR + pre-accumulation, as shipped | 0.81 / 0.80 | 1.03 / 1.01 |
| two-layer RR + pre-accumulation, `VR_TR_INDEPENDENT=1` | 0.94 / 0.91 | 1.03 / 1.01 |

Adding `VR_TR_LIGHT_SHARE=1` makes that fix follow whichever layer supplies the pixel's light, using the
same light-share statistics as the halo rule, which buys back part of the noise it costs (typical moving
pixel 1.04 / 1.01 of the true light). It changes the estimator, so it is off by default. The price is a
noisier input at a moving silhouette:
RR's output there is about as noisy as before (per-pixel spread 0.13 / 0.22 vs 0.12 / 0.21 of the
light), but its few bright blotches get slightly stronger (regional mean moving/still 1.31 vs 1.27 at
thin smoke). The two-layer path ends up smoother at the moving edge (0.12 / 0.14) but still dim, and
with a proper truth it is no longer the more accurate still image either (edge regional mean 0.89 vs
0.93 for one RR; an earlier comparison used a truth biased low by the moving frames).

## Found along the way

* `ImageCompare` clamps to [0, 1] -- the table near the top of this section is LDR-range.
* `Scripts/*` claimed Falcor's profiler is unreachable from Python. It is `m.profiler`.
* `deploycommon.bat` looked for `dlss-legacy-37` under `external/packman/`, so `dlss_cnn/` was never
  deployed on a fresh build directory; it had been populated by hand. Fixed.
* Emissive volumes rendered as plain smoke. The baked-volume loader (`SceneGVDB.cpp`) set the emission
  flag but never built the blackbody LUT that `Emission()` samples, and the LUT file itself was not
  carried over into this Falcor's `data/`; both fixed (`data/LUT/`, from `legacy/`), and a missing LUT
  is now an error instead of silent black. The paper's `temperatureScale` 750 still maps the
  LGHExplosion bake below the LUT's first non-zero row (LeScale 1 and 100 render byte-identical), so
  the explosion scene uses 7500.
* `skylight-dusk.exr` crashes `setEnvMap` in this build (the paper's explosion sky); the explosion scene
  uses `satara_night_8k.hdr`.
* `VolumetricReSTIR::setProperties` dereferenced the scene unconditionally: setting a property while a
  graph is built crashed without a message, and any runtime set on bistro would have crashed on its
  missing environment map. Guarded.
