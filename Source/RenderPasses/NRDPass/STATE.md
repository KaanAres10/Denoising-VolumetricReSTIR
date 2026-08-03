# Where this stands, and what to do next

Working notes for picking the NRD work back up. Measurements live in `README.md`; this file is the
open threads and the traps. Written 2026-08-03.

## The one thing to read first

**Every comparison against DLSS Ray Reconstruction so far was run WITHOUT SH mode.** NVIDIA's own
overview says:

> Its modern "SH" mode achieves quality comparable with DLSS-RR

`VR_NRD_SH` defaults to false, so every number below used `RelaxDiffuse` / `ReblurDiffuse`, not the
SH variants. The 2.6-3x sharpness deficit against RR was measured in the one mode NVIDIA does not
claim parity for, and it was described as "structural" on that basis. That conclusion is not
supported yet.

SH mode is already implemented and verified here — the resolve round-trip identity test landed at
3.02e-11 — and `VR_NRD_SH_RESOLVE` offers `Dc` (the defensible resolve for an isotropic phase
function, which is what both scenes use) and `Cosine` (NVIDIA's intended surface usage). Neither has
ever been measured under camera motion.

SH is not free: RELAX 3.25 -> 4.80 ms, REBLUR 2.55 -> 3.40 ms per NVIDIA's own figures.

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
`NRD4_MINLUMW`, `NRD4_LUMRELAX`. Nothing on this list changes the default path.
