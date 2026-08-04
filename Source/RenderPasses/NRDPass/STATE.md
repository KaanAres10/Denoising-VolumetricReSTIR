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
