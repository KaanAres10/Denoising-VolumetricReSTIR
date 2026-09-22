# Where this stands, and what to do next

Working notes for picking the NRD work back up. Measurements live in `README.md`; this file is the
open threads and the traps. Written 2026-08-03.

## The one thing to read first

**Check the IMAGE before claiming a fix.** Nearly every wrong conclusion in this file came from
comparing captures that differed in more than the variable under test -- a static camera against an
orbit, an ACES capture against a Linear one, and an "orbit" of radius 0.95 that was the camera
spinning on the spot. The numbers were correct every time; they were answering a question nobody had
asked. Three fixes were declared on metrics alone and two changed nothing a viewer could see.

The corollary, which cost a whole evening on its own: **check the output FILES exist** before
believing an exit code. See the harness traps at the end.

## Falcor 9.0 port: re-baselined, and the conclusions hold (2026-09-22)

Branch `falcor9-port`. The same matched table, re-measured on both engines: bistro orbit, 300 frames at
1080p, 30 warm-up, the Look tasks' settings. **The 8.0 column is the preserved 8.0 binary re-run with
today's scripts**, not the one in "The denoiser ranking, re-measured on the fixed build": that table
predates later script and guide changes (volume
mvec for TAA, the DLSSDGuides sky defaults), so even the 8.0 binary no longer reproduces it exactly.
Scored with `outputs/m_rebaseline_v9.py`, which reuses `m_denoisers.py`'s metric as written.

|                          | s=32 8.0 → 9.0 | plume 8.0 → 9.0 | surfaces 8.0 → 9.0 | detail 8.0 → 9.0 |
|--------------------------|----------------|-----------------|--------------------|------------------|
| raw ReSTIR (+ TAA)       | 9.25 → 9.23    | 13.87 → 13.83   | 27.43 → 27.44      | 0.0910 → 0.0910  |
| OptiX (+ guides)         | 10.81 → **10.52** | 17.48 → **16.91** | 28.69 → 28.53   | 0.0638 → **0.0673** |
| RELAX-SH                 | 9.27 → 9.30    | 13.59 → 13.63   | 27.15 → 27.22      | 0.0640 → 0.0640  |
| REBLUR-SH                | 9.32 → 9.40    | 13.55 → 13.64   | 26.90 → 26.99      | 0.0637 → 0.0637  |
| DLSS Ray Reconstruction  | 8.75 → 8.75    | 13.77 → 13.80   | 26.51 → 26.49      | 0.0651 → 0.0652  |

9.0 here is `rb_v9uv_*`, with every port fix below applied. Raw and RR match 8.0 to 0.3%, RELAX and
REBLUR to under 1%, and the ranking is the same in every column. OptiX is the one real change, and it
is an improvement: plume 3.3% more stable, 5.5% more detail.

**A 1% darker render, from a Falcor API whose meaning changed -- FIXED.** Before this fix every
configuration rendered 0.93-1.33% darker on 9.0, in the renderer itself (raw showed it; the tone
mapper's 9.0 change is a type declaration only), spread thinly over lit surfaces. Because the metric
divides by the mean, it also read as a uniform ~1% "regression" in every column.

Cause: 9.0's `sampleTriangle` sets `TriangleLightSample.uv` to the sample's BARYCENTRICS,
`sample_triangle(u).yz = (1 - sqrt(u.x), u.y * sqrt(u.x))`; 8.0 set it to the random numbers `u`.
`VolumeUtils.slang` stores it as the reservoir's `lightUV`, and every reuse regenerates the light point
with `sampleTriangleOffset(.., lightUV, ..)` -- feeding it back in AS `u`. On 9.0 that warps the
barycentrics a second time onto a different point of the emitter, so each reused emissive sample was
evaluated away from where it was sampled, under the uniform 1/area pdf of the right point: a bias.
It compiled cleanly because the type and the name did not change -- only the meaning.

Fix: invert the warp where the reservoir is written, `u = ((1 - uv.x)^2, uv.y / (1 - uv.x))`, so
`lightUV` means what it meant on 8.0. That one change moves 9.0's raw mean level from -0.93% to
-0.05% of 8.0's, and by screen region from uniformly darker (-0.45..-1.56%) to mixed signs within
+-0.45%, i.e. noise. The pixel-level difference from 8.0 stays (different random streams, most likely
from the new compiler's float results flipping individual sample choices -- `PAD_RANDOM_NUMBERS` is
off for this pass), but that changes the noise, not the expectation. OptiX's output stays 0.47%
darker; raw, which OptiX denoises, does not, so that is OptiX now using its normal guide.
**Anything else that stores a Falcor `TriangleLightSample.uv` and feeds it back into `sampleTriangle`
has the same bug on 9.0.**

**The OptiX gain is 8.0's normal guide never reaching OptiX.** Answers "The OptiX normal guide is
inert" below: in 8.0's `OptixDenoiser_::convertNormalsToBuf` the conversion shader's variables are
bound and then `mpConvertTexToBuf->execute()` runs -- the generic texture copy, not the normals pass.
The normals shader never ran, so the guide buffer never got the normals, which is why changing the
volume normal mode left OptiX byte-identical. 9.0 fixes the dispatch (`mpConvertNormalsToBuf`), the
staging format (FLOAT3 -> FLOAT4) and the decode (`(n - 0.5) * 2` on an already-signed normal).
Isolated by putting the old decode back into 9.0 for one run (`rb_v9_optix_olddecode`):

|                                   | s=32  | plume | detail |
|-----------------------------------|-------|-------|--------|
| 8.0 -> 9.0 with the old decode    | -1.7% | -2.5% | +4.5%  |
| old decode -> fixed decode        | -0.5% | -0.7% | +0.9%  |

So most of it is the guide being delivered at all; the decode is the smaller part. Both runs predate
the lightUV fix above, so the first row also carries the ~1% darkening, which counts AGAINST OptiX's
score -- the dispatch fix is if anything larger than shown. **Every OptiX number measured on 8.0 was OptiX without a normal guide.** OptiX
still ranks last on 9.0, so the conclusion stands, but its gap to the others is smaller than 8.0 said.

**The comparison is exact, not statistical.** Two runs of the same build are byte-identical, so every
difference is the engine. That is also what made the two faults below findable.

**Two false regressions came first, and both would have gone into this file on metrics alone:**

* **RELAX -7% in the plume was the matrix fix, applied twice.** Slang 2025.13.2 delivers NRD's
  matrices correctly, so `patch_nrd_matrix_layout.py`'s transpose -- the fix on 8.0 -- is the bug on
  9.0. The A/B rows swap across the diagonal (8.0 fixed ≈ 9.0 untransposed, 8.0 untransposed ≈ 9.0
  fixed), and on the pixels 9.0-untransposed is closer to 8.0-fixed than 9.0-as-shipped is. NRDPass
  now reads the matrices untransposed by default; `NRD4_TRANSPOSE_MATRICES=1` is the fault for an A/B,
  and `NRD4_RAW_MATRICES` has no effect any more. **The correct read depends on the Slang version**,
  so re-run this A/B after any Slang bump.
* **RR +10% on s=32 was one run whose capture clock stalled.** 96% of the excess sat in 8 frames; the
  frames showed the camera jumping to the final pose at file 299 and parking. A re-run was
  byte-identical through 298 and clean after, scoring within 0.6% of 8.0. `capture_orbit.py` now writes
  `CLOCK_STALL.txt` and says so when the clock stops tracking the loop. Cause not established.

Also from the port: `libprotoc.dll` / `z.dll` vanished from `bin/Release` twice more, once while no
build touched them. The harness traps below still apply; check for them before a batch.

## SOLVED: REBLUR's medium was transparent under motion

Symptom: with the camera orbiting, REBLUR's plume read as haze -- doors, wall panels, plant pots and
paving stones visible through it. RELAX in the same frame occluded properly.

**It was the SURFACE half, not the volume half.** Every measurement before this one was aimed at the
wrong buffer. Captured separately (`halves.py`), REBLUR's surface half has no plume-shaped hole in
it at all: the awning, shopfront, scooter and paving are drawn sharply straight through where the
smoke is. The composite is volume + surface, so a fully-lit building gets added behind an otherwise
correct plume. Mean radiance in the dense band (`mediumAlpha > 0.75`, 20.2% of frame), x1e-4:

| surface half, dense band | value | vs raw |
|---|---|---|
| raw split (undenoised) | 7.20 | 1.0x |
| RELAX | 8.25 | 1.1x |
| **REBLUR** | **146.46** | **20.3x** |
| REBLUR, every spatial pass off | 146.16 | 20.3x |
| REBLUR, `maxAccumulatedFrameNum = 1` | 8.30 | 1.2x |
| **REBLUR + history confidence (fix)** | **8.29** | **1.2x** |

Mechanism: the surface half is `T * L_surface`, and `T` belongs to the medium in FRONT of the wall,
so it does not travel along the wall's motion vector -- but every guide NRD can test (viewZ, normal,
plane distance) describes the wall, and smoke does not change the G-buffer. REBLUR therefore accepts
history from before the plume moved across, and keeps drawing the building. RELAX escapes because
its luminance edge-stopping refuses to blend a bright history against a zero current sample. Under a
static camera those pixels were ALWAYS occluded, so history is zero too and nothing fills in -- which
is why the bug is invisible without the orbit.

Fix: `VR_NRD_SURFCONF`, ON by default in the split path. The estimator emits `mediumTransmittance`
(a new GenerateFeatures output, written for every pixel) and the surface branch feeds it to NRD's
`IN_DIFF_CONFIDENCE` -- an input that was declared in NRDPass and never produced. Confidence is 1
outside the medium and falls to 0 as it goes opaque, which is where a stale reprojection does most
damage and where losing accumulation costs least, since the term is multiplied by `T` anyway.
Confirmed visually AND numerically; RELAX moves 8.2518e-4 -> 8.2409e-4, i.e. it costs nothing, and
the volume half is byte-identical either way.

Ablated first, none of them mattered (dense-band surface half): pre-pass 0 -> 146.82, temporal
stabilization 0 -> 126.10, anti-firefly off -> 148.54, history fix 0 -> 137.62.

Superseded by this, kept because the reasoning pattern recurs: the volume half loses 14-22% at alpha
0.10-0.75 under motion where RELAX loses 0-12%. That is real and it is a red herring -- those bands
are 2% of the frame and the dense core is 0.93 vs RELAX's 0.94. The standing hypothesis (stochastic
scatter-point viewZ jitter rejecting history in the volume half) was never tested and is now moot.

## SOLVED: the blocky plume boundary, which the confidence fix itself caused

Reported after the confidence fix shipped: "the boundary of the volume, opaqueness not there, and the
boundary seems to have wrong transparency." Correct, and it was the fix's own side effect. Feeding
raw transmittance as `IN_DIFF_CONFIDENCE` makes accumulation change abruptly across the silhouette,
and NRD schedules its work in TILES (`REBLUR_ClassifyTiles`) -- so an abrupt per-tile change in
accumulation comes out as hard rectangular seams cutting into the plume, plus surviving ghosts of a
street lamp and a bollard. Visible at 3x zoom on frame 62 of the orbit; invisible in every band mean,
because the seams are a few percent of the frame.

FIX: divide the surface half by transmittance BEFORE the filter and multiply it back after
(`VR_NRD_SURFTR`, default ON). The half is `T * L_surface`, and `T` belongs to the medium in FRONT of
the wall -- it varies over a few pixels along a boundary in none of NRD's guides and does not follow
the surface's motion vector. Demodulated, the denoiser sees the unoccluded wall, smooth, with no
plume-shaped feature to tile on; the occlusion is re-applied from the estimator's own per-pixel `T`.

Re-modulation uses the adapter's exported `demodDivisor`, NOT albedo again -- once transmittance is
in the divisor the two differ, and having ModulateIllumination re-derive the formula is how a
demodulate/remodulate pair silently stops being a round trip. Bypassed round trip closes at max
9.7656e-04 (exactly the fp16 quantum), mean 9.94e-08.

Demodulation does NOT subsume the confidence fix, which I assumed and measured to be wrong. The
divisor is floored at 0.05, so it stops tracking `T` where the medium is opaque. Composite against
the undenoised image of the same frame, 20-8 px inside the silhouette:

| neither | demodulation alone | confidence alone | both |
|---|---|---|---|
| 1.399 | 1.332 | 0.945 | **0.979** |

and the floor cannot be lowered to cover it: 0.05 -> 0.02 -> 0.01 -> 0.003 gives 1.332 -> 2.515 ->
4.640 -> 6.142, because dividing near-zero surface radiance by near-zero `T` makes fireflies the
filter spreads and re-modulation cannot retrieve. That is the emissive-bloom failure mode in a
different divisor.

So the two own different regimes, and the ADAPTER emits the handover itself --
`saturate(T / minTransmittance)`, 1 while the divisor still tracks `T`, ramping to 0 as it floors out
-- rather than a second threshold that could drift from the first. Raw `T` as confidence measured
worse where demodulation already works (composite 4-6 px inside: 1.013/1.027 with demodulation alone
against 1.067/1.088 with raw-T confidence on top).

Differencing the two 90-frame orbits confirms the change is boundary-localised: interior and
background untouched, 2.9% of pixels moving by more than 0.02. Popping 38.58% -> 37.82%, flicker
unchanged.

METHOD NOTE, the expensive one this round: band means over the whole silhouette said the two
configurations were identical (0.0590 / 0.0510 ghost correlation, composite within 1% of truth at
every band). They are not, and the difference is glaring at 3x zoom. Two separate traps combined --
the metric averaged over a ring that mixes every local context around the plume, and the captures
were at a DIFFERENT camera pose from the frames being looked at, because `halves.py` and `flicker.py`
step the orbit at different rates. Diff the sequences to find where they differ, then look there.

## SOLVED: the halo, and what the popping actually is

Reported alongside the residual see-through. Both turned out to be separate from it.

**Halo** is the volume half's spatial blur carrying the plume's radiance past its own silhouette.
Measured as a radial profile from the `mediumAlpha > 0.5` boundary, volume half as a ratio to raw:

| config | 6-14 px out | 14-30 px out | 30-80 px out | interior |
|---|---|---|---|---|
| pre-pass 30, max blur 30 (NRD default) | 1.43x | 2.40x | 3.41x | 0.87x |
| pre-pass 0, max blur 30 | 1.26x | 1.43x | 0.79x | 0.87x |
| **pre-pass 0, max blur 12 (now)** | **1.15x** | **0.91x** | **0.16x** | **0.88x** |
| all spatial filtering off | 0.88x | 0.56x | 0.18x | 0.88x |
| RELAX at its defaults | 1.37x | 1.89x | 17.92x | 0.92x |

The interior gets BRIGHTER, not dimmer, because the energy stops leaving. Now better confined than
RELAX on every band. Pre-pass reason is the one already established for RELAX -- the kernel is sized
by `saturate(hitDist / frustumSize)` and both branches feed a primary distance of the same order as
the frustum, so it saturates into a full-radius blur. `VR_NRD_PREPASS` / `VR_NRD_VOL_BLUR`.

**Popping is mostly not ours.** Per-pixel second-difference maps over the orbit put the instability
on sub-pixel geometry -- window grilles, string lights, awning edges -- and show the plume as the
STEADIEST region of the frame in every configuration. Share of pixels taking a jump > 0.25:

| config | mean | p99.5 | worst | %px > 0.25 |
|---|---|---|---|---|
| REBLUR, session start | 0.2682 | 0.9731 | 2.5225 | 44.02% |
| + history confidence | 0.2650 | 0.9816 | 2.4876 | 42.35% |
| + per-branch tuning | 0.2633 | 1.0123 | 2.5302 | **38.58%** |
| DLSS Ray Reconstruction | 0.3215 | 1.0028 | 2.6892 | 51.29% |

RR is the worst of the four on every popping measure, so "compare to RR" cuts the other way here --
RR's lead is sharpness (0.00334 vs 0.0013), not stability. Note p99.5 rises slightly with the tuned
kernel: less blur means the pops that remain are marginally stronger.

REFUTED while chasing this: NRD's README requires HDR inputs in [0; 250] and `maxIntensity` is
100000, so nothing enforces it -- but the largest value actually reaching NRD is 100.8 and no pixel
exceeds 250. Also no effect: `hitDistanceReconstructionMode = AREA_3X3` (identical to pre-pass 0
alone, on every band) and `maxStabilizedFrameNum = 0` (slightly WORSE on the surface half, 1.35x vs
1.28x at the silhouette).

Still there, and probably irreducible: at the immediate silhouette (+-2 px) the surface half sits at
1.28x raw. RELAX is 1.29x and killing all spatial filtering still leaves 1.27x, so this is filter
footprint at a boundary no guide describes, not a bug with a fix.

## Per-instance tuning under v4

The split holds TWO NRD instances in one process, so env vars cannot tune them differently. All
RELAX/REBLUR property names were rejected under v4 on purpose (their meanings changed), which also
meant `add_nrd_split`'s `diffuseMaxAccumulatedFrameNum` and `diffusePhiLuminance` had been landing in
the unknown-property warning and doing nothing since the port -- its "each half gets its own tuning"
comment was false. Re-accepted under names meaning the same thing in both structs:
`prepassBlurRadius`, `maxBlurRadius` (REBLUR only), `diffuseMaxAccumulatedFrameNum`,
`diffusePhiLuminance`, `historyFixFrameNum`. Both re-enabled values equal NRD's defaults and RELAX
reproduces 0.29336 flicker byte-for-byte, so nothing moved silently.

## REBLUR runs at NRD's stock defaults

Everything in the v4 block below applies to `mRelaxSettings` ONLY. REBLUR was untouched throughout
the port, including `diffusePrepassBlurRadius = 30` -- the exact value measured here as worse than
the undenoised input, monotonically, because the kernel is sized by `saturate(hitDist / frustumSize)`
and this renderer's hit distance is a scatter distance of the same order as the frustum.

Its settings are now exposed as `NRD4_R_*` (PREPASS, STABIL, ANTIFIREFLY, MAXACCUM, FASTACCUM,
HISTFIX, CLAMPSIGMA, MINHITW, MAXBLUR, PLANEDIST, LOBEFRAC, FIREFLYSCALE, ANTILAGSIGMA, ANTILAGSENS,
HITRECON, HISTLEN), all defaulting to NRD's values so the block changes nothing on its own. That is
what made the ablation table above possible. Two worth knowing about:
* `NRD4_R_HISTLEN=1` writes accumulated history length into `.w` instead of the normalized hit
  distance -- the cheapest way to see history being rejected, and no validation-overlay wiring needed.
* `NRD4_R_HITRECON=1` is AREA_3X3. NRD's header says it "must be used in case of probabilistic
  sampling, when a pixel can be skipped and have 0 (invalid) hit distance", which is exactly what the
  split produces. Never measured.

Still worth retuning REBLUR properly against the RELAX reasoning; the pre-pass is the obvious first
candidate.

## Current numbers (bistro, 1280x720, moving camera)

Flicker is the second temporal difference over consecutive frames, so smooth motion cancels.
Sharpness is Laplacian variance — higher is more detail. Both are needed: any denoiser can win on
flicker by blurring.

| configuration | flicker | sharpness | brightness | ms/frame |
|---|---|---|---|---|
| NRD historyFix 0 (old default) | 0.26687 | 0.00996 | 0.1257 | — |
| NRD historyFix 3 (current) | 0.23468 | 0.01398 | 0.1584 | 75.38 |
| NRD split (volume+surface) | 0.24804 | 0.01398 | 0.1575 | 77.19 |
| NRD + TAA after tonemap | 0.10719 | 0.00124 | 0.1594 | 76.04 |
| NRD split + TAA | 0.11338 | 0.00125 | 0.1584 | — |
| **REBLUR split + TAA** | **0.08370** | 0.00104 | 0.1614 | — |
| DLSS Ray Reconstruction | 0.12818 | **0.00326** | 0.1559 | 79.42 |

Raw ReSTIR with no denoiser is 72.51 ms, so every denoiser cost is a 3-7 ms delta on top of a 72 ms
frame. Most of that baseline is bistro's per-frame `LightCollection::syncCPUData` readback, forced by
the `Power` emissive sampler (`VolumetricReSTIR.h`). Fixing that would make every timing here far
easier to resolve.

Harness: `Scripts/flicker.py` (fixed camera dolly, consecutive captures, `VR_DENOISER`, `VR_TIME`)
and `Scripts/flick_measure.py`.

## FIXED: emissive surfaces bloomed

Reported visually -- light bulbs read far too bright and too large. Three facts line up into a
mechanism, not yet confirmed by measurement:

* `NRDAdapter::mMinReflectance = 0.01`, so demodulation divides by at least 0.01 -- up to 100x
  amplification wherever diffuse albedo is near black.
* `ModulateIllumination.emission` is never wired. Emission therefore rides inside
  `accumulated_color`, gets demodulated by an albedo it was never multiplied by, and is denoised.
* `maxIntensity` is 100000 against NRD's default of 1000, so nothing clamps the resulting spike.

