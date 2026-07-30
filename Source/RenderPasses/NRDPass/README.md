# NRDPass

Wraps NVIDIA Real-Time Denoisers (NRD). Builds against **either** NRD v3.1 or v4.17.3 from one
source tree, selected at configure time:

```
cmake -S . -B build/windows-vs2022 -DFALCOR_USE_NRD4=ON    # v4.17.3 (vendored)
cmake -S . -B build/windows-vs2022 -DFALCOR_USE_NRD4=OFF   # v3.1 (packman) -- default
```

Both are kept so the two can be A/B'd on identical scenes. The differences are large enough that
this comparison is itself a result; see [Measurements](#measurements).

`external/CMakeLists.txt` exports `FALCOR_NRD_DIR`, which `build_scripts/deploycommon.bat` uses to
copy the matching DLL **and** shader tree. The directory is passed in rather than probed, because
both SDKs can be vendored at once and only CMake knows which one the C++ was compiled against — a
DLL/shader mismatch compiles fine and then denoises incorrectly.

`SpecularReflectionMv` and `SpecularDeltaMv` are **v3.1-only**. v4 deletes those denoisers, their
settings structs, and the `OUT_REFLECTION_MV` / `OUT_DELTA_MV` / `IN_DELTA_*_POS` resource types.
Selecting them under v4 throws. `scripts/PathTracerNRD.py` is therefore v3.1-only.

## Why v4 is vendored rather than taken from packman

packman ships v3.1 only. v4.17.3 is built from source into `external/nrd-4/` (gitignored). Two
local patches are applied to the vendored copy, each marked in-file with a `FALCOR LOCAL PATCH`
banner:

* **135 HLSL character literals converted to ASCII codes** — 5 in `Shaders/ml.hlsli`, 130 across
  `REBLUR_Validation.cs.hlsl` / `RELAX_Validation.cs.hlsl`. Slang does not accept HLSL character
  literals. Falcor compiles NRD's HLSL through Slang rather than using NVIDIA's shipped DXIL, so
  these files go through a compiler NVIDIA does not test against. Debug-only paths; behaviour is
  unchanged. The originals are kept beside each replacement as `/* '-' */` comments, so a grep for
  character literals in this file still matches — check for the `FALCOR LOCAL PATCH` banner instead.
* `ml.hlsli` is vendored **flat** into `Shaders/`, not `Shaders/Include/` — v4's shaders `#include
  "ml.hlsli"` as a sibling. (MathLib is a FetchContent dependency of NRD's own build and otherwise
  lives only in a temp directory.) A second, **unpatched** copy under `Shaders/Include/` was left over
  from the first vendoring attempt and has been deleted: nothing referenced it, but it shipped to the
  output directory, and an unpatched `ml.hlsli` that can satisfy the same `#include` is precisely the
  failure `deploycommon.bat`'s `/purge` exists to prevent. If MathLib is ever re-vendored, put it at
  `Shaders/ml.hlsli` and re-apply the patch — do not recreate `Include/`.

## Breaking changes that do not announce themselves

Found by running, not by diffing headers. Recorded because each compiles cleanly and fails quietly.

1. **`NRD_INTERNAL` must be defined.** v4 gates the permutation macros (`DIFF`, `SPEC`, `RADIANCE`,
   `SH`) behind it. Without it, `NRD_SIGNAL=DIFF` expands against undefined symbols, so `NRD_DIFF`
   and `NRD_SPEC` both evaluate false and every shader compiles with **no signal selected**.
2. **The encoding macros were renamed.** `NRD_USE_OCT_NORMAL_ENCODING` / `NRD_USE_MATERIAL_ID` are
   silently ignored by v4, which reads `NRD_NORMAL_ENCODING` / `NRD_ROUGHNESS_ENCODING` from
   `NRDConfig.hlsli` instead. Passing the v3.1 names to a v4 build is a no-op.
3. **`R10G10B10A2_UNORM` means something different.** v3.1: `.xy` = octahedral normal, `.z` =
   roughness. v4: `_NRD_EncodeNormalRoughness101010` packs normal *and* roughness together into the
   30-bit field (`.z` carries roughness with `n.z`'s sign folded into its sign) and puts
   materialID/3 in the A2 field. Nothing validates this. A mismatch makes every edge-stopping weight
   garbage, so the denoiser blurs across depth and normal discontinuities and the frame comes out
   uniformly smeared. `NRDAdapter.cs.slang::encodeNormalRoughness` branches on `NRD_V4` and **must**
   stay in sync with the `NRD_NORMAL_ENCODING` value set in `NRDPass::createPipelines`.
4. **SRVs and UAVs are separate register classes.** v4 removed `ResourceRangeDesc::baseRegisterIndex`,
   so registers must be derived — but `t#` and `u#` each restart at `resourcesBaseRegisterIndex`
   (RELAX TemporalAccumulation binds `t0..t12` alongside `u0..u2`). A single shared counter puts the
   UAV range at `u13`; D3D12 then rejects the pipeline with `E_INVALIDARG`, surfacing confusingly
   late as a failure inside `ComputeStateObject::getNativeHandle`.
5. **Two register spaces** where v3.1 had one implicit space: resources in space 0, constant buffer
   and samplers in space 1.
6. `PackRadiance.cs.slang`: v3.1's nested include path is gone;
   `RELAX_FrontEnd_PackRadianceAndHitDist` lost `sanitize`'s default;
   `REBLUR_FrontEnd_PackRadianceAndHitDist` → `...PackRadianceAndNormHitDist` with `hitDistParams`
   `float4` → `float3`.

Further silent-failure traps (calling convention, `motionVectorScale[3]`, the `*Prev` resolution and
jitter fields, `minMaterialForX` inverting `enableMaterialTestForX`, `historyFixBasePixelStride`
replacing `disocclusionFixMaxRadius` at the same default of 14) are annotated at their use sites in
`NRDPass.cpp`.

## SH mode

Complete and round-trip verified. `VR_NRD_SH=1` selects it; `VR_NRD_SH_RESOLVE` picks the resolve.

```
NRDAdapter (SH_MODE=1)  ->  SH0 = {radiance, hitDist}, SH1 = {dir * luminance, 0}
NRDPass                 ->  RELAX_DIFFUSE_SH  ->  ResolveSh.cs.slang  ->  radiance
```

The pair is **internal**: the pass emits ordinary radiance on the same pin the radiance path uses, so
nothing downstream changes. Exposing coefficients would let `ModulateIllumination` multiply albedo
into SH coefficients — which produces something that looks like an image and is not one.

Three things that are easy to get wrong, each of which yields a plausible picture rather than an error:

1. **The two ends of the API are in different colour spaces.** `RELAX_FrontEnd_PackSh` writes SH0 as
   linear **RGB**; `RELAX_BackEnd_UnpackSh` reads it as **YCoCg** (`c0` + `chroma`). RELAX converts
   internally. The resolve must go through the back-end unpack, and the bypass path — which feeds the
   front-end pair straight in, with no NRD in between — has to do that conversion itself
   (`gSh0IsLinearRgb`).
2. **The DC resolve must not call `NRD_SH_ResolveDiffuse` with `c1 = 0`.** That still applies its
   `k0 = 1/π` factor, which converts an irradiance-like quantity into outgoing radiance off a diffuse
   **surface**. A medium has no surface, so the DC path takes `Y = c0` directly.
3. **SH1 needs a light direction, not a normal.** It is the direction incoming *radiance* arrives
   from, so `mediumNormal` is not a substitute. `VolumetricReSTIR.lightDir` supplies it, and the input
   is declared **mandatory** in SH mode — an unbound one would pack an all-zero SH1, which reads as
   "no directional information anywhere" and denoises without complaint.

**Two resolve semantics, both selectable, because the right one is not obvious.** Both scenes use an
**isotropic** phase function (`g = 0`), for which outgoing radiance is the uniform spherical average —
the DC term. NRD's own resolve instead evaluates a cosine lobe about a surface normal. `Dc` is the
physically defensible choice here; `Cosine` is NVIDIA's intended usage. If the two tie, SH's
directional term is buying nothing for isotropic media — a result, not a failure.

**Round-trip check.** With the denoiser bypassed, `NRDPass` resolves from the *adapter's input* pair
rather than blitting, making it an exact identity test of the transform independent of NRD:

| | vs the radiance path |
|---|---|
| SH pack → resolve (`Dc`) | **3.02e-11** — four orders below the 1.7e-07 noise floor |
| SH pack → resolve (`Cosine`) | 1.36e-02 — as expected from its 1/π factor |

## Guards

Every bug in this port failed *silently* — a smeared frame, an empty texture, a run that writes
nothing — so each one that could recur elsewhere now has a check that fails loudly instead. All four
were verified by deliberately breaking the thing they guard, not just by reading them.

| guard | protects against | verified by |
|---|---|---|
| `NRDPass::reinit` compares `GetLibraryDesc()->normalEncoding` / `roughnessEncoding` against `kNrdNormalEncoding` / `kNrdRoughnessEncoding` | the three-way guide-layout disagreement (shader macros / NRDAdapter packing / linked binary) that produced the smeared frame | setting the constant to 3 — throws `NRD was built for normal encoding 2 but the shaders and NRDAdapter use 3` |
| `NRDAdapter/CMakeLists.txt` fails configure if `FALCOR_USE_NRD4` is ON but `FALCOR_HAS_NRD4` never reached that scope | the adapter compiling the v3.1 packing against a v4 NRDPass, with no build error, if `add_subdirectory` ordering changes | reasoning only — `FALCOR_USE_NRD4` is a cache option and always visible, unlike the `PARENT_SCOPE` variable |
| `advance_and_hold` renders one frame and refuses to continue if `clock.frame` did not advance, then checks `clock.time` did *not* | the `clock.pause()` bug: capture and `exitFrame` both wait on `clock.getFrame()`, so a frozen counter means the run accumulates forever and writes nothing | pausing the clock before the call — raises `the frame counter is frozen at 0 after holding` |
| `add_denoiser` refuses `VR_NRD_VOLMV=1` unless the estimator reports `mMotionVecMode == "Deterministic"` | an unwritten `mvec` output, which NRD reads as "nothing moved anywhere" — a temporal denoiser that silently never reprojects | valid config accepted; the mode is read back off the pass, since an unrecognised value warns and leaves the old mode in place |

The encoding constants exist so the value is written once rather than repeated per call site, and the
runtime check compares against *them* rather than a literal — so editing the constant cannot drift
away from the check meant to police it.

## Settings that differ for volumetric input

NRD is built for surface path tracing. Two of its passes assume things that do not hold for a
participating medium, and both are disabled in the constructor with the measurements that justify
them.

* **Pre-pass off** (`diffusePrepassBlurRadius = 0`). v4 sizes the kernel as
  `prepassBlurRadius * saturate(hitDist / frustumSize)`, assuming `hitDist` is a short
  secondary-bounce length. We supply the expected *scatter* distance through the medium, which is
  the same order as the frustum, so the factor saturates to 1 and the pre-pass becomes a
  full-radius blur over the whole frame. Response is monotonic in the radius (30 → 2.009e-02,
  16 → 1.091e-02, 8 → 5.307e-03, 4 → 2.325e-03, 1 → 1.209e-03, 0 → 1.072e-03), so there is no
  useful regime, not merely a different optimum.
* **History reconstruction off** (`historyFixFrameNum = 0`). It invents a signal for pixels with no
  temporal history by blurring a 5×5 kernel at 14-pixel stride. That trade is right when the
  alternative is a bare 1-spp surface estimate; here a history reset still leaves a converged
  multi-frame VolumetricReSTIR estimate, which the blur then discards.
* **Antifirefly on** — new for RELAX in v4 (v3.1 exposed it for REBLUR only), and our input is
  1-spp volumetric radiance.

This is also the only route by which hit distance reaches RELAX in v4: with the pre-pass off,
`VR_NRD_HITDIST=0` is byte-identical. v3.1's RELAX ignored hit distance entirely.

`NRD4_*` environment variables (`NRD4_PREPASS`, `NRD4_HISTFIX`, `NRD4_ANTIFIREFLY`, `NRD4_ATROUS`,
`NRD4_MAXACCUM`, `NRD4_FASTACCUM`, `NRD4_PHILUM`) override these without a rebuild, so the numbers
above stay reproducible and a regression can be bisected against NRD's own defaults.

RELAX settings are **not** round-tripped through `Properties` under v4: the three v3.1 structs were
merged into one `RelaxSettings` whose fields were renamed, retyped and re-defaulted, so accepting
v3.1-era property names would apply v3.1 tuning to a different filter.

## Measurements

MSE against the converged references, via
`Source/RenderPasses/VolumetricReSTIR/Scripts/sweep.py --no-rr`. Lower is better.

| scene | raw ReSTIR | OIDN GPU | OptiX | NRD v3.1 | NRD v4.17 |
|---|---|---|---|---|---|
| plume | 1.498e-03 | 3.329e-04 | 4.948e-04 | **6.504e-04** | 1.059e-03 |
| bistro † | 1.022e-06 | 6.258e-05 | 6.165e-05 | 1.189e-05 | 7.707e-05 |

† Not a quality ranking — see below.

**v4 scores worse than v3.1 on plume** — 1.6×. The cause is now understood, and it is a property of
the benchmark rather than of the port; see below. Treat the ranking above as measuring something
other than denoising quality.

### The root cause: NRD was fed `viewZ = 0` everywhere

Everything in the next section is still true about how RELAX works, but it was not the whole story,
and the numbers above were taken while a more basic fault was in play.

**`GBufferRaster` writes nothing on the plume scene.** It is lit by an environment map over a bare
plane, with essentially no rasterizable geometry in view, so its `linearZ` output is **all zeros** —
measured, every channel, every pixel. That is what the NRD graph was feeding `IN_VIEWZ`.

A zero depth reconstructs every pixel to the camera origin, so RELAX's reprojection is degenerate and
its history never accumulates. With history stuck at one frame, `Var = E[L²] − E[L]²` is **exactly**
zero, the A-trous luminance weight collapses (see below), and every temporal setting becomes inert.
Measured on the animated plume, all **byte-identical**:

| knob | result |
|---|---|
| `phiLuminance` 2 vs 32 | 0 |
| `diffuseMaxAccumulatedFrameNum` 30 vs 1 | 0 |
| surface vs volume motion vectors | 0 |

`VR_NRD_VIEWZ=restir` feeds the estimator's depth instead. `phiLuminance` 2 vs 32 then differs by
**3.51e-03** — RELAX filtering for the first time — and the motion-vector choice starts to matter too
(1.86e-05, where it had been byte-identical).

**This invalidates an earlier note** that lived in `vr_graph`: that the estimator's scatter depth
scored *worse* than feeding nothing (8.54e-4 vs 6.93e-4). That was measured on a static scene, in the
regime where NRD declines to filter at all, so it compared noise rather than depth quality.

### Why the variance estimator amplified the problem

RELAX decides how hard to filter from a **temporally** estimated variance. `RELAX_TemporalAccumulation`
stores `luminance(L)²` per frame and `RELAX_AtrousSmem` recovers `Var = E[L²] − E[L]²`; the A-trous
luminance weight is then

```
phiLIlluminationInv = 1.0 / max(1e-4, gDiffPhiLuminance * sqrt(centerDiffuseVar))
```

When `Var → 0` this collapses to `1/1e-4` **regardless of `gDiffPhiLuminance`**, so every neighbour
weight goes to zero and A-trous becomes a no-op that is completely insensitive to its own settings.

That is exactly our situation, and more deeply than `VR_FREEZE_ANIM` suggests: **the plume scene is
static by construction.** `vr_graph.load_plume` loads a *single* VDB frame (`fire115.0198`) with
`hasVelocity=False` and a pinned camera — its own docstring says "Static plume on a bare ground
plane". So nothing in it moves whether the freeze flag is set or not. VolumetricReSTIR additionally
does temporal reservoir reuse, which stabilises the estimate further. NRD sees a signal that does not
change over time, concludes it is already converged, and declines to filter — even though the frame
still carries the spatial noise the metric is measuring.

This means the scene cannot exercise a temporal denoiser at all, and no reference workflow fixes that.
**Ranking NRD needs a scene that actually moves** — a scripted camera path, or a VDB sequence with a
velocity grid — not merely a better reference for a static one.

Demonstrated directly (plume, `diffusePhiLuminance` 2 vs 32, everything else equal — difference
between the two outputs):

| | 2 vs 32 |
|---|---|
| `VR_FREEZE_ANIM=1` (frozen) | 1.56e-14 — numerically identical, A-trous inert |
| `VR_FREEZE_ANIM=0` (animating) | 2.83e-05 — A-trous live and responding |

Consequences, and they matter for how the whole comparison is read:

* **v3.1 did not beat v4 by denoising better.** v3.1's gain came from its pre-pass blur, which is
  applied *unconditionally* rather than being variance-gated. v4's pre-pass is unusable here for an
  unrelated reason (hit-distance saturation, above), and every other v4 spatial filter is
  variance-gated — so v4 correctly configured does almost nothing on a frozen scene.
* **The frozen benchmark penalizes NRD specifically.** OIDN, OptiX and DLSS-RR are not gated on a
  temporal variance estimate, so they filter regardless. `VR_FREEZE_ANIM=1` is right for building
  *references* (an unfrozen accumulation drifts and never converges) but it removes precisely the
  signal NRD depends on.
* This cannot be fixed by unfreezing the denoiser runs alone: the reference is a converged average of
  one scene state, so the run under test has to be that same state. A fair measurement needs a
  **per-frame reference** — converge frame *N* with the animation at frame *N*, then score the
  denoiser's frame *N*.

### The per-frame reference workflow (built, verified, not yet used to re-rank)

`VR_HOLD_AT=N` implements the above (`vr_graph.advance_and_hold`). It animates to frame *N* and then
holds that state. The accumulator is explicitly reset on hold, because everything summed during the
approach is an average over *different* states.

How it holds matters, and the two obvious ways are both wrong:

* `scene.animated = False` also stops the scene update the emissive LightCollection and the volume
  rely on, leaving a frame lit only by directly-visible emitters — which reads as a lighting bug.
* **`clock.pause()` silently breaks capture.** `Clock::tick` only calls `step()` when not paused, and
  `step()` is what advances `mFrames` — while both FrameCapture and `clock.exitFrame` trigger off
  `getGlobalClock().getFrame()`. Pausing freezes the exact counter the capture is waiting for, so the
  run accumulates and writes **nothing**, with no error in the log. This was the first
  implementation; it reported success and produced no reference.

What works: reach frame *N* with the framerate pinned (deterministic), then drop to real-time mode
with `timeScale = 0`. The two have to move together — in `step()` a pinned framerate makes time a pure
function of the frame count and ignores `timeScale`, whereas at `framerate = 0` time becomes
`timer.delta() * scale + time.now`, which at `scale = 0` holds at the value just reached. Scene time
stops, the frame counter keeps running, capture fires.

```
reference:  VR_REFERENCE=1 VR_HOLD_AT=200 VR_HOLD_SAMPLES=3000   # captures at 200+3000
denoised :  VR_DENOISER=nrd VR_HOLD_AT=200                       # captures at 200, still animating
```

`VR_FRAMERATE` (default 60) pins `time = frame / framerate`. Without it animation runs on the wall
clock, so "frame 200" is a different scene state on every machine and every run — the same hazard that
once produced a Bistro capture pointing at the night sky.

Verified on plume:

| comparison | difference |
|---|---|
| same hold frame, two separate runs | 1.66e-07 |
| frame 100 vs frame 40 | 2.14e-04 |

The first is the **measurement noise floor** — run-to-run RNG, three orders of magnitude below the
1e-3…1e-5 differences being compared, so it does not threaten any conclusion here. The second confirms
the animation actually advances, which is what supplies NRD its temporal variance.

Two VS Code tasks drive it: *Per-frame ref: plume, hold at frame 200* and *Per-frame A/B: plume + NRD,
animating to frame 200*.

**What it produced so far, and why it does not yet settle anything.** A 960×540 reference held at frame
200 (not comparable to the 1080p frozen numbers above):

| run | MSE |
|---|---|
| OIDN GPU | 3.510e-04 |
| OptiX | 4.311e-04 |
| raw ReSTIR | 1.956e-03 |
| NRD, denoiser bypassed | 1.955e-03 |
| NRD v4 | 3.282e-03 |

Three caveats, all of which have to be stated together:

1. **The reference is not converged.** 400 vs 1200 samples differ by 6.28e-05 — about 18% of OIDN's
   score. The large gaps (NRD vs raw, 1.3e-03) survive that; OIDN vs OptiX (8e-05 apart) does **not**
   and cannot be separated at this sample count. The 1080p plume reference used 30000 samples.
2. **Bypass lands on raw** (1.955e-03 vs 1.956e-03), which is a clean result on its own: the
   demodulate / re-modulate round trip is faithful, so anything NRD costs here is NRD's filtering.
3. NRD scoring worse than raw is **not** explained. `diffuseMaxAccumulatedFrameNum` at 1, 5 and 30 is
   byte-identical, so it is not history depth. A motion-vector hypothesis was tested and **refuted** —
   see the mvec note in `vr_graph.add_denoiser`: plume has no velocity grid, so the volume-aware and
   surface-motion wirings are byte-identical (3.282e-03 either way) and neither can be at fault.
   Since the scene is static, the "variance" RELAX responds to must be frame-to-frame jitter from the
   scene update rather than genuine noise. Unresolved.

### The bistro column does not measure what it looks like it measures

**Do not read the bistro row as a quality ranking.** Raw ReSTIR scores 9.06e-07 there on a frame
that is *visibly* extremely noisy, while NRD v4 — which is dramatically cleaner to look at on the
same frame — scores ~100× worse. Both statements are true at once, and the image is the honest one.

The cause is the scene, not the denoiser. Bistro is a night exterior needing +8 EV (256×) to view.
Most pixels carry values small enough that even large *relative* noise contributes almost nothing
squared, so MSE is dominated by the near-black background and is nearly blind to the noise a viewer
sees. Any systematic shift a denoiser introduces — for us, the demodulate / re-modulate round trip
with its `minReflectance` floor — is comparatively large in the same units. So the column ranks
*least bias*, not least noise. MAPE does not rescue it: normalizing by a near-black reference
inflates exactly the same pixels.

This supersedes an earlier reading of the same numbers as "ReSTIR self-converges in about five
frames, so the scene is degenerate". The measurements behind that (7.51e-06 at frame 1 falling to
7.78e-07 by frame 5) are real and reproduce, but convergence is not what they show — the estimate is
still obviously noisy at frame 120. Low MSE on this scene is a property of its dynamic range.

Practical consequence: **plume is the scene that can rank denoisers**; bistro is useful for guide
ablations (where the question is whether a guide changes anything at all, not by how much) and for
eyeballing. Ranking on bistro needs a perceptual or exposure-aware metric first.

One further caution: the plume/bistro references are the converged ones (30000 / 3000 samples with
`VR_FREEZE_ANIM=1`); earlier, noisier references inflated every row.

### Guide ablations

Each guide is worth ablating rather than trusting — the depth guide was once found to be *worse*
than feeding nothing, and only an A/B revealed it.

All v4 figures below are with the corrected settings (pre-pass and history-fix off), frozen, frame 200.

| knob | v3.1 | v4.17 |
|---|---|---|
| `VR_NRD_NORMALS=0` | 25% worse on bistro, inert on plume | **154% worse on bistro** (2.132e-04 → 5.428e-04) |
| `VR_NRD_HITDIST=0` | inert under RELAX | matters only via the pre-pass; inert once it is off |
| `VR_NRD_JITTER=1` | 6% worse on plume, 10× worse on bistro | 1.5% worse on plume (1.058e-03 → 1.074e-03); 2.4× worse on bistro (7.707e-05 → 1.824e-04) |
| `VR_NRD_DEMOD=0` | 35% worse | **no longer helps** — 8% *better* on plume (1.058e-03 → 9.689e-04), 0.8% worse on bistro |

The normals row is what verifies the v4 encoding fix: the guide has to *matter* before its layout
can be called correct. On plume it is inert under both SDKs, so plume cannot verify it.

Jitter still hurts under v4, as it should — NRD does not upscale, so jitter buys no sub-pixel detail
and only adds variance. The effect being *smaller* than v3.1's rather than larger is the reassuring
direction: a broken `cameraJitterPrev` (new in v4, zero-defaulted) would have made jitter
catastrophically worse, not milder.

The demodulation row is the one to be careful with. It does not mean demodulation stopped being a
good idea — it is a direct consequence of the variance gating above. Demodulation earns its keep by
keeping albedo texture out of the blur; when the filter is effectively switched off, there is no blur
to protect against, so all that remains of the round trip is the `minReflectance` floor's bias. Do
not "simplify" the adapter on the strength of this row; re-measure it once a per-frame reference
exists.

## Not yet done

* **Bistro cannot be animated.** Its medium (`smoke-plume-2`) is a single time step with no velocity
  grids, so the only way to move that scene is a camera path. There is no Python keyframe API; the
  pass has a built-in orbit mode (`mCameraAnimationMode = 2` — the only continuous one, modes 0/1
  deliberately freeze the volume) whose three tuning parameters are UI-only and would need exposing in
  `parseProperties`/`getProperties`.
* **`lightDir` on emissive scenes is untested end to end.** The bounded emissive-triangle branch works
  (Bistro reports 18.09% valid), but no SH run has been scored on an emissive-lit scene.
* **The per-frame reference is not converged enough to rank close rows.** 400 vs 1200 samples differ by
  6.27e-05. Differences larger than that are safe; anything closer is not separable without far more
  samples (error falls as 1/sqrt(N), so a 10× tighter reference costs 100× the samples).

### Background, kept for the reasoning rather than the status

* ~~**SH mode**~~ — **DONE**, see [SH mode](#sh-mode). The notes that follow record why each piece is
  shaped the way it is:

  1. **`RELAX_DIFFUSE_SH` consumes a per-pixel dominant light direction**, which we do not currently
     produce. `RELAX_FrontEnd_PackSh` writes
     `SH0 = float4(radiance, hitDist)` and `SH1 = float4(direction * luminance(radiance), 0)`.
     Note `direction` is the direction incoming *radiance* arrives from — **not** a surface normal, so
     `mediumNormal` is not a substitute and using it would produce a plausible-looking wrong result.
  2. **DONE — `VolumetricReSTIR` now emits `lightDir`** (RGBA16Float, `.xyz` = direction the light
     arrives from at the first scatter vertex, `.w` = 1 when trustworthy). Written by `FinalShading`
     from the final reservoir, after the shading loop and with its **own** `SampleGenerator`, because
     `getAnalyticalLightSample` draws from the stream it is handed and reusing `sg` would shift every
     subsequent random number and silently change the rendered image.

     Verified on plume (960×540, frame 30): every pixel is **either a unit vector or exactly zero,
     nothing in between**; valid coverage 18.3%, matching the medium's screen extent; directions are
     spatially noisy (mean cos between neighbours 0.32), which is correct — each reservoir holds one
     importance-sampled environment direction, and that per-pixel noise is exactly what SH denoises.

     Two limits, both deliberate and both reporting `.w = 0` rather than guessing:
     * **Emissive-triangle lights are not reconstructed.** Doing it from `lightID` alone indexed the
       light collection out of bounds and took the device down (`DXGI_ERROR_DEVICE_REMOVED`) on plume,
       which has no emissive triangles. `evaluate_L_in_volume` only reaches that branch for reservoirs
       it already knows hold a triangle sample. Lifting this needs a triangle count to bound-check
       against. **Bistro is emissive-lit, so `lightDir` is invalid there** until that is done.
     * **Volumes with emission** are rejected outright, for the reason below.

  2b. Why it could not simply be reconstructed for every case — the original blocker:
     `Reservoir` stores `{int lightID, float2 lightUV}`, and `evaluate_L_in_volume` turns those into a
     direction by branching on `lightID`: `< 0` → `gScene.envMap.uvToWorld(lightUV)`, `<
     getLightCount()` → `getAnalyticalLightSample(...).rayDir`, otherwise →
     `sampleTriangleOffset(...).dir`. That branch looks reusable and is not, because
     `encodeEmissivePosition` (`ReSTIRHelper.slang:37`) **overwrites `lightID` with `asint(pos.z)`** —
     an arbitrary float bit pattern — when the sample is volume self-emission. So `lightID` is not
     reliably a light index, there is no in-band flag to distinguish the cases, and the real
     disambiguation is the contextual `isCurrentVertexEmissive` that only exists inside the evaluation.
     Reconstructing post-hoc would therefore misread every self-emission pixel (plume has emission)
     into a garbage direction, while still producing an image that looks broadly reasonable.
     Two further constraints on doing it inside the evaluation: pick the **first** scatter vertex's
     sample when `MAX_BOUNCES > 1`, and do not draw from the shared `SampleGenerator` —
     `getAnalyticalLightSample` consumes it, so reordering or adding a call perturbs the RNG stream and
     silently changes the rendered image.
  3. **TODO — `NRDAdapter` must emit the SH0/SH1 pair** instead of `diffuseRadianceHitDist`:
     `SH0 = float4(radiance, hitDist)`, `SH1 = float4(dir * luminance(radiance), 0)` with `dir` from
     `lightDir` (and the pixel skipped where `lightDir.w == 0`).
  4. **DONE** — `NRDPass::reflect()` has the second IO pair (`IN/OUT_DIFF_SH0` + `SH1`, 2× RGBA16Float)
     and `RelaxDiffuseSh` / `ReblurDiffuseSh` map to `RELAX_DIFFUSE_SH` / `REBLUR_DIFFUSE_SH`.
  5. **TODO — the resolve.** Without it the output is a coefficient pair, not an image:
     `NRD_SH_ResolveDiffuse(sh, N)`, optionally with `NRD_SG_ReJitter` (which needs viewZ and normals
     from the 4 neighbours). Suggested shape: give `NRDAdapter` a `mode` property and instantiate it
     twice in the graph (pack before NRD, resolve after) — a second pass class is unnecessary, and
     feeding the adapter's own output back into itself would make the graph cyclic.

  Worth knowing before starting: SH mode roughly doubles the denoised payload, and on the current
  benchmark it would be measured under the same variance gating described above — so **the per-frame
  reference should land first**, or SH will be evaluated in the one regime where RELAX declines to
  filter.
* Explaining the v3.1 → v4 quality gap above.
* Re-measuring the jitter and demodulation ablations under v4.