An emissive bulb has huge radiance and near-zero DIFFUSE albedo, so it takes the full 100x
amplification. NRD then spreads that spike across its filter footprint, and re-modulation multiplies
back each pixel's OWN albedo -- which cannot retrieve energy that has already leaked into
neighbours. NVIDIA's guidance is that emission must not be denoised at all; the additive `emission`
input on ModulateIllumination exists for exactly this.

CONFIRMED by measurement. Emitter cores are the top 0.1% of the RAW image (unfiltered, so their
extent is the true extent); the table is mean luminance in a ring at distance r, as a ratio to raw,
where 1.00 would mean no leakage. The cores themselves are saturated and cannot show the effect.

| config | r=2 | r=4 | r=8 | whole frame |
|---|---|---|---|---|
| raw ReSTIR | 1.00 | 1.00 | 1.00 | 1.00 |
| maxIntensity 100000 (ours) | 14.72 | 1.91 | 1.09 | 1.10 |
| maxIntensity 1000 (NRD default) | 17.51 | 8.06 | 4.60 | 2.29 |

So energy really is being spread outward from emitters -- 14.7x immediately around them, decaying to
baseline by ~8 px, with the whole frame 10% brighter, i.e. energy ADDED rather than redistributed.

`maxIntensity` is NOT the lever. Lowering it to NRD's default makes the bloom markedly worse: the
leak reaches 8 px instead of 4 and the frame doubles. The existing 100000 was the right call, and
"restore NRD's default" would have been the wrong move here despite being right for
historyFixFrameNum. Exposed as `VR_NRD_MAXINT` so this stays reproducible.

FIXED by routing emission around the denoiser (`VR_NRD_EMISSION=1`). FinalShading emits
`emissiveColor` / `nonEmissiveColor` as a complementary pair, the adapter denoises only the
non-emissive half, and `ModulateIllumination.emission` adds the emitters back untouched. Round trip
with the denoiser bypassed closes at 1.22e-04, inside the fp16 floor and better than the albedo-only
path because emission no longer passes through NRD's fp16 output texture.

| config | r=2 | r=4 | r=8 | frame |
|---|---|---|---|---|
| raw ReSTIR | 1.00 | 1.00 | 1.00 | 1.00 |
| emission denoised (before) | 6.89 | 3.50 | 2.29 | 1.48 |
| emission bypassed (fix) | 1.44 | 1.57 | 1.53 | 1.44 |

The distance-dependent falloff (6.89 -> 3.50 -> 2.29) is replaced by a flat ~1.5x, i.e. ordinary
denoiser gain rather than energy leaking outward from emitters.

Two measurement traps hit while confirming this, both from comparing across runs: the first
"before" numbers used a capture taken before the tonemapper was switched to Linear, and a second
attempt still mixed tonemappers. Only a pair captured from the SAME build with byte-identical raw
(verified max|d| = 0) is meaningful.

Still open: the residual flat 1.44x. That is not bloom, and it may simply be what demodulation plus
filtering does to this scene -- but it has not been explained.

Superseded note on the original diagnosis: Emission has no business being
divided by a diffuse albedo it was never multiplied by, and `ModulateIllumination.emission` is an
additive input that exists precisely so it can bypass the filter. It needs the estimator to emit
directly-visible emissive radiance as its own buffer -- the same shape of change as the volume /
surface split in `FinalShading.cs.slang`, and verifiable the same way: with the denoiser bypassed,
emission + denoised must reconstruct `accumulated_color` exactly.

## History of the transparency hunt (SOLVED above; kept for the method, not the conclusions)

Everything in this section and the next was aimed at the VOLUME half. The defect was in the SURFACE
half. Read them as a record of how five plausible mechanisms were each built, measured and refuted --
the pattern is worth keeping even though every conclusion here is superseded.

The coverage mask (`VR_NRD_VOLMASK`, commit 68de73c) does NOT fix the visible problem. It changes
3.18% of pixels by a mean of 0.2/255 -- invisible. Looked at side by side, REBLUR with and without
the mask are indistinguishable, and both show the doors, wall panels, plant pots, string lights and
paving stones straight through the plume, which reads as a faint haze. RELAX in the same frame is a
solid occluding mass.

The mask was built and shipped on the strength of a leak ratio going 0.401 -> 0.326, and that number
is real. It is also irrelevant, because it was measured on the wrong region: the mask
`mediumAlpha > 0.75` covers only the plume's core, 14% of the frame. The transparency lives in the
BROAD medium-density region, which every measurement so far excluded. The same mistake produced the
earlier "surface share is only 2.4%, so bleed-in is not the cause" conclusion.

NARROWED, 2026-08-04. The transparency is TEMPORAL, not spatial. With bistro's STATIC default
camera, RELAX, REBLUR and REBLUR+mask are all opaque and visually near-identical -- the plume
occludes the building in every one. The see-through appearance appears only in the ORBIT captures.

That invalidates every measurement taken to diagnose it. `halves.py` uses the static camera, so the
per-band energies, the chroma comparison and the leak ratio were all measured in the regime where
the bug does not happen. They came back clean because nothing was wrong in that frame.

Consistent with the temporal reading: per band on the static view, REBLUR's volume half is within
5-9% of RELAX's, its chroma is identical (0.78 both), and its volume:surface ratio is slightly
BETTER (2.54 vs 2.38). By every static measure REBLUR should look MORE opaque.

Leading hypothesis, untested: the volume half's viewZ is the estimator's linearZ, i.e. the view Z of
a STOCHASTICALLY chosen scatter point, so it jitters frame to frame even for a static medium. Under
camera motion REBLUR's disocclusion test sees that jitter on top of real reprojection error and
rejects history continuously, so the volume half never accumulates; TAA then smooths the unaccumulated
signal into a faint haze. RELAX would have to be more tolerant of the same input for this to be the
explanation, which is checkable.

LOCALISED, on the orbit capture (`halves.py` now takes VR_ORBIT=1). Volume half per coverage band,
as a fraction of raw:

| band | % frame | raw (x1e-4) | RELAX | REBLUR | RELAX/raw | REBLUR/raw |
|---|---|---|---|---|---|---|
| 0.10-0.35 | 0.87% | 0.817 | 0.843 | 0.706 | 1.03 | 0.86 |
| 0.35-0.75 | 1.10% | 2.007 | 1.770 | 1.568 | 0.88 | 0.78 |
| 0.75-1.00 | 20.21% | 3.903 | 3.683 | 3.643 | 0.94 | 0.93 |

Under motion REBLUR loses 14-22% of the volume half in the THIN and MID bands while RELAX loses
0-12%; the dense core is intact in both. That is the transparency -- the plume's body thins while its
core stays, so it reads as haze over the buildings. It is also exactly where the scatter point is
most stochastic, i.e. where the volume half's viewZ jitters most, which is what the temporal
hypothesis predicts.

Still to do:
  * volume-half energy per alpha band, orbit vs static, RELAX vs REBLUR -- does REBLUR's volume half
    collapse only when the camera moves;
  * NRD's validation overlay (VR_NRD_VALIDATION=1) on the volume instance, which draws history
    length -- if history is being reset every frame in the medium it will show there directly.

Older list, superseded but kept because the band method is still the right shape:
  * how the volume half's energy compares to RELAX's across 0.1 < alpha < 0.75, not just above 0.75;
  * how the surface half's share varies across those bands -- structure is visible at energy
    fractions far below where it shows up in a mean;
  * whether REBLUR's volume half is genuinely dimmer there, or the surface half is brighter, or both.

Method note for whoever picks this up: check the IMAGE before claiming a fix. Three fixes this
session were declared on metrics alone and two of them changed nothing a viewer could see.

## Open: REBLUR is fed the wrong hit distance, and normalising is not the fix

REBLUR's smoke reads see-through while RELAX's stays opaque. Chasing that led to two findings, the
second of which supersedes the first.

1. We never call `REBLUR_FrontEnd_GetNormHitDist`. REBLUR wants `normHitDist` in [0;1] and must be
   told the normalisation via `nrd::HitDistanceParameters`; we write raw metres. RELAX takes raw
   metres by design, which is why only REBLUR is affected -- and REBLUR sizes its blur kernel from
   that value, so it blurs near-maximally everywhere, which is what dissolves the medium.

2. But normalising alone does NOT fix it. With the defaults (A=3, B=0.1, C=20) and diffuse
   roughness, `smc -> 1`, so `f = 3 + 0.1*viewZ`. At viewZ ~12 m that is f ~4.2, and a 12 m hit
   still normalises to `saturate(12/4.2) = 1.0`. Saturated either way.

   The reason is semantic, and NRD.hlsli states it outright: hit distance "must not include primary
   hit distance". `scatterDistance` is camera-to-scatter-point, i.e. exactly a primary distance.
   Normalising it would convert the wrong quantity into the right units.

So the question to answer first is what hit distance MEANS for a participating medium. Candidates,
none yet tested:
  * the distance from the scatter point to the next event (a secondary distance, which is what NRD
    asks for) -- the estimator does not currently emit it;
  * a transmittance-derived length such as the mean free path 1/sigma_t, which is the medium's own
    characteristic scale and is what REBLUR's kernel radius arguably should track;
  * nothing at all -- `VR_NRD_HITDIST=0` feeds a constant, and on RELAX that was measured
    byte-identical, so REBLUR is the only denoiser for which this guide does anything.

TESTED, AND THE SATURATED-KERNEL EXPLANATION DOES NOT HOLD. `missHitDistance` is now exposed as
`VR_NRD_MISSHIT`, so the guide can be driven to any constant. Sweeping it 3000x on REBLUR-SH split +
TAA + emission (bistro, authored orbit, 90 frames):

| hit distance fed | flicker | sharpness | brightness |
|---|---|---|---|
| surface linearZ / scatterDistance | 0.49034 | 0.00169 | 0.1552 |
| constant 1000 (fully saturated) | 0.50566 | 0.00179 | 0.1554 |
| constant 0.3 (small kernel) | 0.47100 | 0.00160 | 0.1653 |

A 3000x change in the guide moves flicker 7% and sharpness 11%. If kernel radius were what dissolves
the medium, that sweep would have been dramatic. So hit distance is a real but MINOR input, the
missing normalisation is a correctness issue rather than the cause, and the transparency has a
different source.

MECHANISM FOUND, by capturing each denoised half separately (Scripts-adjacent harness `halves.py`
marks NRDSurface / NRDVolume filtered outputs). Inside dense smoke (mediumAlpha > 0.75, 14.3% of
frame):

| | volume half | surface half | surface share |
|---|---|---|---|
| raw | 0.00032 | 0.00000 | 0.1% |
| RELAX | 0.00029 | 0.00001 | 3.3% |
| REBLUR | 0.00027 | 0.00001 | 2.4% |

So surface radiance bleeding IN is not the cause -- it is 2-3%, and REBLUR leaks LESS of it than
RELAX. The cause is the volume half's own energy leaking OUT past the plume's silhouette:

| source | core | ring+4 | ring+12 | ring+28 |
|---|---|---|---|---|
| raw | 0.000316 | 0.000281 | 0.000103 | 0.000016 |
| RELAX | 0.000294 | 0.000250 | 0.000107 | 0.000019 |
| REBLUR | 0.000269 | 0.000229 | 0.000108 | 0.000021 |

Leak ratio (ring+12 / core): raw 0.3262, RELAX 0.3648, REBLUR 0.4010. REBLUR's core loses 15% of its
energy and it reappears outside the plume (+31% at ring+28). A thinner core with a brighter halo is
exactly what reads as see-through. REBLUR spreads about twice as much as RELAX relative to raw.

THE FIX is to stop the volume half's energy escaping its own silhouette. The plume boundary is not
in any guide the volume denoiser gets: mediumNormal is a gradient that goes quiet outside the
medium, and viewZ falls back to the far plane there, so the denoiser has nothing marking "the medium
ends here". mediumAlpha IS that boundary and there is no NRD slot for it -- so it has to be applied
OUTSIDE the denoiser, by multiplying the filtered volume half by coverage before compositing. That
is the transmittance compositing the original plan called B3 and I implemented as a plain additive
sum. Same shape as the emission routing: a small pass or a ModulateIllumination reflectance input,
verifiable by the bypassed round trip.

Superseded candidate, now measured false: REBLUR has no luminance edge-stopping, so it fills the
split's structural zeros with surface radiance from outside the plume, while RELAX's luminance
rejection refuses to blend a zero against a bright neighbour and so keeps the medium opaque. That
predicts something falsifiable and untested: raising `NRD4_MINLUMW` on RELAX should make RELAX's
smoke transparent too. If it does not, this explanation is wrong as well.

## Next, in order

0. **Confirm and fix the emissive bloom above.** Cheapest visible-quality win on the list.
1. ~~Measure SH mode.~~ DONE. SH lands within noise of non-SH for both denoisers (RELAX 0.10703 vs
   0.10719; REBLUR-SH 0.08281 vs 0.08370), so it does NOT close the RR gap -- RR keeps a ~3x
   sharpness lead over every NRD configuration tested. The first REBLUR-SH attempt was invalid: the
   adapter packed RELAX's linear-RGB SH layout for REBLUR, which expects YCoCg, so REBLUR
   reinterpreted the channels (green cast, +30% energy). Fixed in `ee9cf95`; the identity test now
   covers that path. The `Cosine` resolve is separately confirmed wrong for a medium: 45% darker and
   the worst flicker of any anti-aliased row.
2. **Sweep `NRD4_MINLUMW`** (0.0 / 0.3 / 0.6) on REBLUR split + TAA. Committed but never run — the
   sweep silently produced no captures, see the harness trap below. Rationale: RELAX/REBLUR see a
   structural zero beside a bright pixel, read a large luminance difference and refuse to blend, so
   the split's holes survive filtering. A floor on that weight should force blending across them.
3. **Settle the 2.11x in-medium disagreement** between ReSTIR and brute force. They agree to 2%
   outside the medium. Prime suspect is the `noReuse` branch in `ReSTIRHelper.slang:201` that divides
   `sigma_s` by `sigma_t` — reference mode takes it, ReSTIR does not. Until this is understood, every
   absolute in-medium error number carries the offset (relative A/Bs are unaffected).
4. **A/B the volume normal.** The split depends on `VR_VOL_NORMAL=gradient` and it has never been
   compared against `camera`. One run each.
5. **Velocity is dead data.** `GVDBBake` hardcodes `isVelocity = 0` and exports only channel 0, yet
   sets `hdr.hasVelocity = 1` whenever the `*_velocity_*.vbx` files merely exist; the baked loader
   then uploads that slot as scalar R32Float and discards the `isVel` flag it just read
   (`SceneGVDB.cpp:737-753`, against the correct non-baked path at `:544`). So `velocityIn` is never
   populated and every baked asset is velocity-free while every flag says otherwise. This is the
   whole explanation for `VR_NRD_VOLMV` measuring 1.86e-05, and it blocks the velocity-guided
   temporal work entirely. Fixing it needs the bake tool, the loader, and a re-bake of 100 frames.

## FIXED (worked around): RELAX's accumulation was gated by the disocclusion threshold

`CommonSettings::disocclusionThreshold` is what RELAX's reprojection validity test compares against
(`RELAX_TemporalAccumulation.cs.hlsl`, `isReprojectionTapValid` -> `maxPlaneDistance >
disocclusionThreshold`). Raising it from 2% to **20%** restores the accumulation. Now the v4 default;
`NRD4_DISOCC` overrides, and it is re-applied after the property loop so a graph property cannot
silently win.

Measured at 90 frames on the production configuration, instability by spatial scale (x1e-3) with the
correctness check beside it -- composite against `accumulated_color` of the SAME frame, 1.00 being
the undenoised image:

| disocc | s=32 | s=128 | whole-frame | sharpness | vs undenoised |
|---|---|---|---|---|---|
| 2 (was) | 28.28 | 14.38 | 11.88 | 0.00133 | 0.998 |
| 10 | 23.46 | 11.72 | 9.27 | 0.00127 | 0.997 |
| **20 (now)** | **19.49** | **9.94** | **8.08** | 0.00123 | 0.996 |
| 35 | 17.03 | 8.96 | 7.42 | 0.00125 | 0.996 |
| REBLUR | 15.92 | 9.14 | 7.72 | 0.00127 | |
| DLSS RR | 17.70 | 10.05 | 8.43 | 0.00334 | |

20 is -31% at sigma 32 and -32% whole-frame against the old 2, for 7.5% of sharpness, and it puts
RELAX AHEAD of Ray Reconstruction at sigma 128. Every value reproduces the undenoised image to within
0.4%, so the falling mean brightness in the moving sequences is temporal behaviour over the orbit
rather than an energy error. Checked by eye at 3x zoom for ghosting: none visible. 35 is better still
but returns are diminishing and it is 17x NRD's documented maximum.

REBLUR is unaffected by the change (15.92 against 16.03 before), which is consistent with its
accumulation having worked all along. The gap to REBLUR narrows from 76% to 22% but does not close --
the remainder is presumably the same unrooted reprojection problem, since fully restoring RELAX's
accumulation on a static camera needs 50%.

Static camera, spatial minimised, d1: 2% -> 0.07261, 10% -> 0.06195, 50% -> 0.02247.

**This is a workaround, not a root-cause fix.** NRD documents [0.01; 0.02] for this threshold, so
needing 5x that means the reprojection genuinely does not line up -- which is also what the
validation overlay says, its MV viewport being saturated even on a static camera. Raising the gate
buys the accumulation back without explaining why it was being rejected.

REFUTED on the way here, all measured with spatial filtering minimised so the temporal stage is what
is being observed: every RelaxSettings knob (`maxAccumulatedFrameNum` 1/30, fast history 2/6/
disabled, clamp sigma 2/10, `depthThreshold` across 0.003-0.2 i.e. 67x, anti-firefly, history fix,
pre-pass), the SH variant (which skips `PackRadiance` entirely -- so `PackRadiance` is not the
cause), and on the input side motion vectors, viewZ, `viewZScale`, the `copyMatrix` transpose,
normal encoding, `accumulationMode` / `frameIndex` / prev state, and the permanent-pool binding and
lifetime. The temporal accumulation pass IS scheduled (`NRD4_LOGDISPATCH`).

NOTE the earlier note at `vr_graph.py`'s viewZ selection already recorded "its history never
accumulates -- which makes every temporal setting inert", measured on the plume. That observation was
correct and sat in the tree unexplained; this is the same fault.

STILL OPEN: why the reprojection is rejected at 2%. The test is
`planeDist = abs(prevViewZs - prevViewPos.zzz)` against
`saturate(disocclusionThreshold * slopeScale) * frustumSize`, where `prevViewZs` comes through
`UnpackViewZ` (which is `abs()`, so always positive) and `prevViewPos.z` comes from the view matrix
we supply.

REFUTED, view-space Z SIGN. Falcor's view space is right-handed with -Z forward, so `prevViewPos.z`
is negative while the stored side is positive -- which would give `planeDist ~ 2|z|` everywhere and
explain the fault exactly. It is not that: `NRD4_FLIPVIEWZ=1` negates the view matrix's Z row and
measures 0.07567 against 0.07567 unflipped (0.4%, and marginally worse). NRD evidently resolves
handedness internally. Switch kept, since it is the natural first suspect.

MEASURED with a diagnostic viewport added to `RELAX_Validation.cs.hlsl` (viewport 5, local patch,
reached only under `VR_NRD_VALIDATION=1`; `readdiag2.py` reads it). Static camera, surface branch:

| quantity | value |
|---|---|
| `viewZ` we supply | 21.17 m mean |
| `prevViewPos.z` NRD derives | 17.42 m mean |
| **ratio NRD / ours** | **0.791 median, 0.625 at p05, 0.960 at p95** |
| `frustumSize` | 14.51 m |
| planeDist / frustumSize | 0.305 -- against a threshold of 0.02 |

So the threshold SCALE is fine (14.5 m is sane) and the rejection is driven by a genuine ~4.4 m
disagreement between the view Z we hand NRD and the one NRD derives by reconstructing the world
position. RE-MEASURED with an unsaturated encoding (the previous version stored viewZ/100 in 8 bits, so sky
pixels clipped in both channels and their ratio read 1.0 by construction). Now 0.0% of pixels clip:

| quantity | value |
|---|---|
| ratio NRD / ours | median 0.792, p05 0.620, p95 0.957 |
| ratio by depth quartile | 8-15 m **0.651**, 15-18 m **0.722**, 18-25 m **0.800**, 25-108 m **0.902** |
| planeDist / frustumSize | 0.306 -- against a threshold of 0.02 |

**The ratio rises monotonically toward 1 with depth, which is a CONSTANT OFFSET**, not a scale and
not an angle: solving `ratio = 1 - c/viewZ` per quartile gives c = 4.01, 4.59, 4.30, 3.92 m, i.e.
**NRD's derived view Z is ours minus a roughly constant ~4.2 m**. Identical on both the surface and
volume branches, which take different viewZ textures -- so it is not the texture.

A constant offset along the view axis is a TRANSLATION. That is in tension with `NRD4_RELVIEW=1`
(zeroing the view matrices' translation) changing nothing, and the two can only be reconciled if the
offset is introduced by NRD's own camera-relative rebasing rather than by the matrix we pass.

**CAVEAT, and it may well be the whole answer: the diagnostic itself is suspect here.** It computes
`AffineTransform(gWorldToViewPrev, X)` with a CURRENT-frame X, whereas RELAX's real code builds
`prevWorldPos` through `GetPreviousWorldPosFromPixelPos` and keeps the frame conventions matched. If
NRD's camera-relative origin differs between those paths, a constant offset is exactly what mixing
them would produce -- in which case there is no integration bug here at all and the disocclusion
threshold is being blamed for something else. Distinguishing the two needs the diagnostic to
replicate NRD's exact call sequence rather than borrow its helpers, which is where I stopped.

WHAT IS NOT IN DOUBT, whatever the above turns out to be: raising the threshold restores accumulation
and measurably improves the image (-31% at sigma 32, within 0.4% of the undenoised reference, no
ghosting by eye). The open question is why it is needed, not whether it helps.

SUPERSEDED -- I first called this ratio angular and it is NOT. Fitting it properly:

| | value |
|---|---|
| ratio at frame CENTRE | 0.8065 |
| ratio at CORNER | 1.0000 |
| left / right / top / bottom edges | 0.820 / 0.791 / 1.000 / 0.618 |
| best cos(theta) fit, mean abs error | 0.129 -- WORSE than a flat model's 0.102 |

cos(theta) predicts 1 at the centre falling outward and radial symmetry. The measurement is the
opposite at the corner and strongly asymmetric top-to-bottom, so the ray-distance-versus-view-Z
theory (which would give exactly cos(theta)) is dead.

What it looks like instead is a roughly CONSTANT SCALE near 0.79-0.82 across most of the frame. The
1.000 at the top is almost certainly SATURATION rather than signal -- the diagnostic encodes viewZ as
`viewZ/100` in 8 bits, and sky pixels sit near or past 100 m, so both channels clip and the ratio
comes out 1 by construction. The 0.618 at the bottom is unexplained. **The instrument needs a wider,
unsaturated range before any more is inferred from it**; that, not another hypothesis, is the next
step.

NRD reconstructs camera-relative: `RELAX_Common.hlsli`'s `GetCurrentWorldPosFromClipSpaceXY` returns
`viewZ * (gFrustumForward + gFrustumRight*x - gFrustumUp*y)`, whose view-space Z should be `viewZ`
exactly since Right and Up are perpendicular to Forward. A pure scale error there points at the
frustum basis NRD derives from `viewToClipMatrix`, not at anything positional -- and note a rotation
alone can only produce a RATIO, never a depth-dependent offset, which is a useful constraint on any
future explanation.

REFUTED with positive controls, so these are settled rather than merely untried:
* The `copyMatrix` transpose is CORRECT. `NRD4_NO_TRANSPOSE=1` collapses `frustumSize` to 0.0 and the
  plane ratio to 1.0 -- visibly broken, which is the control proving the diagnostic responds.
* View-space Z sign. `NRD4_FLIPVIEWZ=1` makes the plane ratio WORSE, 0.305 -> 0.520.
* Camera-relative translation. `NRD4_RELVIEW=1` strips the view matrices' translation and changes
  nothing. Verified this is a real test and not a broken edit: Falcor's matrix is row-major with
  `operator[]` returning a ROW, so `m[r][3]` is the translation column for its `mul(M, v)`
  convention, and NRD's `AffineTransform` is `mul(m, float4(p, 1))`, which does apply translation.
  The conclusion is that NRD ignores the translation and works rotation-only, rebasing to
  camera-relative itself -- so the positional part of the handoff is not where the fault is.

CAVEAT on the diagnostic: its first incarnation had a round-trip channel that stayed pinned across
configurations which visibly moved the others, so it was measuring nothing and was replaced. The
current two channels do respond (the NO_TRANSPOSE control above), but the helpers are being called
slightly outside the context NRD calls them in, so treat the ABSOLUTE interpretation as provisional.
What is solid is the relative behaviour and the fact that raising the threshold fixes it.

SUPERSEDED CANDIDATE: the THRESHOLD side rather than the distance side.
Refuted by the measurement above: `frustumSize` comes out at 14.5 m, which is sane for this scene.

Other loose end: `PackRadiance` also binds only
`gDiffuseRadianceHitDist` and `gMaxIntensity` on the RelaxDiffuse path while the shader reads and
writes `gSpecularRadianceHitDist` and reads `gViewZ` / `gNormalRoughness` unconditionally -- harmless
in practice (null UAV writes are dropped) but worth cleaning up, and worth ruling out properly.

## SUPERSEDED: RELAX's temporal accumulation is inert; REBLUR's is not

CORRECTS the section below, which claimed accumulation was dead for the whole integration. It is
not. That test compared `maxAccumulatedFrameNum` 1 against 30 with FULL spatial filtering on, and the
a-trous chain smooths enough to hide the temporal difference. Confounded, same class of error as
using the per-pixel metric for a coarse-scale artifact.

Redone with spatial filtering minimised so the temporal stage is what is being measured. Static
camera, 8 consecutive frames, frame-to-frame difference d1 (raw ReSTIR is 0.27490):

| denoiser, spatial minimised | accum 1 | accum 30 |
|---|---|---|
| RELAX (atrous 2, no history fix, no pre-pass) | 0.07348 | 0.07261 (**1.2%**) |
| REBLUR (pre-pass 0, maxBlurRadius 0, no history fix) | 0.07990 | **0.01003 (8x)** |

**REBLUR's temporal accumulation works. RELAX's does nothing.** Same integration, same
CommonSettings, same input textures, same frame. And REBLUR at 0.01003 with essentially NO spatial
filtering is 7.2x steadier than RELAX at 0.07261 with two a-trous iterations -- so this is not about
filter strength.

RELAX is inert against every setting reachable, all measured with spatial minimised:

| knob | d1 |
|---|---|
| `maxAccumulatedFrameNum` 1 -> 30 | 0.07348 -> 0.07261 |
| `diffuseMaxFastAccumulatedFrameNum` 2 / 6 / 30 (disabled) | 0.07261 / 0.07260 / 0.07260 |
| `fastHistoryClampingSigmaScale` 2 -> 10 | 0.07261 -> 0.07260 |
| `depthThreshold` 0.003 -> 0.02 -> 0.2 (67x looser) | 0.07261 -> 0.07214 -> 0.07207 |

Also refuted from the input and plumbing side: motion vectors (<= 0.25 px static), viewZ (valid,
`viewZScale` defaults to 1 and `UnpackViewZ` is `abs(z)`), the `copyMatrix` transpose
(`NRD4_NO_TRANSPOSE=1` changes nothing), normal encoding (the overlay prints NORMALS 2, matching),
`accumulationMode` / `frameIndex` / prev matrices / prev sizes / prev jitter, the permanent-pool
binding and lifetime (`reinit()` runs only on compile or explicit recreate), and
`disocclusionThreshold` (2.0 percent -> 0.02, the top of NRD's recommended [0.01; 0.02]).

The temporal accumulation pass IS being scheduled -- `NRD4_LOGDISPATCH=<frame>` lists what NRD asked
for, and RELAX_Diffuse schedules 13 passes including "Temporal accumulation", "History fix",
"History clamping" and 6 a-trous. So the pass runs and its result does not reach the output, or it
rejects history for a reason none of the above controls.

WHERE I WOULD LOOK NEXT, given REBLUR works through identical plumbing:
1. Diff the RELAX and REBLUR resource-binding paths in `NRDPass::dispatch` for an input RELAX uses
   that REBLUR does not, or one bound to the wrong slot for RELAX only.
2. `mpPackRadiancePassRelax` versus `mpPackRadiancePassReblur` -- the RELAX pack writes only
   radiance and maxIntensity; check what RELAX_DIFFUSE actually expects in
   `IN_DIFF_RADIANCE_HITDIST` and whether the hit-distance channel it ignores is nonetheless read by
   the accumulation pass.
3. Read `RELAX_TemporalAccumulation.cs.hlsl` end to end for reset paths driven by something not in
   RelaxSettings at all.

The validation overlay is wired (`VR_NRD_VALIDATION=1`) on both paths and its MV viewport is
saturated even on a static camera, which is consistent with 1-3 but has not itself been explained.

## SUPERSEDED: "NRD's temporal accumulation contributes NOTHING here"

Established two independent ways, and it invalidates a lot of what is written below it. Every NRD
result in this project is from a denoiser running with ~1 frame of history, i.e. effectively
spatial-only.

**Functional proof, no interpretation required.** Static camera (`VR_ORBIT_DEG=0`), 8 consecutive
frames, single denoiser, frame-to-frame difference:

| config | d1 | d2 |
|---|---|---|
| raw ReSTIR, no denoiser | 0.27490 | 0.46012 |
| NRD, `maxAccumulatedFrameNum = 1` | 0.03109 | 0.05108 |
| NRD, `maxAccumulatedFrameNum = 30` | 0.03141 | 0.05173 |

One frame of history performs the SAME as thirty. The 8.8x improvement over raw is entirely RELAX's
spatial a-trous; the temporal stage does nothing.

**NRD's own validation overlay agrees** (`VR_NRD_VALIDATION=1`, now wired on both the split and
single paths). With a COMPLETELY STATIC camera at frame 40+:
* The MV viewport is saturated -- black means the supplied motion vector matches the reprojection NRD
  derives from world position; ours disagrees by >= 1 px in both axes with nothing moving.
* DIFF-SPEC FRAMES is covered in NRD's `historyLength < 2` checkerboard across the whole frame. That
  marker is unambiguous and does not depend on reading colours: it is only drawn where history is
  under 2 frames. After 40 static frames it should be pinned at the 30-frame cap.

Identical on the split and non-split paths, so it is the integration, not the split.

REFUTED so far, each measured rather than argued:
* Motion vectors. `GBufferRaster.mvec` is <= 0.25 px on a static camera and `VolumetricReSTIR.mvec`
  is <= 0.0004 px, i.e. correctly zero.
* viewZ. Valid and fully populated -- max 110 m, mean 22 m, 100% non-zero.
* The `copyMatrix` transpose. `NRD4_NO_TRANSPOSE=1` gives 3.8 against 3.9, no change. Kept as a
  switch so it does not need re-deriving.
* Normal encoding mismatch between our packing and the NRD library build. The overlay prints the
  encoding it was compiled with: it reads **NORMALS 2**, matching NRDPass's
  `NRD_NORMAL_ENCODING = 2`.
* `accumulationMode` (left at CONTINUE), `frameIndex` (increments), prev matrices, prev sizes and
  prev jitter (all updated at the end of execute).
* History confidence. The volume branch has none wired at all and shows the same history length.

STILL TO CHECK, in the order I would try them:
1. Whether the history-length resource the overlay reads is even the one RELAX_DIFFUSE_SH writes --
   if the SH variant stores it elsewhere, the overlay reading is wrong and only the functional test
   above stands (that test is the stronger of the two anyway).
2. `viewZ` SIGN. Falcor's view space is right-handed with -Z forward and we feed a positive linearZ.
   NRD uses `abs(viewZ)` in the places checked so far, which is why this is second rather than first,
   but the unprojection path was not read end to end.
3. `IN_VIEWZ` format: NRD asks for "R16f+" and gets RG32Float. Binding is by texture so this should
   be fine, but it has not been verified against what NRD's descriptor expects.
4. Instrument `nrd::GetComputeDispatches` and log which passes NRD actually schedules -- if the
   temporal accumulation dispatch is being skipped entirely, none of the above matters.

THE COROLLARY, and the reason this is at the top of the file: **every temporal conclusion below is
suspect.** "NRD's accumulation is saturated because VolumetricReSTIR already accumulates" was the
earlier explanation for the same observation, and it was wrong -- accumulation is not saturated, it
is not running. Retune after this is fixed, not before.

## Read against NVIDIA's own integration and NRD's own C++ -- four questions closed, one mechanism found

No render cycles, no repro app: NRD-Sample and NRD are both public, so a known-good integration can be
diffed against ours field by field. Both are shallow sparse clones, `Source/` only:

    git clone --depth 1 --filter=blob:none --sparse https://github.com/NVIDIA-RTX/NRD-Sample.git
    git clone --depth 1 --filter=blob:none --sparse https://github.com/NVIDIA-RTX/NRD.git

`NRDSample.cpp:3835-3869` is the whole `CommonSettings` block, and `NRD/Source/InstanceImpl.cpp:356-437`
is everything NRD does to those matrices before the shaders see them. That is the reference this
project never had.

### CLOSED: `NRD4_RELVIEW` and `NRD4_FLIPVIEWZ` are dead ends, and RELVIEW would do harm

Both switches exist because I reasoned about what NRD *must* need. NRD does both itself:

* **Handedness.** `InstanceImpl.cpp:375` runs `DecomposeProjection` on `viewToClipMatrix` to detect
  handedness, and if the projection is not left-handed it negates `viewToClip`'s Z column and
  `worldToView`'s Z row (`:377-389`). Handing NRD a right-handed pair is the supported case, so
  FLIPVIEWZ is redundant.
* **Camera-relative matrices.** `InstanceImpl.cpp:398-408`, commented *"this part is mandatory needed to
  preserve precision by making matrices camera relative"*, reads the camera position out of the inverted
  matrix, zeroes the current translation, and sets the previous translation to the camera **delta**. So
  NRD wants the translation left in. Stripping it first is not neutral: both extracted camera positions
  become zero, `translationDelta` and therefore `m_CameraDelta` come out zero, and RELAX adds
  `gCameraDelta` to every reprojected position (`RELAX_TemporalAccumulation.cs.hlsl:413`). RELVIEW=1
  would break reprojection under camera motion -- the one case this project is about.

Both still default off, which is why neither ever did damage. Comments in `NRDPass.cpp` corrected.

### CLOSED: the constant-viewZ-offset theory, refuted by REBLUR working

The standing story was that our `IN_VIEWZ` disagrees with NRD's reconstruction by a constant, and that
the disagreement is what the plane test rejects on. **REBLUR's test is structurally identical to
RELAX's** and REBLUR accumulates fine on the *same* `CommonSettings` object:

    REBLUR_TemporalAccumulation.cs.hlsl:272   Xvprev = AffineTransform(gWorldToViewPrev, Xprev)
                                       :273   smbPlaneDist0 = abs(prevViewZ0 - Xvprev.z)
    RELAX_TemporalAccumulation.cs.hlsl:119    prevViewPos = AffineTransform(gWorldToViewPrev, prevWorldPos)
                                       :120   planeDist0 = abs(prevViewZs00.yzw - prevViewPos.zzz)

`frustumSize` is the same quantity in both (`min(rect) * gUnproject * viewZ`), and the threshold curves
differ by at most ~1.4x across the NoV range, nowhere near the 35x we need. Anything wrong in
`CommonSettings`, in `IN_VIEWZ`, or in the shared threshold maths would break both. So the fault is not
there, and every "our viewZ is off by X" reading -- the 0.8078, the 4.2 m -- cannot be the cause even
if the numbers themselves are real.

### THE ASYMMETRY: RELAX round-trips through the previous projection; REBLUR does not

This is the first mechanism that predicts "REBLUR fine, RELAX broken" rather than assuming it. With 2D
motion vectors (`gMvScale.z == 0`, our case -- `motionVectorScale[2] = 0`), the two build `prevWorldPos`
by different routes:

    REBLUR :171  Xprev = RotateVectorInverse(gWorldToViewPrev, Xvprevlocal) + gCameraDelta
    RELAX  :413  prevWorldPos = GetPreviousWorldPosFromClipSpaceXY(prevUV*2-1, currentLinearZ + mv.z)
                              + gCameraDelta

REBLUR's route is a pure matrix rotation. RELAX's goes through `gPrevFrustumForward/Right/Up`, and those
are built (`NRD/Source/Relax.cpp:52-77`) from `m_ViewToClipPrev.a00`, `.a11`, `m_WorldToViewPrev` and
`m_FrustumPrev` -- where `m_FrustumPrev` comes from `DecomposeProjection` reading our projection's
off-diagonal terms. The test at `:119` then transforms that reconstruction *back* by
`gWorldToViewPrev`. **That round trip must return the depth it started from, and it is exact only if
the frustum basis is consistent with the projection we hand over.** RELAX is the only one of the two
that is sensitive to it.

The tempting part: the withdrawn "0.8078x frustum basis" and the withdrawn "constant 4.2 m viewZ
offset" are the *same* number if the diagnostic region sat around viewZ 21.8 m
(21.8 - 0.8078*21.8 = 4.2), which looks like a scale error in exactly this round trip.

**It is not. The round trip is exact, and this mechanism is dead too.** Checked in float64 against the
matrices we actually hand NRD rather than through the diagnostic viewport, which has saturated once
already: `relax_roundtrip_check.py` beside this file, matrices from `NRD4_LOGMATRIX=1` on bistro.

    round trip  AffineTransform(gWorldToView, reconstruct(clipXY, viewZ)).z / viewZ
      worst deviation from 1.0 over the frame and 0.5..200 m : 4.495e-07
      input precision floor (10x the logged orthonormality error): 5.502e-06

and it is exact *structurally*, not numerically-by-luck. The plane test only uses the `.z` of the round
trip, and `z = dot(row2, viewZ*(F + R*clipx - U*clipy))`. `F` is `row2` itself; `R` and `U` are scalar
multiples of `row0` and `row1`, which are orthogonal to `row2`. The clipXY terms vanish identically, so
`z == viewZ` for **any** fov, aspect, or position in the frame. Our projection is exactly symmetric
(off-diagonal xy terms are 0.000e+00) and the view rotation is orthonormal to 5.5e-07.

Two consequences worth keeping:

* A wrong fov or a misread projection **could not show up in this test at all**, so it is not evidence
  that the projection is right -- only that the frustum basis cannot be what rejects reprojection.
* The control I had written up as decisive one commit earlier would have returned 1.0 and proven
  nothing. Deriving it on paper cost minutes; building the viewport instrument for it would have cost
  a day and produced a confident wrong answer. Do the algebra first when the quantity is analytic.

**Where that leaves the test.** With the geometry proven exact, the plane test reduces to exactly what
it is supposed to be:

    planeDist = | storedPrevViewZ(at the reprojected pixel) - depthOfCurrentSurfaceInPrevView |

There is no room left for a matrix or convention bug. It can only fail if the motion vector points at
the wrong pixel, or if `IN_VIEWZ` is wrong -- and both of those are shared with REBLUR.

**A reframing was the next hypothesis, and it is now REFUTED.** The idea was that REBLUR's test rejects
just as often and REBLUR merely does not *flicker* when it does, its Poisson-disc hit-distance spatial
pass having something stable to fall back on where RELAX's variance-weighted a-trous does not. Measured
from the validation overlay's DIFF FRAMES viewport, `NRD4_MAXACCUM=NRD4_R_MAXACCUM=30`, bistro,
surface half:

| configuration | history mean | median | at full cap |
|---|---|---|---|
| REBLUR, static camera, disocc 1% | **24.12** | 29.86 | 64.9% |
| RELAX, static camera, disocc 1%  | **0.05**  | 0.05  | 0.0%  |
| RELAX, static camera, disocc 35% | 8.15      | 0.05  | 26.9% |
| REBLUR / RELAX, orbiting, disocc 1% | 0.05 / 0.11 | | 0.0% |

REBLUR does not reject as often. On a static camera it reaches full history while RELAX reaches zero,
so there is a real denoiser-specific fault and the reframing is wrong.

### The static camera is the important part, and it moves the whole problem

With a static camera `mv = 0`, so `prevWorldPos == currentWorldPos` and the plane distance is
identically zero. **No disocclusion threshold can matter, yet RELAX still rejects.** Whatever kills
RELAX's history is therefore *not* the plane test at all -- which means the 35% threshold has been
treating a symptom, and it also explains why raising it only ever recovered part of the frame
(26.9% at full cap, median still 0.05).

Note this does not undo the shipped fix: 2% -> 35% is still measurably better by eye and by metric.
It just is not addressing the cause.

**Ruled out by measurement, not by argument:** `IN_DIFF_CONFIDENCE`. RELAX multiplies its accumulation
*cap* by confidence (`RELAX_TemporalAccumulation.cs.hlsl:598`) while REBLUR only lerps its accumulation
*speed* toward 1.0 (`REBLUR_TemporalAccumulation.cs.hlsl:368`), so a near-zero confidence would kill
RELAX's history and barely touch REBLUR's -- exactly the observed asymmetry, and it is an input this
project added itself for the see-through fix. Captured and measured: confidence is **1.0 over 86.5% of
the frame** (mean 0.887, median 1.000), so 86.5% of pixels have an unmodified cap of 30 and still show
zero history. Not the cause.

### LOCALISED by shader control: it IS the plane-distance threshold, and it fires on a static camera

Three patches to `RELAX_TemporalAccumulation.cs.hlsl`, static camera, `NRD4_DISOCC=1`, surface half:

| patch | history mean | at full cap |
|---|---|---|
| none (baseline) | 0.05 | 0.0% |
| backfacing gate disabled (`dot(N, prevN) < -2.0`) | 0.05 | 0.0% |
| `smbDisocclusionThreshold = 1e6` **after** the screen test | **29.95** | 100% |
| `smbDisocclusionThreshold = 1e6` **before** the screen test | **29.95** | 100% |
| REBLUR, for reference | 24.12 | 64.9% |

The third row is the positive control that makes the second row mean anything: shader edits do reach
the GPU, so the backfacing gate's null result is a real null and that candidate is dead. The fourth row
separates the two things the third could not: `IsInScreenBilinear` is not involved, because leaving it
applied changes nothing. **It is the threshold comparison itself.**

So my "with a static camera mv = 0, therefore the plane distance is zero, therefore no threshold can
matter" was wrong. The plane distance is NOT zero on a static camera -- `planeDist` genuinely exceeds
1% of `frustumSize` there, and bypassing that one comparison restores a full 30-frame history.

That partially rehabilitates the withdrawn viewZ-disagreement story, with one thing still unexplained:
REBLUR's test compares the same two quantities and does not reject. The difference between them is how
`prevWorldPos` is built -- REBLUR by a pure matrix rotation, RELAX through the frustum basis (see the
asymmetry section above) -- so the two arrive at different `planeDist` values from the same inputs.

### MEASURED: a constant ~7 m offset in NRD's reconstructed previous view Z, on a static camera

The measurement below was run rather than reasoned about. `planeDist` and the reconstruction ratio were
routed out of `RELAX_TemporalAccumulation.cs.hlsl` through a shader global into the history-length
channel -- legitimate because `planeDist` depends only on viewZ, motion and matrices, never on history
length, so borrowing that channel cannot corrupt the value being measured -- and read back with the
calibrated viewport-8 decoder.

    planeDist / frustumSize, static camera      median 0.507   (must be ~0)
      exceeds the 1% threshold                  100.0% of pixels
      exceeds even 35%                           72.5% of pixels

That last figure is the consistency check worth keeping: 100 - 72.5 = 27.5% of the frame should survive
at the 35% setting, against the 26.9% at full cap measured independently from the history length. Two
different instruments, same number.

Then each side of the comparison separately. `prevViewPos.z / currentLinearZ` must be exactly 1.0 when
the camera cannot move:

| viewZ band | ratio | implied offset in `ratio = 1 - c/viewZ` |
|---|---|---|
| 10-20 m | 0.533 | **7.0 m** |
| 20-30 m | 0.698 | **7.6 m** |
| 30-50 m | 0.833 | **6.7 m** |

**The error is ADDITIVE, not a scale.** A constant ~7 m is subtracted from the reconstructed previous
view Z. That is the same phenomenon as the withdrawn "constant 4.2 m offset" (different camera pose),
and it finally has a shape: a constant offset in `AffineTransform(gWorldToViewPrev, X).z` is a
TRANSLATION term, which on a static camera should be exactly zero.

NRD builds that translation itself: `InstanceImpl.cpp:398-408` extracts both camera positions, zeroes
the current translation and sets the previous one to `translationDelta = cameraPositionPrev -
cameraPosition`. With a camera that does not move that delta must be zero. **So the next thing to check
is whether `worldToViewMatrixPrev` and `worldToViewMatrix` are actually equal on a static frame** --
they are both built from `mpScene->getCamera()->getViewMatrix()` with `mPrevViewMatrix` assigned at the
end of the same function, so they should be, and if they are not the fault is in our code and is
directly fixable.

Ruled out along the way, each by control rather than argument: the matrix transpose
(`NRD4_NO_TRANSPOSE` is genuinely wired inside `copyMatrix` and changes this ratio not at all), and
`GBufferRaster.linearZ`, which despite being computed as `posH.z * posH.w` does come out as view-space
Z in metres (median 18.8, max 110 on this frame).

**Fourth instrument bug, same file as the trap that documents it:** the first decode of this read EXR
channel 0, which is empty -- OpenCV reads EXR as BGR so Falcor's `.x` is index **2**. That is written
down in "Traps that have already cost time" below, and I walked into it anyway. It made every depth
land in one bucket and hid the additive shape for a full round. When a per-pixel breakdown looks
degenerate, check the channel before believing the aggregate.

### FIXED: every NRD matrix reached the shader TRANSPOSED, and correcting it retires the workaround

Shipped in `RELAX_Config.hlsli`: the four matrix constants are declared under `*_raw` names and the
used names are `#define`d as `transpose( ..._raw )`. Renaming moves nothing in the buffer, so NRD's
`memcpy`'d blob still lines up byte for byte and only the interpretation changes; every call site is
untouched, and no pass ends up referencing a constant its own resource block does not declare -- which
is what broke the earlier attempt in `RELAX_Common.hlsli`.

**Result, static camera, NRD's documented 1% threshold, surface half:**

| | history mean | median | at full cap |
|---|---|---|---|
| before | 0.05 | 0.05 | 0.0% |
| **after** | **29.80** | **29.95** | **99.1%** |
| REBLUR, untouched | 24.12 | 29.86 | 64.9% |

**Result, bistro's authored orbit, instability by spatial scale (x1e-3):**

| configuration | s=32 | s=128 | whole-frame |
|---|---|---|---|
| broken, 2% | 19.52 | 8.19 | 5.87 |
| broken, 35% (the workaround) | 8.57 | 3.16 | 1.75 |
| **FIXED, 2%** | **7.41** | **2.74** | **1.51** |
| FIXED, 35% | 7.29 | 2.68 | 1.49 |
| REBLUR | 7.01 | 2.51 | 1.33 |
| Ray Reconstruction | 7.92 | 2.72 | 1.52 |

62% better at the documented threshold, and **the threshold now barely matters** (2% against 35% is
1.6%) -- which is the signature of a workaround that has stopped doing anything. `NRD4_DISOCC` is
therefore back to **2**, inside NRD's documented `[0.01; 0.02]`, and it beats the old 35% workaround
outright. RELAX now edges past Ray Reconstruction at s=32 and sits ~6% behind REBLUR.

**Controls run, because "it must be fine" has been wrong here before:**

* REBLUR before vs after the RELAX-only edit: `max|diff| = 0.000000e+00`. Untouched, so it remains a
  clean control and its numbers stand.
* Energy against the undenoised image of the same frame: fixed is 1.5% under raw, REBLUR 1.3% over --
  same band, so this is not an energy loss.
* The image is *cleaner*, not just steadier: p99 drops 0.52 -> 0.31 and pixels above 0.5 go 1.4% ->
  0.9%, which is firefly suppression from accumulation that is finally running.

**Still to do:** `REBLUR_Config.hlsli` and `SIGMA_Config.hlsli` carry the same fault and are NOT fixed.
REBLUR may be surviving *because* of the transposition -- its reprojection uses `RotateVectorInverse`,
which transposes internally -- so correcting it could change REBLUR's output either way, and every
REBLUR number in this file would need re-measuring. Do that as its own piece of work, with the
byte-difference control first.

### How it was proven, before the fix

    Geometry::RotateVector(          gWorldToViewPrev , gPrevFrustumForward.xyz ).z  =  0.7984
    Geometry::RotateVector( transpose(gWorldToViewPrev), gPrevFrustumForward.xyz ).z =  0.9984   <- 1.0

The shader's copy of every NRD `float4x4` is the transpose of what NRD's C++ wrote. `float4`
constants like `gFrustumForward` are unaffected, and that asymmetry -- correct vectors, transposed
matrices -- is exactly what produces `(M^2)_33 = 0.8068` and every downstream symptom in the table
above.

**Why this is our bug and nobody else's.** NRD ships **precompiled shader bytecode**:
`PipelineDesc` carries `computeShaderDXBC / computeShaderDXIL / computeShaderSPIRV`
(`NRDDescs.h:441-454`), and the reference integration consumes it --
`NRDIntegration.hpp:216` picks `nrdPipelineDesc.computeShaderDXIL`. NRD builds those blobs itself with
ShaderMake/DXC and **no matrix-layout flag**, i.e. HLSL's default column-major
(`NRD/CMakeLists.txt:334-352`). `shaderIdentifier` is documented as being for "custom integrations".

We are a custom integration: `NRDPass.cpp` ignores the bytecode and recompiles
`nrd/Shaders/*.cs.hlsl` through Slang, then `memcpy`s NRD's raw constant blob into a D3D12 CBV
(`:2447-2448`). A raw blob against a differently-packed cbuffer is only correct if the layouts match,
and for matrices they do not.

**And the layout cannot be steered from our side.** All three attempts leave the denoised output
**byte-identical** (`max|diff| = 0.000000e+00`), with the shader cache deleted each time:

* `SlangCompilerFlags::MatrixLayoutColumnMajor` on / off -- and Falcor does forward it to Slang
  (`ProgramManager.cpp:745-746`), so the option is reaching the compiler and being ignored.
* `#pragma pack_matrix(row_major)` ahead of the includes, where it governs the cbuffer declarations.

An inert knob and a correct setting produce the same null, so each of these had to be checked with the
byte-difference control before it meant anything. The first of them looked like a clean null purely
because the shader cache was stale.

**The fix.** Transpose NRD's matrix constants at the point where the shaders read them. Confirmed to
restore the value exactly. It has to be applied to *every* matrix constant, not just this one -- the
transposition is a property of the cbuffer, so `gWorldToViewPrev`, `gWorldToClipPrev`,
`gWorldPrevToWorld` and the REBLUR/SIGMA equivalents are all affected. The contained way to do it is in
the `*_Config.hlsli` headers: declare each matrix under a raw name and add
`#define gWorldToViewPrev transpose(gWorldToViewPrev_raw)`, so no call site changes and no pass needs a
constant it does not declare -- which is what broke the earlier attempt in `RELAX_Common.hlsli`.

Two things to verify while doing it. **REBLUR probably survives by accident**: its reprojection uses
`RotateVectorInverse`, which transposes internally, so a transposed matrix makes it behave like
`RotateVector` -- possibly right for its use, which would explain why REBLUR accumulates fine on the
same broken constants. Fixing the layout may therefore *change* REBLUR, and its numbers must be
re-measured rather than assumed stable. And `gFrustumRight` / `gFrustumUp` are vectors, so they were
never transposed -- but they are built on the CPU from `m_WorldToView.Row(0)` and have not been checked
independently; a lateral error is invisible in every `.z` measurement above.

### REINSTATED: the frustum-forward basis really is 0.80x, and it is the root cause

The withdrawn "0.8078" section below was **right**. It was withdrawn because the instrument saturated
and looked unresponsive to `NRD4_PROJ`; the number itself was never wrong. Re-measured cleanly, the
value is a hard constant over the entire frame:

    dot(viewForward, gPrevFrustumForward)   median 0.7984   p05 0.7984   p95 0.7984

**This must be exactly 1.0 by construction.** NRD's own comment in `Relax.cpp:56` says the vector is
deliberately left unnormalised so that its view-space z is 1.0 -- that is what makes
`GetPreviousWorldPosFromClipSpaceXY`'s `viewZ * (F + R*x - U*y)` reconstruct a point at depth `viewZ`.
The encoding quantises to 1/30 = 0.033, so 0.7984 and the earlier 0.8078 are **the same number**.

The chain, all measured on a static camera where every one of these must be exact:

| quantity | must be | measured |
|---|---|---|
| `dot(viewForward, gPrevFrustumForward)` | 1.0 | **0.798** (constant) |
| `(currentLinearZ + mv.z) / currentLinearZ` | 1.0 | 0.73-0.90 (~ -4 m) |
| `prevViewPos.z / currentLinearZ` | 1.0 | 0.63 (~ -7 m) |
| `planeDist / frustumSize` | ~0 | 0.507 |

The error compounds down the chain because the basis is used twice. The "constant 4.2 m offset" of
commit 17a4b86 was also real -- it is this same 0.8 expressed at that camera's depths.

**What the constant tells us.** `frustumForwardView.z` is the literal constant 1.0, so the lateral
frustum terms cannot affect this; the round trip `RotateVector(worldToView, viewToWorld * (a,b,1,0)).z`
is 1.0 for *any* fov, aspect or frustum asymmetry, and fails only if `viewToWorld` and `worldToView`
are not exact inverses. NRD derives one from the other with `InvertOrtho` (`InstanceImpl.cpp:392-408`),
which is an involution **only when the 3x3 is orthonormal**. So the 3x3 NRD ends up with is not
orthonormal, by a factor whose square is ~0.80, i.e. a scale of ~0.893 on the basis.

Ruled out by control: the matrix transpose. `NRD4_NO_TRANSPOSE` moves this scalar not at all (0.7984
both ways), which makes sense -- transposing flips the basis and the transform together and the dot is
invariant to it. So this is NOT the layout question that the old section assumed, and `NRD4_PROJ`'s
unresponsiveness was never evidence against the number.

Also ruled out by measurement this round: a spurious camera translation. `NRD4_LOGDELTA` logs
`max|view - viewPrev| = 0.000000` and `cameraDelta = (0,0,0)` on every static frame for both instances,
with the camera position matching bistro's authored pose exactly. So `gCameraDelta` contributes nothing
and the offset is entirely the basis.

**The two models, and the one that survived.** `dot(viewForward, F) = 0.807` is explained either by
(a) a transposed multiply somewhere in the basis construction, or (b) a uniform scale `s` on the 3x3
with `s^2 = 0.807`, i.e. `s = 0.898`. They differ in one measurable:

    length(RotateVector(gWorldToViewPrev, float3(1,0,0)))   measured 0.9984   (1.0 within 1/30 quantisation)

**The matrix is orthonormal, so model (b) is dead and (a) is what is happening.** The arithmetic
closes exactly: with the logged view matrix, `(M^2)_33 = 0.8068`, matching the earlier independent
0.8078 to three decimals and inside the quantisation band of the 0.7984 measured on the GPU. Computed
without NRD's RH->LH negation the same model gives 0.6497, so the handedness conversion is confirmed to
be happening correctly and is not the fault.

Corroboration, four independent ways: the GPU scalar, the CPU arithmetic on the logged matrix, the
earlier 0.8078, and the model's prediction that the value is invariant to transposing our input --
which it measurably is, with a control proving the switch is live (`NRD4_NO_TRANSPOSE` changes the
denoised output by max 51.1 while leaving the scalar at 0.7984).

Ruled out this round, each by control rather than argument:

* **A scale on the matrix** -- the basis measures orthonormal at 0.9984.
* **Our transpose choice** -- `(A^2)_33` is invariant to it, and it measurably is.
* **A spurious camera translation** -- `NRD4_LOGDELTA` reports `max|view - viewPrev| = 0.000000` and
  `cameraDelta = (0,0,0)` on every static frame for both instances.
* **My own instrument's frame ordering and channel** -- see the corrections above; both were real bugs
  and both are fixed in the tools committed beside this file.

**Shader matrix packing is UNTESTED, not ruled out.** This is the candidate the arithmetic actually
points at: `(M^2)_33` is exactly what you get when the shader's copy of a matrix is the transpose of
what NRD's C++ wrote, because the frustum vectors are `float4`s and are unaffected by matrix packing
while the matrices are. `NRDPass.cpp` does set `SlangCompilerFlags::MatrixLayoutColumnMajor`, and I
added `NRD4_ROWMAJOR=1` to flip it -- but **the flag is inert**. With the shader cache deleted, the two
settings produce a byte-identical denoised output (max|diff| = 0.000000e+00) and leave the scalar at
0.7984 either way, so the flag never reaches how these programs read their matrices. That makes the
experiment inconclusive; it is not evidence that packing is fine. The switch is kept, off, so the next
attempt does not rebuild it and hit the same dead end.

To actually test packing, the layout has to be forced in a way that demonstrably changes the shader:
`#pragma pack_matrix(row_major)` injected into NRD's headers, or a `row_major` qualifier on the
constant declarations in `RELAX_Config.hlsli`, verified live by the same byte-difference control before
any conclusion is drawn from it.
* **My own instrument** -- `ml.hlsli:536` defines `RotateVector(m, v)` as `mul((float3x3)m, v)`, a
  proper column-vector multiply, so the diagnostic means what it says. This mattered: if it had been a
  row-vector multiply, a *correct* NRD would also have produced 0.8068 and the fault would have been
  mine.

**Attempted fix, and why it is not in the tree.** Rebuilding the forward from the matrix --
`RotateVectorInverse(gWorldToViewPrev, float3(0,0,1))`, whose view-space z is 1.0 by construction --
substituted into `RELAX_Common.hlsli` does not compile: that header is included by every RELAX pass,
and passes like `RELAX_HitDistReconstruction` do not declare `gWorldToViewPrev`. A working version has
to be guarded per pass, or confined to the two reconstruction functions the temporal accumulation pass
actually calls. That is the next piece of work and it is mechanical rather than investigative.

Two cautions for whoever does it. First, `gFrustumRight` and `gFrustumUp` are built from the same
matrix on the CPU (`Relax.cpp:68-70`) and have **not** been checked -- a lateral error is invisible in
the `.z` measurements above, so verify them before assuming only the forward is wrong. Second, RELAX
declares no `gWorldToView`, only `gWorldToViewPrev`; substituting one for the other is valid only while
the camera is static, which is a test, not a fix.

**Method note.** Three of the four "withdrawn" characterisations in this file were withdrawn on
instrument grounds, and this one should not have been. A saturating instrument invalidates the
measurement, not the hypothesis -- the right response was to rebuild the instrument, which is what
finally worked here (float-derived encoding, self-calibrating decoder, positive control that the edit
reaches the GPU).

**The step after that is now a single well-defined measurement, not a hypothesis:** print
`planeDist / frustumSize` from RELAX's temporal accumulation on a static camera and see what it
actually is and how it varies over the frame. `CommonSettings::debug` (`gDebug`) exists for exactly
this and is already plumbed. If it is a constant, that constant is the bug; if it tracks depth or
screen position, that shape names the term. Do this before proposing any further cause.

**Ruled out (was the next candidate):** the backfacing-history rejection at
`RELAX_TemporalAccumulation.cs.hlsl:144-149` -- `if (dot(currentNormal, prevNormalFlat) < 0) { all taps
invalid }`, comparing IN_NORMAL_ROUGHNESS against RELAX's own `gPrev_Normal_Roughness` history. REBLUR
has no equivalent gate. It fires unconditionally, before any threshold, which fits "rejects even when
the camera cannot move". Both halves take their normals from the same adapter output that REBLUR reads,
so the normals themselves are probably fine and the suspicion falls on RELAX's previous-normal history
being unwritten or misread. One run with the normal test neutered settles it.

### Two instrument bugs, and why `histlen.py` must not be used again

The first read of this measurement produced three near-identical rows, medians of exactly 7.5 for every
configuration -- the "identical rows mean the knob is not wired" trap from the list below. Both bugs
were in the reader, not the data:

1. `f == 0.75` is the shader's **"history under 2 frames" marker**, not a value. Decoding it literally
   gives `(1 - 0.75) * 30 = 7.5`, which is where every 7.5 came from. The marker is drawn on one phase
   of a static 4x4-block checkerboard, so the other phase is clean.
2. `f == 0` is **not sky**, it is a FULL history (`f = 1 - hl/cap`). Treating it as sky and dropping it
   discarded the most-accumulated pixels -- which is why one fixed camera reported "sky" fractions of
   0%, 65% and 27% across three runs. Sky is masked from `linearZ` instead.

`nrd_history_length.py` beside this file is the corrected reader. It decodes both checkerboard phases
and prints both, so a contaminated read announces itself instead of being trusted. `histlen.py` in the
scratchpad is wrong; do not reuse it.

### CORRECTION: the published instability table is inflated ~2.2x, and one claim in it is reversed

`scale.py` loaded frames with `sorted(glob("fl.*.png"))`. The capture range is frames 40..129 and the
names are not zero-padded, so that sorts **100,101,...,129,40,41,...,99** -- and the metric is a SECOND
temporal difference, which is meaningless on a scrambled order. Measured both ways on the same
sequences:

| REBLUR, authored orbit | sigma=32 | sigma=128 |
|---|---|---|
| published artifact table | 15.92 | 9.14 |
| reproduced with the scrambled order | 15.43 | 8.90 |
| **correct numeric order** | **7.01** | **2.51** |

REBLUR's configuration has not changed since publication and its published numbers reproduce the
scrambled order to within 3%, so the published table was produced with the bug. Corrected, on the same
90-frame orbit at 1280x720:

| config | s=0 | s=8 | s=32 | s=128 |
|---|---|---|---|---|
| RELAX, disocc 20% (the artifact's row) | 259.86 | 50.94 | 10.97 | 4.16 |
| RELAX, disocc 35% (today's default)    | 261.55 | 47.29 | 8.57  | 3.16 |
| REBLUR                                  | 272.56 | 44.65 | 7.01  | 2.51 |
| DLSS Ray Reconstruction                 | 259.94 | 48.74 | 7.92  | 2.72 |

What survives and what does not:

* **Survives:** raising the disocclusion threshold helps, and by more than was claimed -- 20% -> 35%
  takes sigma=32 from 10.97 to 8.57 (-22%) and sigma=128 from 4.16 to 3.16 (-24%). The ranking
  RELAX-worse-than-REBLUR at sigma=32 survives, and the ratios there are almost unchanged (published
  1.224, corrected 1.222).
* **Reversed:** the artifact's claim that the fix "puts RELAX *ahead of* Ray Reconstruction at
  sigma=128". At the artifact's own 20% setting RELAX is 4.16 against RR's 2.72 -- 53% **worse**, not
  ahead. The bug inflated sigma=128 unevenly (2.8x for RELAX against 3.7x for REBLUR and RR) because
  scrambling hurts a smooth sequence more than a jumpy one, and that uneven inflation is what
  manufactured the win.

`nrd_instability_by_scale.py` beside this file is the corrected metric; it prints both orderings so the
size of the error stays visible. `scale.py` in the scratchpad is wrong -- same class of bug as
`histlen.py`, and the third instrument fault in this investigation.

**And the answer to "does RELAX still flicker": yes.** At today's default it is 22% worse than REBLUR
at sigma=32 and 26% worse at sigma=128, and worse than RR at both. The remaining gap is real, it is
much smaller than it was, and it is consistent with RELAX's temporal accumulation still being mostly
dead (history 0.05 frames on a static camera, above).

`make_orbit_video.py` builds videos of the authored orbit for eye judgement -- same path as the
published page, numeric frame order, crf 14 so the encoder does not smooth away the artifact being
judged.

### Viewing captures: bistro is EV+8 or it looks broken

`vr_graph.load_bistro` sets `exposure: 8.0` with the comment "Night exterior lit only by emissive
geometry: without this the frame is 256x too dark". Tonemapping a raw HDR capture without applying it
leaves only the emissive lights visible against black, which reads exactly like the volume and surfaces
having failed to render. This wasted a round trip. `look_at_captures.py` beside this file applies it;
`LOOK_EV` overrides.

### FIXED: camera jitter was passed in UV, NRD wants pixels

`NRDSample.cpp:3657` computes its own shader-side jitter as `viewportJitter / rectSize` and hands the
**undivided** `viewportJitter` to `commonSettings.cameraJitter` (`:3843`). So NRD's jitter is in pixels,
and the header's "[-0.5; 0.5] sampleUv = pixelUv + cameraJitter" is describing a pixel magnitude.
Falcor's `getJitterX()` is documented as "subpixel offset along X axis divided by screen width" -- UV.
We passed it straight through, so NRD was told the camera jitter was ~1/1280 of its real value.

Inert at the default (`VR_NRD_JITTER` is off), but it **invalidates the measurement recorded beside that
default** in `vr_graph.py`: "jitter on 6.93e-4, jitter off 6.50e-4 -- 6% worse with it". That was a
denoiser told about the jitter versus a denoiser told nothing about it, not evidence that jitter hurts.
Re-measure before trusting it. Fixed in `NRDPass.cpp`.

### Noted, not yet chased

`denoisingRange` is a hardcoded `kNRDDepthRange = 10000`; the sample uses `4 * sceneAABBradius`
(`NRDSample.cpp:360`). NRD's header says pixels with `viewZ < denoisingRange` are valid and that sky
should be pushed *above* it. At 10000 nothing in bistro is ever excluded, so sky may be being denoised
as geometry. Cheap to check, unknown whether it matters.

## WITHDRAWN: "root cause found -- frustum-forward basis is 0.8078x"

Read this before trusting the section below it. **The 0.8078 measurement is not what I claimed and
the root cause is NOT found.** Two errors, both mine:

1. The "dot product" used `Geometry::AffineTransform`, which is `mul(m, float4(p,1))` and therefore
   applies the view matrix's TRANSLATION -- -16.05 in z for this camera. Applying that to a
   DIRECTION vector mixes a direction with a position and yields a number that means nothing. Fixed
   to `Geometry::RotateVector`.
2. With that fixed the value is STILL exactly 0.8078, and still identical across materially
   different projection matrices -- which cannot be true of a quantity NRD derives from the
   projection.

The switch was verified to work rather than assumed: `NRD4_PROJ=4` (transposed projection) changes
the denoised output by max 3.8e-01, while `NRD4_PROJ=2` (negated w row, i.e. left-handed) is
BYTE-IDENTICAL to the baseline. So the plumbing is live, some variants are no-ops inside NRD, and the
diagnostic value tracks none of them.

Conclusion: the diagnostic still is not measuring `dot(gFrustumForward, viewForward)`, and every
interpretation built on it -- angular mismatch, constant offset, 0.808x frustum scale -- is
unsupported. `NRD4_PROJ`, `NRD4_LOGMATRIX`, `NRD4_NO_TRANSPOSE`, `NRD4_FLIPVIEWZ` and `NRD4_RELVIEW`
are all kept, since they work and the next attempt should not have to rebuild them.

**What survives, and is independent of any of this:** RELAX's history IS being rejected, raising
`disocclusionThreshold` measurably fixes it (surface half at sigma 128: 79.5 -> 18.5), the surface
half is where the flicker lives, and the shipped improvements are verified against the undenoised
image and by eye. The mechanism is established; only the explanation for WHY the plane test fails
remains open, and it is now open with a better toolset and four dead ends ruled out.

Method note, the expensive one: I called this a root cause because a single constant number with a
prediction that matched felt conclusive. The prediction matching (24% predicted, 20-35% measured) was
real but it is weak evidence -- a wrong quantity of roughly the right magnitude produces the same
agreement. The control that mattered was "does this number respond when I change what it supposedly
depends on", and I ran it only afterwards.

## SUPERSEDED: NRD's frustum-forward basis is 0.8078x instead of 1.0

One scalar explains the whole chain. `RELAX_Common.hlsli`:

    GetCurrentWorldPosFromClipSpaceXY(clipXY, viewZ) = viewZ * (F + R*x - U*y)

At the frame CENTRE the R and U terms vanish, so the view-space Z of that reconstruction is exactly
`viewZ * dot(F, viewForward)`, which must be **1.0 by construction**. Measured with a diagnostic
viewport added to `RELAX_Validation.cs.hlsl` (`readdiag4.py`):

    dot(gFrustumForward, viewForward) = 0.8078   median = p05 = p95, CONSTANT over the whole frame

No spatial variation, no saturation, no dependence on anything -- a clean uniform scale error.

**It predicts the rest quantitatively**, which is what makes it the root cause rather than another
correlate:

| step | value |
|---|---|
| plane distance = (1 - 0.8078) * viewZ | 0.192 * 18.15 m = **3.49 m** |
| frustumSize | 14.51 m |
| threshold needed for history to survive | 3.49 / 14.51 = **24%** |
| measured: 20% leaves 68.8% of pixels failing, 35% works | **prediction lands between them** |

So: NRD reconstructs world positions 0.808x too short along the view axis -> its derived previous
view Z disagrees with the `IN_VIEWZ` we supply by 19% -> the plane-distance test rejects history
everywhere -> RELAX loses temporal accumulation -> the surface half is 3.2x cleaner than its input
where REBLUR's is 12x -> large-scale surface flicker under camera motion. REBLUR is less affected
because its plane test is formulated differently and is more tolerant.

The matrices we hand NRD (`NRD4_LOGMATRIX=1` dumps them once):

    projNoJitter  [1.640625 0 0 0][0 2.916667 0 0][0 0 -1.000001 -0.001][0 0 -1 0]
    nearZ 0.001  farZ 1000  aspect 1.7778  focalLength 35  frameHeight 24

That is a textbook RH D3D projection: `tan(fovY/2) = 1/2.916667 = 0.342857` gives fovY 37.85 deg,
which matches focalLength 35 / frameHeight 24 exactly, and `P[0][0] = P[1][1]/aspect` checks out.
Nothing is obviously malformed, so the mismatch is a CONVENTION difference in how NRD derives its
frustum from it.

REFUTED, each with the diagnostic responding to a positive control:
* Near plane. 0.001 / 0.1 / 1.0 all give exactly 0.8078, so the 1e6 near:far ratio is not it.
* The `copyMatrix` transpose. Removing it collapses `frustumSize` to 0.0 -- the transpose is right.
* View-Z sign (`NRD4_FLIPVIEWZ`) and view translation (`NRD4_RELVIEW`): worse, and no effect.

For reference, a unit-normalised frustum CORNER ray would give
`1/sqrt(1 + (aspect*t)^2 + t^2) = 0.8195` -- close to 0.8078 but not equal, so "F is normalised
rather than scaled to unit view-Z" is suggestive and not proven.

NEXT: NRD derives this inside the closed library, so the options are to test projection variants
against the diagnostic until dot reaches 1.0, or to report it upstream -- NRD's README has a
"HOW TO REPORT ISSUES" section asking for a repro in their sample. If it can be fixed properly the
disocclusion threshold should return to NRD's documented 2% and RELAX should close most of the gap
to REBLUR without the brightness cost that 50%+ carries.

## RELAX's surface flicker: scored against the INPUT, not against REBLUR

"RELAX flickers on surfaces while REBLUR looks stable" is real, and the composite hid it: the
composite mixes the medium, the surface half and the raw emissive strobe, and TAA flattens what
survives, so it showed a 2x difference where the underlying buffer is far worse. Measured on the
SURFACE HALF alone, under motion, scored only on the 78.6% of the frame with no medium and no
emitter (`surfflick.py`), instability by spatial scale, x1e-3:

| | s=0 | s=8 | s=32 | s=128 |
|---|---|---|---|---|
| **raw surfaceColor (the input)** | 3448.8 | 396.1 | 135.9 | 62.7 |
| RELAX SH (shipping) | 461.5 | 115.7 | 42.4 | 18.5 |
| RELAX non-SH | 502.1 | 120.8 | 43.3 | 19.9 |
| REBLUR non-SH | 429.9 | 68.0 | 19.3 | 11.0 |
| REBLUR SH | 412.6 | 59.3 | **11.3** | **4.7** |

**RELAX is not adding instability** -- it removes 3.2x of the input's large-scale variation. REBLUR
removes 12x. Both work; one works far better, and the difference is temporal accumulation.

WITHDRAWN: "RELAX is the wrong tool because NVIDIA say it wants RTXDI-clean signals". That was too
convenient. VolumetricReSTIR IS a ReSTIR estimator, and the adapter's own table shows the split's
structural zeros exist ONLY where the medium is -- outside it the surface half has 0.0% holes. So on
exactly the pixels measured above, the input is the RTXDI-shaped signal RELAX is built for. The one
qualification that survives is that the raw input is still unstable at coarse scales (135.9 at s=32),
so it is not as clean as RTXDI's output and some of the difficulty is genuine.

REFUTED against this metric, so do not re-try them:
* SH mode -- RELAX SH 42.4 against non-SH 43.3.
* `diffuseMinLuminanceWeight` 0.5 (164.8, WORSE), `diffusePhiLuminance` 32 (139.2, WORSE),
  `spatialVarianceEstimationHistoryThreshold` and `luminanceEdgeStoppingRelaxation` (no change).
* Input intensity clamping -- see the section on the SH path having no clamp. Even a clamp of 1 moves
  s=32 by 5%.

WHAT DOES MOVE IT is the disocclusion threshold, i.e. temporal accumulation again:

| disocc | s=8 | s=32 | s=128 | shipping image s=32 / s=128 / mean |
|---|---|---|---|---|
| 20 | 195.6 | 111.1 | 79.5 | 18.72 / 7.86 / 0.0874 |
| **35 (now)** | 115.7 | 42.4 | 18.5 | 14.80 / 5.56 / 0.0851 |
| 50 | 88.7 | 27.2 | 14.9 | 11.87 / 4.28 / 0.0795 |
| 100 | 76.0 | 19.9 | 11.8 | 10.46 / 3.48 / 0.0772 |

So the surface flicker traces back to the SAME unresolved reprojection mismatch as everything else --
RELAX rejects history the plane test says is invalid, REBLUR's test is more tolerant, and the ~4.2 m
plane-distance offset that causes it is still unexplained. 50 and 100 close more of the gap but
darken the image 9% and 12%, which is not understood either, so 35 is the default.

## MEASURE FLICKER BY SPATIAL SCALE -- the per-pixel metric misses what people see

The second temporal difference used everywhere in this file is a HIGH-PASS measure: it is dominated
by per-pixel sparkle and cancels smooth change on purpose. The artifact people actually report when
the camera moves -- "the scene changes", whole regions shifting brightness together -- is the
opposite kind, and that metric is blind to it BY CONSTRUCTION. Blur first, then measure. `scale.py`.

Instability at increasing spatial scale, x1e-3, normalised by mean brightness (90-frame orbit, split
+ TAA + emission + mask):

| config | s=0 (per-pixel) | s=8 | s=32 | s=128 | whole-frame |
|---|---|---|---|---|---|
| RELAX | 293.4 | 77.2 | **28.3** | **14.4** | **11.88** |
| REBLUR | 263.6 | 55.4 | **16.0** | **9.2** | **7.70** |
| Ray Reconstruction | **321.5** | 62.1 | 17.7 | 10.1 | 8.43 |

**The ranking INVERTS with scale.** At s=0 RR is worst, which is what every earlier number in this
file measured and why they kept saying RR was the least stable. At s=32 and above RELAX is the clear
outlier -- 76% worse than REBLUR at s=32, 54% worse on whole-frame brightness. Two different
artifacts, and the one that gets reported is the coarse one. Always report both scales.

LOCALISED TO THE SURFACE HALF. Using the split to give each half a different denoiser
(`VR_NRD_VOL_METHOD`), at s=32 on a 30-frame run:

| config | s=32 | whole-frame |
|---|---|---|
| RELAX both halves | 19.13 | 5.91 |
| RELAX surfaces + REBLUR medium | 17.79 (-7%) | 5.50 |
| **REBLUR surfaces + RELAX medium** | **7.58 (-60%)** | 1.85 |
| REBLUR both | 5.72 (-70%) | 1.16 |

So it is the SURFACE branch, not the medium -- swapping only that one accounts for 60% of it.

NOT REACHABLE FROM RELAX'S SETTINGS, swept against this metric rather than the per-pixel one:

| knob | s=32 |
|---|---|
| baseline (atrous 6) | 19.13 |
| `NRD4_ATROUS` 8 | **17.76 (-7%)** |
| antilag fully off | 19.06 (-0.4%) |
| `NRD4_CLAMPSIGMA` 3 | 19.12 |
| `NRD4_FASTACCUM` off | 19.12 |
| `NRD4_SVAR` 8 | 19.14 |
| `NRD4_MINLUMW` 0.3 | 18.80 |
| `NRD4_PHILUM` 8 | 18.98 |
| `NRD4_HISTFIX` 0 | 20.59, and 26% too dark |
| atrous 5 / 4 / 3 | 20.65 / 21.93 / 22.39 -- monotonically WORSE |

Atrous is monotonic 3 -> 8, so 8 is the best RELAX can do and it is worth 7%, not 3.3x.

AND IT IS NOT REBLUR'S STABILIZATION PASS, which was the obvious hypothesis: REBLUR with
`maxStabilizedFrameNum = 0` sits at 5.78 against 5.72 with it on. Unchanged. The difference is that
RELAX's a-trous weights come from a per-frame variance estimate, so when that estimate moves the
filtered result moves with it over the whole footprint, while REBLUR's Poisson-disc radius is driven
by hit distance and accumulation speed, which vary slowly.

THE FIX, therefore, is to run the SURFACE half under REBLUR. The split already allows it and
`VR_NRD_VOL_METHOD` now makes the pairing explicit in either direction.

## THE FLICKER IS THE EMISSIVE BUFFER, and it never touches the denoiser

This is the answer to "why does it flicker", and it is not the denoiser, not aliasing, and not RELAX.

Bucketing the per-pixel second temporal difference by what each pixel IS (`fdiag.py` captures
consecutive frames with guides, `fwhere.py` buckets them), on the composite BEFORE the tonemapper and
TAA:

| category | % of frame | % of flicker energy | per-pixel rate |
|---|---|---|---|
| **emitter present** | **2.55%** | **95.7%** | **37.5x** |
| inside the medium (a > 0.35) | 17.02% | 3.4% | 0.20x |
| flat surface | 80.43% | 0.9% | 0.01x |

and **99% of the worst-flickering pixels are emitters**. After TAA they are still 99.4% of the tail.

The cause is in `FinalShading.cs.slang`: `emissiveColor` is `curColor` only when the reservoir
happened to pick self-emission, else zero. Measured over 8 consecutive frames at emitter cores:

* **76% of pixel-frames are exactly ZERO**
* **98.4% of pixels are on/off** (zero in some frames, non-zero in others)
* temporal std / mean = **2.65**
* the emissive term is **100% of the composite** at those pixels (median share 1.00)

So it strobes, and `VR_NRD_EMISSION=1` adds it RAW -- `ModulateIllumination.emission` is a plain
additive input. That is why every RELAX and REBLUR setting is inert on it: the flicker never passes
through a denoiser at all. It also explains the pop maps (string lights, bulbs), why the medium is
the steadiest region, and why all three denoisers score so similarly.

TAA is what currently handles it, taking emitters from 95.7% of flicker energy down to 14.9%. That
is the whole reason TAA cuts flicker 27% here.

FOUR MITIGATIONS TRIED, ALL MEASURED WORSE OR NEUTRAL (N=30, baseline 0.26185):
* Denoise emission with its own instance, no demodulation, under RELAX -- **+6.6%**, sharpness +21%.
  RELAX's `atrousIterationNum` is documented "[2; 8]", so its spatial pass cannot be switched off and
  the point emitters get smeared back into the bloom the bypass existed to remove. `maxBlurRadius` is
  a REBLUR-only setting, so it does nothing here -- that is why the first attempt looked so bad.
* Same but forcing REBLUR for that branch with pre-pass 0 and maxBlurRadius 0 -- **+5.6%**. Better,
  still worse than doing nothing: NRD's anti-firefly and fast-history clamping exist to suppress
  exactly the spikes that ARE this signal.
* TAA alpha 0.02 + colorBoxSigma 8 (long history, loose clamp) -- total flicker energy UP, emitter
  share only 14.9% -> 12.1%.
* An unclamped reprojected average of the emissive buffer alone (`VR_NRD_EMISTAA`, a second TAA at
  sigma 15) -- **-23% flicker energy BEFORE the composite TAA**, which confirms the diagnosis, but
  **+1.3% after it**: two temporal filters in series with different reprojections fight each other.

Switches kept, default off, as recorded dead ends: `VR_NRD_EMISDN`, `VR_NRD_EMISTAA`.

### "But REBLUR and RR work" -- they do not, and measuring per-category says why

Same bucketing, applied to all three on the FINAL displayed image (RELAX and REBLUR after TAA, RR
after its own resolve, since that is what each configuration actually shows):

| | total flicker energy | emitter share | emitter per-pixel | in-medium per-pixel |
|---|---|---|---|---|
| RELAX + TAA | 31499 | 14.9% | 5.85x | 0.49x |
| REBLUR + TAA | **26813** | 18.0% | 7.05x | **0.22x** |
| Ray Reconstruction | **38422** | 16.0% | 6.27x | 0.38x |

Two corrections fall out, both against things stated earlier in this file:

1. **RR does not "work". It is the WORST of the three on flicker** -- 22% more total flicker energy
   than RELAX, and 99.8% of its worst-flickering pixels are emitters, at a higher per-pixel rate
   (6.27x) than RELAX's. It reads as steadier because it is 2.5x sharper and resolves the background
   crisply; sharpness is being mistaken for stability, per-category this time rather than in the
   frame mean.

2. **Denoising the emission does NOT fix the strobe.** RR takes `accumulated_color` straight into
   DLSSDPass -- it never goes through `add_nrd_split`, so the emission bypass does not apply to it
   and RR denoises emission along with everything else. It still has the worst emitter tail of the
   three. So "route emission through a denoiser" is refuted by RR's own numbers, not just by the two
   NRD attempts above. A signal that is exactly zero in 76% of frames is hard for ANY filter.

3. REBLUR's real advantage is **in the medium**, where it is 2.2x steadier than RELAX (0.22x vs
   0.49x per-pixel), not on emitters -- its emitter share is actually the highest of the three. The
   10% total-flicker gap to RELAX is the medium and the surfaces, not the thing that dominates the
   absolute level.

Which is the strongest argument yet that the fix belongs at the source: three different denoisers,
including a trained one that filters emission directly, all fail to remove it.

CLOSED, for now, BY CONSTRAINT. VolumetricReSTIR's logic is off limits, which rules out the only fix
that works (below). Every downstream option has now been measured and every one is worse than doing
nothing:

| route | result |
|---|---|
| denoise emission under RELAX, no demodulation | +6.6% flicker |
| denoise under REBLUR, pre-pass 0, maxBlurRadius 0 | +5.6% (before the accumulation fix) |
| same, re-tested AFTER the accumulation fix | **+7.9% flicker, hard-jump pixels 9.72% -> 13.03%, sharpness +22%** |
| TAA alpha 0.02 + colorBoxSigma 8 | total flicker energy up |
| separate unclamped TAA on the emissive buffer | -23% before the composite TAA, +1.3% after it |
| DLSS RR, which denoises emission natively | worst emitter tail of the three denoisers |

The re-test matters because the first two verdicts were taken while temporal accumulation was broken,
so they were stale. They are not any more. The +22% sharpness with the blur radius at ZERO is the
tell: NRD's anti-firefly and history clamping are suppressing exactly the spikes that ARE this
signal, so the term comes back altered rather than averaged.

So the current configuration -- emission routed around the denoiser, composite TAA after the
tonemapper -- is the best of the measured options, and TAA is already doing the heavy lifting
(emitter share of flicker energy 95.7% before it, 14.9% after). Do not re-try the denoiser routes
without a reason that is not on this list.

IF the estimator ever opens up, the fix is: emission should
not be a stochastic reservoir choice. Integrated deterministically along the primary ray during the
march -- the same shape of change as `opticalThickness`, which already rides that march -- it would
not strobe at all and would need no filtering, which is also what NVIDIA assumes when they say
emission must not be denoised. Doing that means FinalShading must stop emitting it stochastically or
the contribution is double counted, and the volume + surface + emissive == accumulated_color identity
would need restating. That is the next piece of work here.

## RELAX's flicker is NOT a tuning problem, and here is the proof

Asked to make RELAX as steady as REBLUR and RR. It cannot be done with RELAX's settings, and the
measurement that settles it is one line: **`diffuseMaxAccumulatedFrameNum` 30 -> 1 moves flicker
0.3%.** Thirty frames of temporal accumulation down to one. If accumulation were doing the work that
would be catastrophic; it is nothing.

The reason is not a bug. **VolumetricReSTIR does its own temporal reuse**, so NRD is handed a signal
that is already a multi-frame average and has little left to accumulate. Every temporal knob is
therefore inert by construction. Swept on bistro's orbit, split + emission + mask, N=30, against a
0.35849 baseline with TAA off:

| knob | flicker | note |
|---|---|---|
| `NRD4_MAXACCUM` 30 -> 1 | +0.3% | thirty frames of history to one |
| `NRD4_MAXACCUM` 30 -> 60 | -0.0% | |
| `NRD4_FASTACCUM` 2 -> 6 (NRD default) | -0.0% | the v3.1 carry-over is not the problem |
| `NRD4_FASTACCUM` -> 30 (fast history off) | -0.0% | |
| `NRD4_CLAMPSIGMA` 2 -> 3 | -0.0% | |
| `NRD4_ANTILAG_RESET` 0.5 -> 0 | +0.0% | |
| `NRD4_DISOCC` 0.01 -> 0.05 | +1.5% | worse |
| `NRD4_ATROUS` 6 -> 8 | +0.3% | worse |
| `NRD4_PHILUM` 2 -> 8 | +0.3% | worse |

For scale: raw ReSTIR with NO denoiser is 1.69641 and RELAX is 0.35849, so RELAX is cutting flicker
4.7x. It is working; it is just saturated.

WHERE THE REBLUR GAP COMES FROM, then, is structural rather than tuning: REBLUR has a temporal
stabilization pass (`REBLUR_TemporalStabilization`, a TAA-shaped reproject-clamp-blend) and RELAX has
no equivalent. At N=90 with TAA: RELAX 0.29336, REBLUR 0.26358 (-10.2%), and 44.60% vs 37.82% of
pixels taking a hard jump.

AND NOTE THE PREMISE IS HALF WRONG: **Ray Reconstruction is 9.6% WORSE than RELAX on flicker**
(0.32150, 51.29% hard pixels -- the worst of the four). RR reads as steadier because it is 2.5x
sharper, and crisp reads as solid. Sharpness and stability are being conflated by eye, which is
exactly why both numbers are always reported here.

WHAT DID HELP, both small and both now exposed:
* `NRD4_MINLUMW = 0.3` -- the sweep that had been committed-but-never-run (it silently produced no
  captures). -1.4% flicker at N=30, +0.7% sharpness. Real but marginal.
* `VR_TAA_SIGMA` 1.0 -> 2.0 -- TAA's colour-box clamp. Flicker unchanged, **sharpness +55.5%** at
  N=90, no ghosting visible at frame 62. The current TAA is over-clamping and throwing detail away.
  Not defaulted: `d1` drops 1.9%, which is consistent with mild lag, and one frame cannot rule out
  ghosting. Worth a proper A/B before adopting.

RELAX antilag is now exposed too (`NRD4_ANTILAG_ACC` / `_SPATIAL` / `_TEMPORAL` / `_RESET`), since
NVIDIA's guide says to integrate with it disabled and it had never been reachable. It changes nothing
here, but that is now a measurement rather than an assumption.

TRAP FOUND WHILE DOING THIS: per-instance properties are parsed AFTER the env-override block, so
re-enabling them silently killed `NRD4_MAXACCUM`, `NRD4_PHILUM`, `NRD4_HISTFIX` and `NRD4_PREPASS` on
the split path. A dead debug override is worse than none -- a sweep runs, reports no effect, and the
wrong conclusion gets written down. The affected env vars are now re-applied after the property loop.
The first RELAX sweep in this section was run before that fix and had to be redone.

## How much of this is tuned to bistro's plume?

Asked directly, and worth having a straight answer on record. Everything this session was measured on
ONE scene, ONE medium, ONE camera path, ONE resolution (1280x720), and for the still analyses ONE
frame. Splitting the changes by what they actually rest on:

MECHANISM, not tuning -- these follow from what the quantities MEAN and should transfer:
* Transmittance demodulation of the surface half. `L = T * L_surface` is the compositing identity for
  a participating medium; `T` not following the surface's motion vector is a property of geometry,
  not of this plume.
* Re-modulating by the adapter's exported divisor rather than re-deriving it.
* The confidence handover being the SAME number as the divisor floor.
* Pre-pass 0. Derived from `saturate(hitDist / frustumSize)` saturating whenever hit distance is a
  camera-to-scatter distance, which is true of any primary-distance guide, and already established
  for RELAX by a monotonic sweep.
* Per-instance v4 properties.

TUNED, and the honest risk list:
* `VR_NRD_MINTR = 0.05` -- the divisor floor, i.e. "never amplify by more than 20x". Dimensionless
  (transmittance is [0;1]) so it carries across scenes in units, but the right value depends on how
  noisy the surface estimate is, so it is really a function of spp and medium density. Chosen from a
  4-point sweep on bistro; 0.02 and below were catastrophic (fireflies), 0.05 was the first that
  worked. NOT bracketed from above -- 0.1 and 0.2 were never tried.
* `VR_NRD_VOL_BLUR = 12` px at 720p -- now scaled by render height so the world-space footprint is
  constant, but how far a medium's radiance may legitimately spread is a property of the MEDIUM. A
  thin wide fog would want a larger radius than a dense compact plume. Highest overfitting risk on
  the list.
* `VR_NRD_COVKNEE = 0.2` (pre-existing) -- same character.

UNTESTED REGIMES, where the reasoning may hold but the measurement does not exist:
* A medium that fills the frame (thin fog). Then `T ~ 0.5` everywhere, demodulation is active
  everywhere and the confidence handover never fires -- the opposite balance to bistro's plume, where
  the core is opaque and demodulation floors out over 20% of the frame.
* A small or distant medium, where the plume is a few dozen pixels across and the blur radius is
  comparable to its whole extent.
* An ANIMATED medium. Bistro is a single time step, so only the camera moves; nothing here tests a
  plume moving against a static camera, which is exactly the case velocity-guided reprojection is
  for. The plume scene can animate but has no surfaces to speak of, so it cannot exercise the split.
* Any resolution other than 1280x720.
* Anisotropic phase functions. The Dc SH resolve assumes `g = 0`.

Cheapest checks if this needs to hold elsewhere, in order: run the plume scene with the split on to
get a second medium; re-run the halo sweep at 4K to confirm the resolution scaling behaves; sweep
`VR_NRD_MINTR` upward (0.1, 0.2) to find the top of the working range rather than only the bottom.

## Traps that have already cost time

* **Never pipe a Mogwai run through `Select-Object -First N`.** It closes the pipeline and kills the
  process mid-run; exit -1, nothing written. Documented in `README.md`. **Bash `for` loops have the
  same symptom** — captures land only from inline invocations. Not root-caused, hit three times.
  Always check the output FILES exist rather than trusting an exit code.
* **`libprotoc.dll` and `z.dll` keep vanishing from `bin/<config>/`**, including from the protoc_shim
  build directory itself. Almost certainly antivirus. `restore_runtime_dlls` re-copies them on every
  build, but cannot help if they are removed after the build — restore them before running. An AV
  exclusion on `build/` is the real fix and is a two-minute job.
* **Measure denoisers with the camera MOVING.** Every historical number was taken on a pinned camera,
  which is the one regime where history is never disoccluded. That is how `historyFixFrameNum = 0`
  looked "strictly non-negative" while actually leaving the scene 26% too dark under motion.
* **Correlation is not improvement.** Three plausible mechanisms were built and measured worse:
  volumetric demodulation (-10.7% detail), selection-rate normalisation (turned a 17% shortfall into
  a 58% excess), and "AA is the RR gap" (TAA closed the flicker but at 11x the blur). The mechanism
  being sound says nothing about the effect.

## Switches added, all default off

`VR_NRD_SPLIT`, `VR_NRD_VOLDEMOD`, `VR_NRD_SELNORM`, `VR_NRD_TAA`, `VR_TAA_LDR`, `VR_VOL_NORMAL`,
`NRD4_MINLUMW`, `NRD4_LUMRELAX`, and the `NRD4_R_*` family. Nothing on this list changes the default
path.

Two exceptions, deliberately, both correctness fixes rather than experiments and both confined to the
split path (itself off by default, so the single-denoiser default is unchanged):

* **`VR_NRD_SURFTR` defaults ON** -- transmittance demodulation of the surface half. Off, the plume's
  boundary comes out in hard rectangles. `VR_NRD_SURFTR=0` restores the old behaviour for an A/B, and
  with it off `VR_NRD_SURFCONF` falls back to raw transmittance as before.
* **history confidence is always on in the split** -- sourced from the adapter's `historyConfidence`
  when demodulation is on, else from `mediumTransmittance` under `VR_NRD_SURFCONF`. Without it the
  split path draws the scene through the smoke.

`VR_NRD_MINTR` (default 0.05) is the divisor floor AND the confidence handover point; they are the
same number on purpose. Do not raise it without re-checking the deep-interior number, and do not
lower it at all -- see the firefly measurements above.

## The fix is a BUILD STEP, not an edit in external/nrd-4

`/external/nrd-4/` is gitignored (~10 MB of built binaries, fetched per this pass's README), so an
edit made there is **not in version control** and disappears whenever NRD is re-fetched or rebuilt.
The matrix correction is not optional polish -- without it RELAX rejects every reprojection and holds
0.05 frames of history against a 30-frame cap -- so it is reapplied on every build by
`build_scripts/patch_nrd_matrix_layout.py`, wired as the `patch_nrd_shaders` target that
`deploy_dependencies` depends on. Same pattern as `restore_runtime_dlls`.

The script is idempotent (it looks for the `NRD_RAW_MATRICES` marker), and it **fails loudly** if a
future NRD version renames the shared-constants block rather than skipping silently -- a silent skip
would ship a denoiser whose temporal accumulation does not work, which is the exact failure this whole
investigation was about.

Verified end to end: delete the fix, build, and it comes back; then a full
`deploy_dependencies` build with the shader cache cleared reproduces history 29.80 / 99.1% at cap.

**A verification failure worth carrying forward.** Throughout this investigation I checked the
vendored tree with `git status --porcelain external/`, read the empty output as "pristine", and said
so several times. The path is *ignored*, so that command returns empty no matter what is in there. It
could never have detected a leftover diagnostic patch. When a check is supposed to catch a specific
failure, confirm it can actually see that failure -- `git check-ignore -v <path>` here, or the
byte-difference control used for the shader switches.

## Re-tuning after the fix: what moved and what did not

Every RELAX setting in this project was chosen while the transposed matrices held history at 0.05
frames, i.e. while the spatial filter was doing the work accumulation should have been doing. Re-run
on bistro's authored orbit against the fixed build:

| change | s=32 | s=128 | whole-frame | sharpness | verdict |
|---|---|---|---|---|---|
| shipping at the time | 6.84 | 2.36 | 1.2716 | 119.8 | baseline |
| prepassBlurRadius 30 (NRD stock) | 7.52 | 2.84 | 1.6443 | - | worse, keep 0 |
| diffusePhiLuminance 1.0 | 7.41 | 2.72 | 1.4904 | - | neutral |
| emitters through the denoiser | 8.17 | 3.03 | 1.7470 | - | worse, keep routing round |
| historyFixFrameNum 0 | 6.88 | 2.45 | 1.4318 | 114.9 | worse, keep 3 |
| **enableAntiFirefly false** | **6.69** | **2.30** | **1.2444** | **132.4** | **shipped** |

**Anti-firefly was the one that had inverted.** We set it true against NRD's own RELAX default of
false, on a plume measurement of 1.072e-03 -> 1.059e-03 taken before the matrix fix -- with no
temporal accumulation, a spatial firefly filter was the only thing suppressing fireflies. With
accumulation running it is a net loss, and turning it off is what closes the sharpness gap to REBLUR
(119.8 -> 132.4, overtaking REBLUR's 125.9).

Checked for the artifact it is named after rather than assumed: isolated bright outliers over 90
frames go 50460 -> 54564, an 8% rise on a median-based measure that cannot tell a firefly from real
detail, and at 2x zoom the plume gains internal structure with no visible speckle.

**Scope limit:** plume has NOT been re-measured since the fix, and the original justification was on
plume. It is animated, 1-spp and genuinely firefly-heavy -- the case most likely to still want this.
Re-run plume before treating it as settled. `NRD4_ANTIFIREFLY=1` restores.

**A knob that is not a knob:** `maxBlurRadius` is REBLUR-only. `NRDPass.cpp` maps the property onto
`mReblurSettings` alone, so setting it on a RELAX instance does nothing -- 30, 15 and 8 produced
instability identical to four decimals. RELAX's spatial extent is `atrousIterationNum`, which is still
untested.

### Where the session ends up, bistro's authored orbit

| config | s=32 | s=128 | whole-frame | sharpness |
|---|---|---|---|---|
| RELAX at session start | 19.52 | 8.19 | 5.87 | 86.3 |
| RELAX now | **6.68** | **2.30** | **1.241** | **132.1** |
| REBLUR now | 6.64 | 2.28 | 1.225 | 125.9 |
| DLSS Ray Reconstruction | 7.92 | 2.72 | 1.515 | 62.0 |

2.9x steadier and 1.5x sharper than where it started. REBLUR keeps a ~1% edge on stability; RELAX is
now the sharpest of the three.

### RELAX's tuning is converged; the rest are trades

Full re-sweep against the fixed build, bistro's authored orbit. Shipping row 6.69 / 2.30 / 1.2444 /
132.4 (s=32 / s=128 / whole-frame / sharpness):

| setting | result | verdict |
|---|---|---|
| atrousIterationNum 5 (NRD stock) | 6.78 / 2.32 / 1.2465 / 133.5 | sharper, less stable -- a trade |
| atrousIterationNum 4 | 6.87 / 2.35 / 1.2486 / 134.8 | more of the same trade |
| diffuseMaxFastAccumulatedFrameNum 6 (stock) | 6.69 / 2.31 / 1.2706 / 134.4 | sharper, worse whole-frame |
| maxAccumulatedFrameNum 63 | 6.71 / 2.31 / 1.2561 / 132.0 | worse; 30 is right |
| fastHistoryClampingSigmaScale 3.0 | 6.65 / 2.29 / 1.2483 / 133.5 | +0.6% one axis, -0.3% another |
| fastHistoryClampingSigmaScale 4.0 / 6.0 | 6.65 / 2.30 / 1.2606, 1.2699 | saturated, whole-frame degrading |
| spatialVarianceEstimationHistoryThreshold 3 (stock) | 6.68 / 2.30 / 1.2410 / 132.1 | neutral -- **taken** |

Nothing here is an improvement. Every row trades stability against sharpness, and the clamp's gain is
at the level where taking it would be over-fitting to one scene. The clamp is worth understanding
though: it saturates at 3.0, and past that sharpness keeps rising while whole-frame degrades, which is
the fast history escaping clamping altogether -- the same mechanism as the TAA colorBoxSigma result,
where a tight history box is itself a blur.

`spatialVarianceEstimationHistoryThreshold` went back to NRD's stock 3 on liability grounds rather
than performance: it measured neutral, and an override that deviates from upstream with no recorded
justification is a thing that rots silently. `atrousIterationNum 6` and `fastAccum 2` are also v3.1-era
carryovers, but unlike that one they now have measurements behind them, so they stay.

**Untested still:** plume, on everything above and on the anti-firefly change in particular.

---

## SOLVED: v8's OptiX instability was a dropped ray-origin offset (2026-08-23)

**One line, lost in the 8.0 port of `VolumetricReSTIR/InlineRayTracingHelpers.slang`:**

```hlsl
sd.posW = computeScatterRayOrigin(sd.posW, sd.frontFacing ? sd.faceN : -sd.faceN);
```

4.x applied it in `computeSurfaceShadingInfo`; 8.0 did not. `computeScatterRayOrigin` was left
DEFINED BUT NEVER CALLED -- grepping for a zero-use helper is what found it.

Every shadow ray in this pass is `{ shadingInfo.posW, dir, 0, distance }`, i.e. **tMin = 0**. Without
the offset the ray starts exactly ON the surface it must leave, self-intersects at t~0, visibility
returns 0, and the pixel is left black. The restored line matches 8.0's own idiom in
`Scene/ShadingData.slang:79`, `computeRayOrigin(posW, (frontFacing == viewside) ? faceN : -faceN)`.

### Result, bistro orbit, 300 frames at 1080p, legacy-matched config

|                   | s=32  | plume | surfaces | detail |
|-------------------|-------|-------|----------|--------|
| legacy (target)   | 18.42 | 27.33 | 37.81    | 0.0650 |
| v8 before         | 56.26 | 47.70 | 95.70    | 0.0580 |
| **v8 after**      | **17.37** | **25.70** | **36.66** | **0.0735** |

3.2x better, now slightly ahead of the 4.x fork on every axis AND 13% sharper -- not a
stability-for-sharpness trade. Raw estimator pixels with NO contribution: surfaces 55.90% -> 16.89%
(4.x: 34.38%), frame mean 0.004309 -> 0.004436 (4.x: 0.004467).

### Why every earlier check missed it

It **conserves total energy** -- the surviving pixels carry it -- so frame means, firefly counts and
energy-concentration percentiles all reported "the estimator output is equivalent". Only SPARSITY
changed. And because it strikes surfaces rather than the medium (plume 30.67% vs surfaces 55.90%),
it presented as unstable *volumetrics* while the damage was on bistro's geometry. Every hypothesis
about ReSTIR, motion vectors, guides and the denoiser was chasing a symptom one stage downstream.

### Three retractions this produced

* **"Different OptiX SDK / driver."** Wrong. The Aug-13 legacy binary re-run 10 days later is
  BIT-IDENTICAL (md5-equal frames, 0.000% pixels differing), so the driver never moved; and
  `legacy/Source/Externals/.packman/OptiX_9.0.0` is a stale FOLDER NAME whose `optix.h` reads
  `OPTIX_VERSION 90100` and `diff -rq`s clean against v8's copy. Both builds were always on 9.1.
* **"Legacy cannot render bistro's volume."** Wrong, and it blocked this comparison for weeks. The
  failure is `Can't find file 'Bistro_5_1/BistroExterior.fbx'` -- a Falcor 4 MEDIA SEARCH PATH
  problem. Absolute paths fix it (`legacy/Scripts/_probe_optix_today.py`, `_probe_raw_today.py`).
* **"The raw estimator output is equivalent."** Rested on `legacy/outputs/Bistro_Raw_Video`, an
  ABORTED 4-frame run whose frame 2 has 3x its neighbours' mean. Superseded by `Bistro_Raw_Today`.

### Traps worth keeping

* **Shaders are served from `build/.../bin/Release/shaders/`, not from `Source/`.** Editing the
  source and re-running measures the OLD shader. The tell was the classic one: "after" identical to
  "before" to four decimals. Deploy with `cmake --build ... --target VolumetricReSTIR`.
* **Every number recorded in this file before 2026-08-23 was measured on the broken shadow rays**
  and is superseded. That includes the RELAX/REBLUR/RR comparisons and the NRD tuning.

### Shipped configuration (mvec + TAA), after the fix

|            | s=32  | plume | surfaces | detail |
|------------|-------|-------|----------|--------|
| guides OFF | 12.22 | 20.60 | 30.07    | 0.0639 |
| guides ON  | 11.65 | 19.94 | 29.22    | 0.0640 |

30.05 -> 12.22 for the shipped path, i.e. the fix is worth 2.5x there too. Note what it does to the
GUIDES result: they were recorded as "19% better for 3.6% of detail" (30.05 -> 24.33) and are really
4.7% better at no detail cost. They had been compensating for an estimator leaving 56% of surface
pixels black. **A denoiser aid measured against a broken input overstates itself** -- the same
caution applies to every other tuning number in this file.

Plume scene re-checked after the fix: renders correctly (frame means 0.19-0.20, 97-100% non-black).

### The denoiser ranking, re-measured on the fixed build

Every earlier comparison in this file was made against an estimator throwing away half its surface
pixels. Re-run at matched settings (SH + split + NRD TAA + emission + volmask, gradient volume
normals, LDR TAA on), bistro, 300 frames at 1080p:

|                          | s=32  | plume | surfaces | detail |
|--------------------------|-------|-------|----------|--------|
| DLSS Ray Reconstruction  | 9.32  | 15.84 | 26.93    | 0.0638 |
| RELAX-SH                 | 9.34  | 14.06 | 27.24    | 0.0651 |
| REBLUR-SH                | 9.35  | 13.90 | 26.94    | 0.0645 |
| raw ReSTIR (+ TAA)       | 9.64  | 15.66 | 28.06    | 0.0992 |
| OptiX (+ volume guides)  | 11.65 | 19.94 | 29.22    | 0.0640 |

**The fix collapsed the field.** RR / RELAX / REBLUR now sit within 0.3% of each other -- a three-way
tie where the old numbers had RELAX at 10.74 against OptiX's 30.05, a ~3x spread. Most of what used
to read as denoiser quality was each denoiser coping differently with a broken input. For the
project's actual question -- denoising strength vs additional sampling under fixed compute -- that
is the result: on a CORRECT input, the choice among the strong denoisers buys very little here.

Two cautions on reading that table:

* **sigma=32 looks saturated.** Everything lands near 9.3, which reads as a floor rather than genuine
  parity. The plume column (sigma=16) separates them: REBLUR 13.90 and RELAX 14.06 lead, RR 15.84 and
  raw 15.66 are mid, OptiX 19.94 trails. Prefer that column for a real ranking.
* **The raw row is a FLOOR, not a contender.** `VR_TAA_LDR=1` applies TAA to the no-denoiser path, so
  it is raw + TAA; and the metric blurs at sigma before differencing, so the pixel-level noise that
  dominates raw is removed before it is ever measured. Its 0.0992 "detail" is noise energy --
  Laplacian variance cannot tell noise from detail. Same trap class as "ghosting is temporally smooth
  so it lowers the score while looking wrong".

### A3 answered: density gradient vs the camera-facing stand-in

The plan left this open ("the density gradient may lose to the camera-facing stand-in -- that is a
result worth reporting"). Measured on RELAX-SH, bistro orbit, 300 frames at 1080p, everything else
matched:

|                        | s=32 | plume | surfaces | plume detail |
|------------------------|------|-------|----------|--------------|
| camera-facing stand-in | 9.32 | 14.00 | 27.23    | 0.0505       |
| density gradient       | 9.34 | 14.06 | 27.24    | 0.0520       |

**+3% plume detail for -0.4% stability -- close to a wash.** The gradient does not clearly win, so
the original objection to it was not wrong. The knob IS live (19-36% of pixels differ frame to
frame, max delta 173/255), so this is a real negative-ish result, not an unwired switch.

Default moved to `gradient` (`VR_VOL_NORMAL`), because every number recorded in this file was
measured that way -- the `.vscode` `Look:` tasks all set it -- and a default disagreeing with every
published number is the worse inconsistency. Detail inside the medium is also the axis this project
is trying to protect.

### The OptiX normal guide is inert

`VR_OPTIX_GUIDES` was described as wiring volume-aware albedo AND normal guides. Only the albedo
half does anything on that path. Traced end to end:

* estimator `mediumNormal`, Camera vs Gradient: **20.6%** of pixels differ
* `DLSSDGuides.normals`, same A/B: **20.1%** differ -- so the volume normal reaches the guides
* OptiX denoised output: **byte-identical**, 0.000% of pixels differing

So OptiX's 12.22 -> 11.65 comes from the albedo guide alone, and `VR_VOL_NORMAL` is a no-op there.
The guides pass is not at fault: `mBlendNormal`, `mAlphaScale` and `blendMedium` are all live and
permissive by default. Unresolved whether OptiX's HDR/TEMPORAL model simply weights the normal guide
at ~0 here, or whether `guideNormal` is not reaching `optixDenoiserCreate` -- worth a look if the
normal guide is ever wanted on that path.

Also seen: 0.003% NaN/Inf pixels in `DLSSDGuides.normals`, in BOTH modes and only outside the plume,
so they originate in the G-buffer's `guideNormalW`, not in the gradient code. Small, but it is
feeding a denoiser guide.

### Still open

* The fix OVERSHOOTS: v8 now has fewer dead surface pixels than 4.x (16.89% vs 34.38%). Suspect the
  other half of the offset pair -- 4.x's `sampleTriangle` also offset the LIGHT position before
  computing the light vector, 8.0 removed it, and the fork code re-applies it only to the shadow ray,
  leaving `ls.dir`/`ls.distance` inconsistent with `ls.rayDir`/`ls.rayDistance`. It measures better,
  so it is not urgent, but it is not parity.
* Shadow rays never alpha-test: `FindSurfaceHit`/`FindIfOccluded` commit every non-opaque candidate
  (`TODO(surface-scene): alpha test via gScene.materials`), so alpha-cut foliage occludes as solid.

---

## Superseded: the investigation that led there (kept for the ruled-out list)

## Why v8's OptiX looks less stable than the falcor4-legacy OptiX video (2026-08-23)

The question was whether some ReSTIR or volumetric change made the medium unstable on the OptiX
path. It did not. **The estimator is not the cause, and the difference is not in this repository.**

### Ruled out, by direct comparison against `legacy/`

* **The ReSTIR algorithm.** `VolumetricReSTIRParams` defaults diff to zero differing values across
  every shared field. RNG seeds are character-identical (`SampleGenerator(DTid.xy, gNumTotalRounds *
  gFrameCount + gRoundOffset)`), `mFrameCount++` advances per execute in both, and `TemporalReuse.cs
  .slang` diffs to Falcor-8 renames plus two `IsWithinRange` bounds guards. Emissive sampler is
  `Power` in both; `mUseAnalyticLights` false in both; `emissiveIntensityMultiplier` 1 in both.
* **`mTemporalReuseMThreshold`.** Looks like a difference -- the legacy script passes 10.0 against a
  C++ default of 4.0 -- but `vr_graph.load_bistro` sets 10.0 too. Both builds run 10.0.
* **The estimator's OUTPUT.** Raw frames are equivalent: relative high-frequency energy ratio
  v8/legacy 0.92, 0.91, 1.15 (the 1.94 outlier is legacy's own frame 2, whose mean is 3x its
  neighbours -- that 4-frame raw set is an aborted run, do not lean on it). Frame-mean radiance,
  and the share of total energy in the top 0.01/0.1/1% of pixels, all match within a few percent.
* **The capture configuration.** v8 reconfigured to the legacy script exactly (colour only -> HDR
  model, no TAA, Linear+autoExposure, no warm-up) still measures 56.26 against legacy's 18.42.
* **Scene animation.** legacy froze the scene (`t.pause()` + `m.scene.animated = False`); v8's
  `pin_clock` lets it run. Adding `VR_FREEZE_ANIM=1` moves the score 56.26 -> 55.84. Not it.
* **Camera path.** Phase correlation on consecutive frames: 3.32 px/frame legacy, 3.10 v8-matched,
  3.36 v8-shipped. The orbits are the same speed.

### What the videos' apparent difference IS mostly made of

Configuration, and it is large. TAA alone accounts for 61.01 -> 30.05 at sigma=32. Legacy's
auto-exposure renormalises brightness every frame, which is exactly what the instability metric
measures, so it suppresses the score without the renderer being steadier (`VR_TONEMAP_AUTOEXP`).

### The residual, and where it lives

Given equivalent raw input, the two builds' OptiX output differs by a **stable 2.0x in surface-region
median** (legacy 0.000113-0.000116, v8 0.000056-0.000057, every frame) while the *means* match --
so it is not a global scale, it is the dim pixels specifically. v8 also retains LESS detail
(plume 0.0362 vs 0.0448, surfaces 0.0611 vs 0.0707). Blurrier *and* less stable at once is not a
tuning trade-off.

**RETRACTED: "it is a different denoiser / different OptiX SDK".** That was wrong, and testing it
killed it three ways:

* **The legacy build runs today and reproduces BIT-IDENTICALLY.** Same Aug-13 binary, same 300-frame
  orbit, run 10 days later: md5-identical PNGs, 0.000% of pixels differing, and all four metrics
  equal to the decimal (18.42 / 27.33 / 37.81 / 0.0650). The renderer is deterministic and **the
  driver has not changed**, so the driver cannot be the variable.
* **Both builds use the SAME OptiX SDK.** `legacy/Source/Externals/.packman/OptiX_9.0.0` is a stale
  FOLDER NAME: its `optix.h` says `OPTIX_VERSION 90100`, and `diff -rq` against v8's
  `external/packman/optix/include` reports no differences at all. Headers dated 2025-11-19, months
  before the Aug-13 build. Same SDK, same driver, same model.
* **The earlier "legacy cannot render bistro's volume" was also wrong** -- and it is what blocked
  this test for weeks. The failure is `Can't find file 'Bistro_5_1/BistroExterior.fbx'`: a Falcor 4
  MEDIA SEARCH PATH problem, not GVDB, not CUDA, not the bake. Absolute paths in the script fix it
  outright (`legacy/Scripts/_probe_optix_today.py`). Legacy renders bistro fine.

So the denoiser, its model, the driver and the SDK are all held fixed, and the gap remains. **The
difference is in v8's own code.** Since the OptiX denoiser is deterministic and identical, output
that differs means INPUT that differs -- so the estimator comparison has to be redone properly. The
old `legacy/outputs/Bistro_Raw_Video` is an ABORTED 4-frame run whose frame 2 has 3x its neighbours'
mean and a max of 6.8; every "the raw is equivalent" claim above rests on it and is not trustworthy.
Superseded by the 300-frame `Bistro_Raw_Today` capture.

### Two changes that came out of this

* **`VR_OPTIX_GUIDES`, now ON by default.** OptiX accepts albedo/normal guides and this graph had
  never wired them (colour only, as legacy did). Feeding it the volume-aware DLSSDGuides:
  sigma=32 30.05 -> 24.33, sigma=128 18.61 -> 13.36, whole-frame 16.39 -> 11.30, for 3.6% of detail.
* **`VR_OPTIX_VOLMV`, measured and left OFF.** The G-buffer's motion vectors are rasterized, so at a
  plume pixel they describe the wall behind the smoke, while the estimator's are computed at
  `expectedT` inside the medium. Physically the right input, and on this orbit it does nothing:
  30.05 -> 30.08, plume 31.45 -> 31.47. The edge is live (41-44% of pixels differ, max delta 105),
  so this is a real negative, not an unwired knob.


---

## Falcor 8 vs the 4.x fork: frame cost (2026-08-23)

Raw ReSTIR estimator only (no denoiser, no TAA; identical tonemapper both sides), bistro orbit,
300 frames at 1080p, 3 runs each, alternating builds with a process kill between.

|                                   | mean ms | gap    |
|-----------------------------------|---------|--------|
| Falcor 4 fork                     | 102.47  | --     |
| v8, as first measured             | 121.74  | +19.27 |
| v8, animation frozen to match     | 118.39  | +15.91 |
| **v8, atlas compression restored**| **116.4** | **+13.9** |

Run-to-run spread is 0.5% (v8) and 3.2% (legacy), so the gap is far outside noise.

### Fix 1: the comparison was unfair (3.4 ms)

The fork's scripts set `m.scene.animated = False`; `vr_graph.load_scene` only freezes under
`VR_FREEZE_ANIM`. So v8 was re-updating the light collection every frame and legacy was not.
The profiler shows it exactly: `EmissivePowerSampler::update` **6.03 ms -> 0.00 ms** when frozen.
Any cross-build timing MUST set `VR_FREEZE_ANIM=1`.

### Fix 2: the port dropped the GVDB atlas compression (2.6 ms, and a real bug)

`SceneGVDB.cpp` allocated every density atlas as `R32Float` -- 4 bytes/voxel against the fork's
0.5 (BC4) or 1 (R8Unorm) -- and pinned `densityCompressScaleFactor` to 1.0 while the shader's
`getValueAtlasCoord()` still multiplied by it. Its own comment admitted the omission:
"the fork's optional BC4 path (ATLAS_COMPRESSION==2, via BCHelper) is omitted".

Restored as R8Unorm (the fork's ATLAS_COMPRESSION==1 arrangement) on both the VBX and the BAKED
loader. **The baked one is the one that matters** -- bistro loads `smoke-plume-2.bin`, so patching
only the VBX path produced byte-identical output and unchanged timing, the classic "knob isn't
wired" result. Costs image fidelity: mean |delta| 9.19/255, correlation 0.94, plume median
0.2627 -> 0.2601. The fork accepts more loss than this (BC4), so it moves toward parity, not away.

### The remaining ~13.9 ms is NOT in this repository

Volume-only (`mUseSurfaceScene=False`, which also links no type conformances in either build):
legacy 21.47 vs v8 32.09 -- still +10.6 ms with identical everything. Verified identical:

* `Scene/GVDB/gvdb.slang` -- the traversal inner loop -- **byte-identical**
* reservoir count and size (2,073,600 x 32 B), samplers (filter/border/addressing), `tStep`
  formula, every sampling/tracking/mip parameter, `SURFACE_SCENE` gating, compiler flags, FP mode,
  debug-info settings

Hypotheses tested and killed, each with a number rather than an argument:

* **MaterialSystem `evalEmissive`** -- stubbed out entirely in the build-copy shader: saved 1.8 ms.
* **Type conformances** -- refuted by construction: `createSceneComputePass` is used only when
  `mUseSurfaceScene`, so the volume-only path never links them, and it is still +67% slower.
* **Shader model** -- the fork pins 6_5, the port takes the device default 6_7. Pinning 6_5
  measured SLOWER (116.55 vs 115.80). Reverted.
* **Light-sample scaling** -- invalid: `mInitialLightSamples` is documented "only 1 or 0" in both.
* **Env-map isolation** -- unusable: `EnvMap.createFromFile` needs an active scene builder in 8.0.
* **`noemissive` isolation** -- invalid: bistro is lit ONLY by emissive geometry, so it renders
  black (p90 = 0.0000, 1.8% lit) and times two empty frames against each other.

### Compiler-option space: exhausted, every lever tested

Every setting Falcor exposes that could affect codegen was measured on the full config
(3 runs each, frozen scene, against the 116.4 ms baseline):

| lever                                    | result                       |
|------------------------------------------|------------------------------|
| `DisableShortCircuit` removed (Slang's new short-circuit `&&`/`||`) | **120.79 -- SLOWER** |
| `Optimization = SLANG_OPTIMIZATION_LEVEL_MAXIMAL`                   | **117.06 -- SLOWER** |
| `shaderModel = SM6_5` (matching the fork's explicit pin)            | **116.55 -- SLOWER** |
| `GenerateDebugInfo`, FP mode, matrix layout                         | already identical    |

All reverted. This is a useful negative: the difference is not in anything Falcor or this project
*configures*, it is inside the Slang -> DXIL translation itself. Note the short-circuit result is
counter-intuitive and worth remembering -- forcing both operands to evaluate is FASTER here, because
branch divergence costs more than the redundant work in these loops.

The residual is uniform -- v8's Spatial Reuse is 53.1% of its frame, legacy's 53.0% of its own --
which is the signature of codegen, not a hotspot. The last known data difference is BC4 vs R8, worth
~0.6 ms by extrapolation (R32->R8 saved 3 bytes/voxel for 3.86 ms), and `BCHelper` exists only in a
nested vendored copy, not in the active tree. **Closing the rest means Falcor engine work** --
comparing generated DXIL and register allocation between Slang versions -- not Volumetric ReSTIR work.

### Also fixed while looking: a dangling `if` left the scene unbound

All four passes had this:

```cpp
if (mParams.mUseSurfaceScene)
if (mParams.mUseSurfaceScene) mpScene->bindShaderDataForRaytracing(...); else mpScene->bindShaderData(...);
```

The `else` binds to the INNER `if`, so with `mUseSurfaceScene == false` BOTH branches are skipped and
`gScene` is never bound for TraceRays, Temporal Reuse, Spatial Reuse or Final Shading. Volume-only
scenes ran on whatever binding persisted from `setScene`. Fixed in all four. **No timing effect**
(full 116.32 before and after, volume-only 32.29 vs 32.09), so the earlier `nosurface` measurements
still stand -- but they were taken through that path, which is worth knowing.

### Compiler and toolchain: every lever eliminated

| lever                                   | result                                   |
|-----------------------------------------|------------------------------------------|
| DXC 1.5 (the fork's) vs 1.7 (the port's) | **no change** -- 116.65 vs 116.4         |
| Slang `Optimization = MAXIMAL`           | slower -- 117.06                         |
| Slang short-circuit `&&`/`||` restored   | slower -- 120.79                         |
| `shaderModel = SM6_5` (fork pins this)   | slower -- 116.55                         |
| `[loop]` on the GVDB traversal loops     | no change, image byte-identical          |

The DXC swap was verified live: hiding `dxcompiler.dll` makes Mogwai fail to start, so it is
genuinely the compiler in use.

### Control: the gap is not measurement drift

Legacy re-measured at the END of the session: **100.96 ms** (101.24 / 99.77 / 101.89) against 102.47
hours earlier -- stable, slightly faster if anything. The machine did not drift; the gap is real.

### Where it actually is

With the shader source byte-identical AND the DXIL compiler identical, the only remaining variable is
the **Slang version**, which generates the HLSL that DXC consumes. v8's dumped DXIL for the largest
pass is ~45,000 instructions with 186 alloca sites -- real register pressure -- but there is no
legacy baseline to compare it against: enabling `DumpIntermediates` in the fork needs its
VolumetricReSTIR plugin rebuilt, and a standalone build fails with 111 unresolved Falcor symbols
(its Falcor.lib will not link against the v143 toolset the way the small OptixDenoiserRecent plugin
did). Swapping Slang itself is not viable -- Falcor 8 uses the `CompilerOptionEntry` API that the
fork's Slang predates.

**Final: legacy 100.96 ms, v8 116.3 ms, +15.4 ms (+15%). 6 ms of the original 19.27 closed.**
The remainder is Falcor 8's Slang codegen and is not reachable from this project's code.

---

## DLSS 310.9.1: RR2 measured against the previous RR, and a NaN guide bug (2026-09-18)

SDK 310.9.1 is vendored (`external/dlss-310.9.1`) and linked; 310.7.0 stays selectable per pass with
`sdkVariant=Previous310_7` (`VR_SDK`). 310.9.1 adds **RR2** (RR preset F, its new default). Full
tables in `Source/RenderPasses/DLSSPass/README.md`, section "RR2 ... vs the previous RR".

|                           | s=32  | plume | surfaces | detail | RR GPU  | plume relMSE | bistro median err |
|---------------------------|-------|-------|----------|--------|---------|--------------|-------------------|
| previous RR (310.7.0, E)  | **8.97** | **14.55** | **26.65** | 0.0628 | 7.79 ms | **1.69e-3** | **0.0184** |
| RR2 (310.9.1, F)          | 9.29  | 15.27 | 27.33    | 0.0672 | **6.84 ms** | 2.05e-3 | 0.0217 |

A speed/sharpness trade, not a quality upgrade: RR2 is 12% cheaper and resolves more structure in the
smoke, but is 3-5% less stable, 2-21% less accurate per pixel (by scene and metric), and dims the
brightest highlights.
Preset E stays the default. Controls are all exact (byte-identical): the SDK upgrade itself changes
nothing -- 310.9.1's E is bit-identical to 310.7.0's -- and repeat RR runs are deterministic with the
clock pinned, so the noise floor for these A/Bs is 0.

**Bug: `DLSSDGuides` fed RR NaN normals on every pixel with no geometry.** `normalize(lerp(0, n, 0))`.
0.003% of bistro -- the "NaN/Inf in DLSSDGuides.normals" noted above in the OptiX section, which
come from this normalize and not from the G-buffer's guideNormalW as guessed there -- but 79% of the
plume scene. The 310.7.0 model's output is bit-identical with NaN or zero normals; RR2's
changes on 99.98% of pixels, and it had measured 2.7x worse than E on the plume because of it. Fixed
with NVIDIA's documented sky guides (`skyDefaults`, on; `VR_RR_SKY=0` reproduces every earlier number
bit for bit). On the bistro orbit the fix is 0.5/255 mean change, so the rankings above stand.

Also: `compare_denoisers_plume.py` never set the camera depth range (far plane 0.35 -- the load_plume
trap), and `ImageCompare` clamps to [0,1], so the README's "HDR MSE" table is LDR-range. And Falcor's
profiler IS reachable from scripts (`m.profiler`); `capture_orbit.py VR_PASS_TIMES=1` uses it.

### The halo around the smoke in motion (2026-09-18)

RR's motion vectors came from GBufferRaster, which has no smoke: at a plume pixel RR was told the pixel
moves like the wall behind it, and under the orbit it smeared the smoke's history along with that wall
-- a haze around the silhouette while moving, gone when the camera stops. `vr_graph` now hands RR the
estimator's volume-aware mvec by default (`VR_RR_VOLMV`, the same source TAA_LDR already used). 960x540
orbit: plume instability 16.83 -> 15.51 (E), 17.74 -> 16.50 (RR2); surfaces and detail improve too.
Every RR number above this entry used the G-buffer mvec; `VR_RR_VOLMV=0` reproduces them.

Also fixed on the way: resizing a live window garbled RR (the estimator's per-pixel buffers kept their
startup size -- its resize check compared the output texture with the render size, which always match
-- and the G-buffer/guides were pinned while the estimator followed the window). Orbit captures are
byte-identical before and after both fixes, since they never resize.

### The halo, second cause: the ground was given the smoke's motion (2026-09-19)

What remained after the switch to volume mvec was a veil ~50 px wide lying over the GROUND beside the
silhouette while the camera moves -- both RR versions, gone within ~1 s of stopping, absent from the raw
input, unchanged by volume depth or TAA off. GenerateFeatures takes the medium's expected scattering
depth for depth/mvec wherever the primary ray meets ANY medium, so the plume's faint outer fringe
(mid-orbit: 28k pixels, 11k below 0.1% coverage) carried the smoke's motion, 6.9 px/frame away from the
ground those pixels show, and RR reprojected that ground as smoke.

Fix, guide-only: new estimator property `mGuideMediumMinShare` -- depth/mvec follow the medium only where
it supplies at least that share of the pixel's LIGHT, estimated as a*Lm / (a*Lm + T*Ls) from the pixel's
own coverage/transmittance and the neighbourhood's medium light per unit coverage and surface light per
unit transmittance. Those come from a new pass, GuideLightStats.cs.slang, run after final shading: a
running average of (medium light, coverage, surface light, transmittance) using final shading's own
volume/surface classification, read through its mips next frame. The estimator never reads it:
accumulated_color and mediumAlpha byte-identical with the rule on and off over 60 frames of motion.
`vr_graph` sets 5% when RR takes the estimator's mvec (`VR_RR_MV_MIN_SHARE`, 0 restores); the estimator
default 0 keeps NRD's volume half as it was.

How it got there: a coverage threshold first (0.02 best on bistro; 0.5 removes the veil but cuts the
smoke's soft edge off in motion). I explained 0.02 with "the lit smoke outshines the night ground ~50x"
-- inferred, and refuted by the estimator's light split (~2x per unit coverage; the smoke's light
overtakes the ground's only at 10-30% coverage). A coverage threshold does not transfer: across bistro,
the plume under a night env, the plume under a daylight env (VR_PLUME_ENV=lakeside_8k.hdr) and the
paper's emissive explosion (VR_SCENE=explosion), fringe error (stop-and-go, E, m_halo_alpha.py):
bistro 6.34 -> 5.16 at coverage 2% vs 5.09 at light share 5%; night plume 2.91 -> 2.96 (worse than
nothing) vs 2.89; daylight plume 2.87 -> 2.75 vs 2.72; explosion 4.78 -> 4.56 vs 4.49. 5% share is the
only setting that helps or is neutral everywhere (10%/20% win on daylight, lose on the night plume).
Bistro orbit instability E 9.47 -> 9.43, RR2 9.82 -> 9.69; the central plume columns E 15.50 -> 15.77.
`VR_RR_MV_SHARE_STATS=0` reproduces the coverage rule byte for byte. NOT covered: in NRD mode the Look
script's TAA_LDR still reads the estimator mvec under the old rule.

Found on the way to the explosion test: emissive volumes rendered as plain smoke -- the baked loader set
the emission flag but never built the blackbody LUT, and the LUT file was missing from data/. Fixed
(data/LUT from legacy/); non-emissive captures byte-identical after the fix. The paper's temperatureScale
750 still gives exactly zero emission on this bake (LeScale 1 and 100 identical), so the scene uses 7500;
skylight-dusk.exr crashes setEnvMap, so it uses satara_night_8k.hdr.

Retracted (my measurement error): "a dark band 1-12 px outside the smoke, in the raw input even without
temporal reuse". The stops occupy frames 74..224, 299..449, 524..674 (schedule index == file index); that
metric took 75..225 etc., so its "settled" frame was the first one after the camera moved on and the mask
no longer fit. With the right frames there is no band without temporal reuse. `outputs/m_halo_band.py`
now asserts the indices.

Retracted too (and this retraction is itself wrong for the medium -- see "The moving dim rim is ReSTIR's
temporal reuse" below): "the estimator's temporal reuse loses energy while the camera moves" (-2/255 across the
frame, -9 at the smoke's edge in the TONE-MAPPED stop-and-go frames). Checked in HDR instead: stop 3 of
the stop-and-go path, plain ReSTIR (no denoiser, no TAA), 8 seeds (VR_RECORD_WARM 60..67 shifts the
seeds, not the poses), true light moving / stopped:
    plain ground 0.998 +- 0.003    outer fringe (<1%) 1.015 +- 0.048    smoke edge (30-90%) 1.045 +- 0.076
    fringe 1-10% 0.878 +- 0.037    deep smoke 0.985 +- 0.009
while the per-pixel noise is 1.9x (ground) to 3.9x (smoke edge) higher while moving. So the edge does not
get darker; it gets NOISIER -- temporal reuse finds less usable history at a moving silhouette -- and the
tone curve, concave, turns extra variance into a lower average on screen (the same data reproduces the
-9.3/255). The "lost energy, not clipped noise" argument (near-black pixels doubled, bright LDR tail
unchanged) was wrong: fireflies saturate at 255, so an LDR tail cannot show the energy they carry. A real
loss remains only in the thin 1-10% coverage band (-12%, a ring a few pixels wide, invisible under the
noise). Plain ReSTIR shows no halo either way. The measurements above that used the same LDR metric
(history cap -6.4 -> -1.8, MIS off, spatial off) mostly measure noise. Also refuted, and removed:
rejecting temporal/spatial neighbours whose primary-ray transmittance differs (band -6.9/-7.5 vs -6.4).

Also fixed: VolumetricReSTIR::setProperties dereferenced the scene unconditionally, so setting a property
while a graph is being built (before the scene is bound) crashed without a message, and a runtime set on
bistro would have crashed on its missing environment map.

### RR's smoke edge is dimmer while the camera moves -- RR, not ReSTIR (2026-09-19)

SUPERSEDED: it is ReSTIR -- its temporal reuse loses thin medium at a moving silhouette. See "The moving
dim rim is ReSTIR's temporal reuse, not RR" below; the first bullet here measured the noisy total.

After the veil fix, RR's smoke edge still reads ~6/255 darker while moving (typical edge pixel -13.5%),
recovering over seconds after the camera stops. Measured in HDR with 8 seeds at stop 3 (VR_RECORD_WARM
60..67; outputs of each stage captured):
  * RR's INPUT at the edge carries the same average light moving and stopped, and the same typical noise
    (0.70x vs 0.73x of the true light); only its rare bright samples get rarer and brighter while moving
    (99.9th percentile 8x -> 11.6x the mean).
  * RR's OUTPUT at the moving edge: typical pixel darker, a few brighter blotches (HDR mean even +26%,
    median -13.5%) -- visibly, the thin, softly glowing rim of the smoke is missing while moving.
  * Not the depth/mvec mismatch: VR_RR_VOLDEPTH=1 changes nothing (-6.64 vs -6.69/255).
  * Not input noise as such: stopped, a far noisier input (ReSTIR temporal reuse off) leaves RR's edge
    unchanged (83.4 vs 83.8/255).
  * With ReSTIR temporal reuse off the moving darkening drops to -2.3/255: about a third is RR's own
    behaviour while moving, two thirds come with ReSTIR's temporal reuse at a moving silhouette (the
    lumpier, and temporally correlated, edge samples).
So the thin glow's light arrives in rare bright samples that RR can only average out over a stable
history; while the view changes it cannot, and draws the edge harder and dimmer. TAA adds nothing
(-6.07 after TAA). Not fixed: RR is a black box; reducing it would mean changing ReSTIR's temporal reuse
at the silhouette or feeding RR a layer guide, both untested.

### Two-layer RR (VR_RR_LAYERS=1): the veil gone by construction, the moving rim not (2026-09-19)

The smoke and the surfaces denoised by SEPARATE RR instances (vr_graph add_rr_layers; as in Hofmann et
al. 2023 and this project's NRD split): surface layer = surfaceColor / T (DLSSDGuides layer=Surface,
T floored at 0.05) with the G-buffer's guides, depth and mvec; medium layer = volumeColor with the
medium's guides (DLSSDGuides layer=Medium: albedo = single-scatter albedo x coverage, normal =
mediumNormal) and the estimator's depth/mvec with mGuideMediumMinShare = 0; composite T*surface +
medium via ModulateIllumination. Needed NGXWrapper to hold one RR feature PER PASS in the shared NGX
session (a single shared handle made two DLSSDPass instances recreate each other's feature). The
single-RR path stays byte-identical (750/750 stop-and-go frames).

Stop 3, 8 seeds, HDR, previous RR (E); output / true light:
    region                 one RR moving|stopped    two-layer moving|stopped
    ground beside smoke        0.77 | 0.93              0.73 | 0.97
    smoke edge 30-90%       (blotchy) | 0.81            0.71 | 0.90
    deep smoke                 1.00 | 1.01              1.00 | 0.99
(Not confirmed against a proper truth -- see the dim-rim entry below.) Stopped, the two-layer image is the
more accurate one -- edge 0.90 vs 0.81, and its colour (blue 0.82 vs
0.64: one RR loses the lamps' pink/blue at the edge). No veil, by construction. But the thin rim still
dims while moving (typical edge pixel 0.79 of the stopped value; on screen -9.5 vs one RR's -6.7/255,
because the stopped image is brighter). A plain (not coverage-scaled) medium albedo changes nothing.
So the moving dim rim is not a motion-vector problem: with its own exact history RR still accumulates
less while things move, and the rim's light arrives in sparse samples. Cost at 960x540: 44.3 vs 42.1 ms
per frame (second RR 2.0 ms). Off by default. The split makes the next step possible -- a
motion-compensated pre-accumulation of the medium layer (its motion is exact) before RR.

### The moving dim rim is ReSTIR's temporal reuse, not RR (2026-09-19)

Supersedes the two entries above on this point. The smoke's thin rim is dimmer while the camera moves
because the ESTIMATOR loses the medium's light there; RR (one or two instances) and the medium
pre-accumulation only pass it on. Measured on the estimator's split -- volumeColor, the medium's own light:
exact, and far less noisy than the total, which is dominated by the lamps' fireflies -- at stop 3 of the
stop-and-go path, 8 seeds, against the true light at that pose (256 frames with temporal reuse off,
averaged: +-2.3% thin, +-1.1% edge), with the scene animation frozen (VR_FREEZE_ANIM=1, see below):

    medium light / true       moving    still
    thin smoke (1-30%)         0.60      0.99
    smoke edge (30-90%)        0.80      1.01
    deep smoke                 0.99      1.00
    temporal reuse off: the same moving and still (thin 1.09 +- 0.12, edge 1.06 +- 0.03 moving/still).

Cause: TemporalReuse picks last frame's pixel ("reprojection point") from the CANONICAL sample's own depth
when that sample scattered in the medium (else the surface with probability T, or a density-drawn point).
The Talbot weights assume the temporal neighbour does not depend on the sample; here the canonical sample's
weight is computed against a neighbour chosen for it, the neighbour's samples against the neighbours chosen
for the other canonical samples, and the two no longer sum to one. With a still camera every choice lands on
the same pixel: no effect, which is why the static bias tests never saw it. In motion, parallax sends medium
and surface to different pixels; at thin smoke most neighbours are picked through the surface, whose
previous pixel sees less of the medium at that depth, and the loss compounds through the history. Deep
smoke, where every choice sees medium, is unaffected. Check: no reprojection at all -- a neighbour that
trivially cannot depend on the sample -- removes most of it too (0.95 / 0.98, lanterns animating).

Fix, opt-in (it changes the estimator): `mTemporalReprojectIndependent` / `VR_TR_INDEPENDENT=1` draws the
point from the pixel alone, as the surface-sample branch already did. Off is byte-identical (8/8 captured
images). On, same test: medium light moving 0.99 thin / 1.00 edge, still 1.01 / 1.02; cost +0.06 ms
(temporal reuse 4.55 -> 4.60 ms at 960x540, frame unchanged); per-pixel noise at a MOVING silhouette
1.7-2x (thin 1.76 vs 0.90, edge 1.08 vs 0.65 of the true light; the history now matches it less often),
still frames and deep smoke unchanged. On screen (typical pixel vs the truth, thin / edge):

    moving                       as shipped     VR_TR_INDEPENDENT=1
    one RR                       0.87 / 0.89    1.03 / 1.00
    two-layer RR + pre-accum.    0.81 / 0.80    0.94 / 0.91
    still: all four 1.01-1.03.

One RR's moving/still typical edge pixel goes 0.86 -> 0.98 (thin 0.86 -> 1.00): visibly, the lamp-lit glow
at the silhouette stays while moving. Its output noise there barely changes (0.13 / 0.22 vs 0.12 / 0.21),
the few bright blotches get slightly stronger (regional mean moving/still at thin smoke 1.31 vs 1.27).
The two-layer path is smoother at the moving edge (0.12 / 0.14) but its medium RR still dims ~7-9% in
motion even with a correct, pre-accumulated input (0.98 / 0.94 of the true medium light).

Corrections, all mine:
  * "RR's INPUT at the edge carries the same average light moving and stopped" (entry above): measured on
    the total, whose 8-seed noise (+-8-16%) hid a 10-13% loss. Its closing guess -- "two thirds come with
    ReSTIR's temporal reuse" -- was the right direction.
  * The retraction "the estimator's temporal reuse loses energy while the camera moves" (the halo entry)
    is itself wrong for the medium: it does, at the silhouette. What that entry measured was the total.
  * Two-layer RR "stopped, the more accurate image -- edge 0.90 vs 0.81, blue 0.82 vs 0.64": against a
    proper truth (frozen lanterns, 256 frames) the still images are equal within a few percent, one RR
    slightly ahead (edge regional mean 0.93 vs 0.89, blue 0.89 vs 0.86). That truth averaged moving and
    still frames, so the moving loss biased it low, and the lanterns were animating.
  * MediumAccumulation cannot restore light its input lacks: with normal ReSTIR the accumulated layer was
    0.62 / 0.77 of the true medium light while moving -- exactly its input.

Also found: the bistro's lanterns and string lights sway (14 wind animations, `m.scene.animations`), and
they are its only lights. With them moving, ReSTIR shows transient bright bursts at the top of the plume
some 120-150 frames after the camera stops: 2-3x there at +120-130 frames as shipped, up to 10x at
+140-155 with the switch (every seed, decaying over ~15 frames; the rest of the thin smoke 1.4-2x for those
frames). None with the animation frozen, none with temporal reuse off. Not investigated further. A truth
has to be taken with the animation frozen: with the lights moving, the medium's light drifts +-5% over
30 s. Reproduce: `outputs/rim_tr/run_all.sh`, then `frozen_report.py` / `frozen_rr_report.py` there;
pictures `outputs/rim_tr/rim_fix_rr{,_zoom}.jpg` (stopped / moving as shipped / moving with the fix).

#### Following the layer by light share instead of by coverage (2026-09-19)

The fix above follows the surface with probability T, so at thin medium (T 0.7-0.99) the medium almost
never gets a matching history and its light is noisier in motion. `mTemporalReprojectByLightShare`
(`VR_TR_LIGHT_SHARE=1`, only with `mTemporalReprojectIndependent`) follows it with the surface's share of
the pixel's LIGHT instead -- the same estimate the guides use (GuideLightStats, last frame's running
average, so still independent of this frame's sample; the statistics pass now runs whenever either
consumer needs it). Same test (lanterns frozen, stop 3, 8 seeds, vs the 256-frame truth):

    medium light / true, moving      thin      edge        noise, moving (std / true mean)
    as shipped                       0.60      0.80        smoke 0.90 / 0.65   total 0.68 / 0.82
    fix, by T                        0.99      1.00        smoke 1.76 / 1.08   total 0.72 / 0.90
    fix, by light share              1.03      1.00        smoke 1.62 / 0.89   total 0.70 / 0.84

So it keeps the correction and buys back about half the extra noise at the silhouette (a third at thin
medium); in the total light the penalty over as-shipped drops to 2-3%. RR's own output noise is
unchanged either way (0.13 / 0.22 of the true light, moving); its typical moving pixel is 1.04 thin /
1.01 edge of the true light (by T: 1.03 / 1.00; as shipped 0.87 / 0.89). Both switches off is
byte-identical, and so is the by-T fix with the light-share switch off (12/12 images each). It costs
nothing to read (temporal reuse 4.60 -> 4.59 ms at 960x540, i.e. within run-to-run noise); where the
guide rule is off the statistics pass has to run for it, 0.13 ms at 960x540 and 0.54 ms at 1080p.

#### Is the change itself unbiased? (2026-09-19)

Checked against brute-force volumetric path tracing (`mUseReference`), which the repo's own bias tests use
but only with a STILL camera -- where this bias does not exist, since every depth then reprojects to the
same pixel.

  * The reference the numbers above are measured against -- ReSTIR with temporal reuse off, 256 frames at
    stop 3's pose -- is itself within 1% of a path-traced reference at that pose (256 frames x 4 spp,
    +-1.5% / 1.6% / 0.3%): thin 1.009, edge 0.994, deep 1.027. So "0.60 of the true light" is measured
    against something that is genuinely the true light, give or take a percent. (Deep smoke sits ~2.7%
    above the path tracer in EVERY configuration and both states -- the estimator's ray-marched
    transmittance and mip levels, untouched by this change.)
  * On the plume, where a path-traced reference converges in a minute, all three configurations agree
    with it within ~1% in both states (total light, 4 seeds, ground plane shaded so the surface-or-medium
    branch runs): as shipped 0.985 / 1.000 (thin / edge) moving, by T 0.992 / 1.009, by light share
    0.990 / 1.008; stopped 1.007-1.015 everywhere. The effect is small there because the plume's
    background is the environment map, i.e. at infinity, so the two reprojection choices land on nearly
    the same pixel -- it takes bistro's near background to separate them.
  * The TOTAL light on bistro cannot resolve this at 8 seeds (+-12% at thin, the lamps' fireflies),
    which is why every number above is the medium's own light, where the split is exact and the 8-seed
    error is 2-6%.

#### Without touching the code: what the shipped settings can do (2026-09-20)

Same test (lanterns frozen, stop 3, 8 seeds, vs the 256-frame truth). Both of these are parameters of the
original implementation, no code change:

    moving                        medium light, thin | edge    noise (smoke) thin | edge | deep
    as shipped                          0.60 | 0.80                 0.90 | 0.65 | 0.53
    Reprojection Mode = None            0.98 | 0.98                 1.33 | 0.84 | 0.73
    history cap 10x -> 2x               0.77 | 0.92                 1.40 | 1.17 | 1.05
    code fix, by light share            1.03 | 1.00                 1.62 | 0.89 | 0.54

"No Reprojection" recovers the rim nearly as well as the code fix -- the neighbour is then this pixel in
the previous frame, which cannot depend on the sample -- and blotches LESS on screen (RR's regional mean
moving/still at thin smoke 1.18, against 1.27 as shipped and 1.31/1.32 for the code fixes; RR's typical
moving pixel 1.03 thin / 1.01 edge of the truth). Its cost is deep medium, which loses motion
compensation entirely: noise 0.73 against 0.53 (RR's own output 0.09 against 0.07). Note this path
flatters it: the orbit is centred on the plume, so the medium barely moves on screen (the ground behind
it moves 6.9 px/frame), and "the same pixel" is nearly the right neighbour FOR THE MEDIUM. A pan, where
the medium crosses the screen, should behave differently -- untested.

The history cap is the poor lever: it only halves the loss and it costs noise everywhere, including
still frames (smoke 1.59 | 1.15 stopped, against 1.20 | 0.71 as shipped), since it shortens every
history and not just the mismatched ones.

Why a guide-side rescale cannot stand in for either. The light-share rule fixed the halo because that
was a ROUTING problem -- which layer's motion a pixel is given. This is an energy problem: the light is
already gone from ReSTIR's output. Reconstructing it from the guides would mean knowing the rim's true
brightness, and the medium's light per unit coverage is not flat across the silhouette -- measured on the
truth, 2.70x the deep-smoke value at 1-3% coverage, 2.36x at 3-10%, 2.21x at 10-30%, 1.12x at 90-99%.
The correction the moving frames would need runs from 1.01x (deep) to 2.08x (thinnest) and grows with
camera speed, so any fixed curve fits the bias rather than fixing it.
