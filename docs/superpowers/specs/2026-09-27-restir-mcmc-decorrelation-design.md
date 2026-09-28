# Volumetric ReSTIR decorrelation: measure the correlation, then mutate

**Date:** 2026-09-27
**Status:** design approved in chat; awaiting spec review
**Branch:** decorrelation

## Intent

Spatiotemporal reuse makes ReSTIR's per-pixel estimates correlated: neighbours share samples, and
history carries samples across frames. The result is blotchy, low-frequency error, which denoisers
treat as signal.

**Lin et al. 2021**, the method this repo implements:
- Fig. 15: small spatial-reuse radii make "correlation between nearby pixels… visually apparent".
- Fig. 14: a large temporal limiting factor Q overweights stale samples.
- Its limitations section names decorrelating the noise for denoisers as future work.

**Sawhney et al. 2024** ("Decorrelating ReSTIR Samplers via MCMC Mutations"):
- Adds Metropolis–Hastings mutations of each pixel's reservoir sample after temporal reuse, for
  ReSTIR DI and PT.
- This lowers short-range covariance and stays unbiased.
- It has little impact on MSE: it reduces correlation, not error.
- Its §7 says volumes should need only volume-specific strategies, such as Pauly et al. 2000's
  scattering and propagation perturbations.

This work has two phases, in this order:

1. **Phase A:** find and quantify the correlation that ReSTIR itself causes on this repo's
   volumetric scenes, and attribute it to reuse stages and parameters.
2. **Phase B:** add Metropolis–Hastings mutations and measure what they fix.

Both phases are judged first on the raw 1-spp output (covariance, duplicate samples, bias, MSE,
cost), then on the output of every denoiser in the harness.

### Success criteria

1. For every available scene, a measured Δρ̄(r) = ρ̄_reuse(r) − ρ̄_noreuse(r), with bootstrap
   confidence intervals, plus duplicate-sample heatmaps separating exact-sample sharing from
   light-ID sharing.
2. On the deep scenes, the extra correlation is attributed to a stage (temporal / spatial) and a
   parameter (M cap, radius, rounds, shared neighbour offsets). The attribution is recorded with
   crop sheets.
3. A findings checkpoint with the user before any estimator change.
4. With mutations off (the default), all captures are byte-identical to HEAD
   (`outputs/mask_check.sh raw`, `pending_9p/spec/verify.sh quick`).
5. With mutations on, region bias against the path-traced references matches mutation-off within
   error bars.
6. On scenes where Phase A found correlation, a mutation-on vs. mutation-off comparison of the
   relative change in C̄(8) (raw and robust), Δρ̄, relMSE and per-pass cost, plus the effect on
   every denoiser.

## Decisions already taken

| Decision | Choice | Rationale |
|---|---|---|
| Order | Study first, then mutations | Establish that there is reuse-induced correlation, and where it comes from, before claiming a fix for it. |
| Scope of round 1 | Single scatter | Every harness scene runs `mMaxBounces=1`. Multi-bounce perturbations are round 2. |
| Scenes | All available except the JangaFX EmberGen datasets | bistro, plume, plume g=-0.9, explosion, emerald (+Fog), bunny, bunny g=0.8, wdas. The user excluded FirePlumeVDB and DustShockwaveVDB (2026-09-27). `bunny_multilight.pyscene` is missing on disk. |
| Judged on | Raw first, then denoised | Raw is the paper's own evaluation; denoised is this repo's purpose. |
| Denoisers | OptiX, OIDN (GPU), NRD RELAX-SH, NRD REBLUR-SH, DLSS-RR | Every denoiser `add_denoiser` wires. `oidncpu` is the same network as OIDN. `sr` is an upscaler. SVGF is not wired into the harness. |
| Headline metric | Δρ̄ against no reuse | No-reuse output is not assumed uncorrelated: final shading's R2 sampler can correlate pixels by itself. |
| Covariance | Raw (paper Eq. 21) and robust (clamped, worst 0.01% trimmed) | Fireflies can be reuse-spread correlation, so they must not be discarded; robust is for plots. |
| Chains | R separately seeded chains, history reset between them; bootstrap over chains | Temporal reuse makes consecutive frames dependent. The chains are distinct pseudo-random realizations, not provably independent ones. |
| Mutation placement | A separate pass right after Temporal Reuse | The paper's placement. Off means the pass is neither created nor dispatched, so output is byte-identical. |
| Target for mutations | p̂_S (the temporal pass's `spatialOptions`) | The same deterministic target that temporal and spatial reuse evaluate. |

## What already works (verified 2026-09-27)

Read in the code, with no changes made:

- **The sample** (`HostDeviceSharedDefinitions.slangh:16`):
  - `depth` is the primary scatter distance along the camera ray; `kRayTMax` marks a
    surface/background sample.
  - The rest are `lightID`, `lightUV`, `p_y`, `runningSum`, `M`.
  - The contribution weight is `W = runningSum / (p_y·M)` (`FinalShading.cs.slang:209`).
  - Temporal and spatial reuse copy `depth` and the light sample verbatim: Lin's distance copy plus
    reconnection.
- **The emissive `lightUV` is always the area-uniform u.**
  - `sample_triangle(u)` (`MathHelpers.slang:400`) is the standard area-preserving warp.
  - Solid-angle samples store the inverted warp (`VolumeUtils.slang:332`).
  - Env samples store `worldToUv(dir)` (`VolumeUtils.slang:170`).
- **p̂ is deterministic.** The ray-marching and analytic trackers draw no random numbers
  (`VolumeTrackingAdapterGVDB.slang:141`).
  - `evaluate_F_` (`ReSTIRHelper.slang:141`) makes p̂ a density in `dt` along the ray × area
    (emissive, `Le·cos/d²`) or × solid angle (env).
- **Pass order** (`VolumetricReSTIR.cpp:1102–1337`): Generate Samples → Temporal Reuse (in place,
  p̂ from `spatialOptions`) → history copy if spatial is off → Spatial Reuse → CopyReservoirs (the
  post-spatial output becomes history) → Final Shading.
  - The temporal output's `p_y` comes from either the initial-sampling p̂ or the spatial p̂.
- **Suspected correlation sources:**
  - The M cap is ×10 on Bistro. One candidate was spread over ~100 frames (STATE:860).
  - `generateNeighborOffset` (`SpatialReuse.cs.slang:75`) ignores the pixel, so every pixel uses the
    same R2 neighbour offsets in a frame, and the pattern repeats every 16 frames.
- **Resets and seeds** (`VolumetricReSTIR.cpp:634,2099`):
  - An options change resets history and sets `mFrameCount=0`, so a plain reset replays the same
    realization.
  - `randomizeFrameSeed` draws `mFrameCount=rand()%65536` from `srand(123)`: reproducible,
    separately seeded chains inside one session.

## Architecture

### Components

| Component | Kind | Responsibility | Depends on |
|---|---|---|---|
| `Scripts/correlation_pose.py` | Mogwai script | Still pose per scene, frozen animation. Warm-up, R seeded chains × m captures spaced S apart, a 256-frame burst, raw HDR EXR. `VR_MODE=reference` for references. | `vr_graph.py`, `randomizeFrameSeed` |
| `Scripts/vr_graph.py` | Python module | Loaders for emerald, bunny, wdas. Knobs applied only when set: `VR_PHASE_G`, `VR_MTHRESH`, `VR_SR_RADIUS`, `VR_SR_COUNT`, `VR_SR_ROUNDS`, `VR_MUTATIONS`, `VR_MUT_STRAT`. | existing loaders |
| Sample-identity outputs | Final Shading optional outputs | `sampleId` = hash(`lightID`, `lightUV`, `depth`) and `lightId`. Bound and written only when requested. | the `gOutputLightDir` pattern |
| `VR_SR_PER_PIXEL_OFFSETS` | `-D` define, default 0 | Per-pixel Cranley–Patterson rotation of the R2 offsets. A diagnostic only. | `SpatialReuse.cs.slang` |
| `outputs/decorr/m_corr.py` | Python | C̄(r), ρ̄(r), Δρ̄(r) (raw and robust); 2D autocorrelation; temporal ρ(τ); duplicate heatmaps; reference errors; bootstrap CIs. | numpy, OpenCV EXR |
| `outputs/decorr/run_study.sh`, `sheet.py` | Shell, Python | Runs the study matrix; crop sheets and heatmaps. | the two above |
| `MutateSamples.cs.slang` | Compute pass "Mutate Samples" | Metropolis–Hastings on the temporal output, with the Eq. 16 weight update. | `evaluate_P_hat`, `SpecializeOptions.slangh` |
| `Scripts/tests/test_mutation_measures.py` | Test | Checks that u→area has a constant Jacobian and that uv↔ω round-trips. | numpy |

### Data flow

```
Phase A:  correlation_pose.py ──EXR/ids──▶ m_corr.py ──▶ tables, heatmaps, sheets ──▶ checkpoint
Phase B:  Generate Samples → Temporal Reuse → [Mutate Samples] → Spatial Reuse → Final Shading
                                                   ▲ off (default): not created, not dispatched
```

## Phase A: the correlation study

**Capture:**
- Warm-up is W = max(256, 4·Mcap) frames. The first and second halves of the captures must agree
  within their confidence intervals on frame mean and on ρ̄(8).
- Spacing S is the first lag, coprime with 16, at which the burst's ρ(τ) < 0.05.
- The defaults R = 20 and m = 5 give K = 100.
- The run logs each chain's starting frame count and rejects duplicates.

**Metrics:**
- C̄(r) is the per-pixel mean Cov(i,j) over a box of radius r, then the image mean, for r = 1…16.
  - It is computed in O(K·N) with box filters of the residuals.
  - Per region: score.py's regions on Bistro, the medium mask elsewhere.
- The normalised ρ̄(r) and Δρ̄(r) are the headline numbers.
- The FFT autocorrelation shows the correlation length and its anisotropy.
- ρ(τ) shows boiling and lag.
- Duplicate heatmaps use 20×20 windows.
- Against the reference: region bias, relMSE (raw and trimmed), and error blurred at 2/8/32 px.

**Matrix:**
1. All scenes: no reuse vs. as shipped. Rank by Δρ̄ and by duplicates.
2. Deep scenes (Bistro, plume g=-0.9, plus the top-ranked), one factor at a time:
   - stages: temporal only / spatial only / both;
   - M cap: 1, 4, 10, 20, 50, 200;
   - radius: 3, 10, 30;
   - rounds: 1, 3;
   - per-pixel offsets on/off.
   The deep scenes get references; Bistro reuses `forkref/cap/v9sa_ref`.
3. All five denoisers, in two settings:
   - still pose, as shipped vs. no reuse: blurred error and ρ̄ of the error;
   - the locked Look orbit: `m_denoisers.py`.

**Checkpoint:** record the findings below, and in STATE.md, then review them with the user. The
findings set Phase B's strategy priority and which scenes it covers.

## Phase B: mutations

### The weight update

For a chain x₀ → z with target p̂_S, the paper's Eq. 16 is `W(z) = p̂_S(x₀)/p̂_S(z) · W(x₀)`. With
`W = runningSum/(p_y·M)`, the pass evaluates p₀ = p̂_S(x₀) and writes:

```
p_y        ← p̂_S(z)
runningSum ← runningSum · p₀ / p_y_old
M          unchanged
```

This gives exactly Eq. 16 whichever target produced the old `p_y`. It also leaves `p_y` equal to
p̂_S at the pixel's own sample, which is what spatial reuse's Talbot MIS reads it as.

**Invalid reservoirs are never mutated.** Unless `runningSum > 0`, `M > 0`, `p_y_old > 0` and finite,
and `p₀ > 0` and finite, the reservoir is left untouched. A non-finite p̂(z) counts as 0.

### Support and ergodicity

- **Support.** The mutated samples are unbiased only under the paper's assumption: the temporal
  reservoir's W is unbiased over all of supp(p̂_S). This holds if candidate sampling covers
  supp(p̂_S).
  - Lin §4.1 engineers this for distance sampling: nearest sampling, with zero voxels returning their
    neighbours' average.
  - It is checked empirically: count temporal outputs with p̂_S(x₀) = 0 or p̂_S(x₀) ≠ `p_y`, plus the
    bias gate.
- **Ergodicity.** Round 1 never changes `lightID` or the sample type, and bounded depth steps cannot
  cross an empty gap wider than s2. So the chain explores only the component reachable from x₀.
  - Unbiasedness does not need ergodicity: Eq. 16 needs only detailed balance and an unbiased W(x₀).
  - Nothing here claims that infinitely many round-1 mutations converge to the full per-pixel p̂.
  - The supplement's infinite-mutation covariance argument holds only within the reachable component.
  - A weak result where Phase A finds light-ID sharing means "these mutations don't reach it".

### Proposals

Each proposal is symmetric in the measure p̂_S is a density in, so the acceptance is
`min(1, p̂_S(z)/p̂_S(x))`.

- Invalid proposals get p̂ = 0 and are rejected; they are never resampled until valid, which would
  break symmetry.
- Each strategy has a fixed, state-independent probability.
- A strategy that does not apply to the current sample is a self-transition: nothing changes and p̂
  is not evaluated. The selection probability cancels.

**Round 1 strategies:**

1. **Light-vertex perturbation** (paper §4.2):
   - Emissive: `u' = frac(u + δ)` on the torus, with Kelemen magnitudes `s2·exp(−log(s2/s1)·U)` and
     a random sign. The triangle stays fixed.
   - Env: rotate ω by an angle drawn log-uniform in [θ1, θ2] with uniform azimuth, which is
     symmetric in solid angle. Store `worldToUv(ω')`.
   - Delta lights are not mutated.
   - Applies to volume and surface samples.
2. **Propagation perturbation of the scatter depth** (Pauly §5.1):
   - `t' = t ± D`, with D log-uniform in [s1, s2]·(voxel size). The scale is state-independent.
   - The light vertex stays fixed.
   - Out-of-medium, behind-surface and t' ≤ 0 proposals are rejected.
   - Applies to volume samples, including self-emission.

**Round 1.5, only if Phase A shows light-ID sharing dominates:** light re-selection by independence
Metropolis.
- Propose z ~ q from the scene light sampler at the current x₁.
- Accept with `min(1, p̂(z)q(x)/(p̂(x)q(z)))`.
- q and p̂ are densities on one mixed reference measure: the disjoint union of area (emissive),
  solid angle (env) and point mass (delta lights).
- q is the selection pdf × the near/far point pdf, both computable from the existing sampler code.

### The pass

- **Dispatch:** `MutateSamples.cs.slang` is dispatched after Temporal Reuse and before the
  spatial-off history copy (`VolumetricReSTIR.cpp:1182`). If temporal reuse is off, it mutates the
  initial samples.
- **p̂ evaluation:** `evaluate_P_hat`, called as `resampleNeighbor` calls it: the same camera ray as
  `TemporalReuse.cs.slang:170`, the VBuffer item, and `SAMPLING_OPTIONS`.
  - Light-only moves pre-fill the primary-ray visibility (`ArrayDataProvider.slang:54`).
- **Random numbers:** a `SampleGenerator` seed with the top bit set, disjoint from every other pass.
- **Params** (serialized, UI, env): `mMutationCount` (`VR_MUTATIONS`, default 0), a strategy mask
  (`VR_MUT_STRAT`), step ranges, and the thread group (`VR_GROUP_MU`).
- **Statistics:** optional per-strategy acceptance counters.
- **Disabled when:** `mMaxBounces > 1`, `mVertexReuse` is on, or in reference mode.

### Evaluation

- **Gate: unbiased.**
  - `bias_test_plume.py` (point light) with 5 mutations.
  - Bistro region bias against `v9sa_ref` via `forkref/score.py`.
  - Both must match mutation-off within error bars.
- **Main matrix:** Phase-A scenes × mutations {0, 1, 5} × strategy {light, depth, both}. Report:
  - the relative change in C̄(8), raw and robust (Table-1 form);
  - Δρ̄;
  - duplicate heatmaps, relMSE, acceptance rates, per-pass ms.
- **M cap with mutations:** {10, 50, 200} × {0, 1} (paper Fig. 11).
- **Equal-time:** mutations vs. a larger `mInitialM` (paper Fig. 7).
- **All five denoisers**, 0 vs. 1 mutation: still pose and orbit.
- **Acceptance rates** are reported per strategy but are not a correctness gate. A rate near 0 or
  near 1 prompts step tuning. The paper's ~40% / ~70% (full-path vs. partial-path mutations, one
  scene) is an observation, not a target.

## Other volumetric mutation methods considered

| Method | Fit here | Verdict |
|---|---|---|
| Light-vertex perturbation (paper §4.2) | Native to `lightUV` | Round 1 |
| Pauly propagation perturbation, primary depth | Native to `depth` | Round 1 |
| Independence-Metropolis light re-selection | Breaks light-ID sharing | Round 1.5 if Phase A calls for it |
| Pauly scattering perturbation / later-bounce propagation | Extra bounces are (ω, dist) in dω·dt | Round 2 (multi-bounce) |
| Paper's reconnection-vertex / partial-path mutations | Equivalent to the rows above for Lin's shifts | Covered |
| Kelemen full primary-sample-space / large-step | Random numbers are not stored; initial candidates already rejuvenate | No |
| Medium↔surface swap (Pauly §7), reversible jump (Bitterli 2017) | Mixed measure; needs RJMCMC | Only if Phase A shows medium/surface edge correlation |
| Independent-MCMC / MTM temporal reuse (Zhou 2025 ch. 5) | Replaces temporal RIS | A later comparison |
| Ghost ReSTIR null-scattering PSS | Makes p̂ consistent across stages | Out of scope (re-architecture) |
| Langevin/HMC, guided proposals | Needs p̂ gradients through GVDB | No |
| Adaptive per-pixel mutation count (paper §7) | Could use Phase A's maps | After round 1 |

## Risks and early verification

| # | Risk | Early check |
|---|---|---|
| R1 | Seeds collide across chains (`rand()%65536`) | Log each chain's frame count; reject duplicates. |
| R2 | Consecutive captures still share history | Spacing from the measured ρ(τ); bootstrap over chains. |
| R3 | Fireflies dominate raw covariance | Report raw and robust side by side. |
| R4 | The p̂_S support is wider than candidate sampling's (bias under depth moves) | Count p̂_S(x₀) = 0 and ≠ `p_y` at the temporal output; the bias gate. |
| R5 | Mutation-off is not byte-identical | `mask_check.sh raw` and `spec/verify.sh quick` after every change. |
| R6 | `lightUV` or env uv mappings are not what the code reading says | `test_mutation_measures.py` before any mutation run. |
| R7 | Captures break on missing runtime DLLs | Check `libprotoc.dll`/`z.dll` before each batch (`restore_runtime_dlls`). |

## Verification results

Phase A results are recorded here as V1…Vn, each confirmed or dismissed, as in the earlier specs; Phase B's
as V-B1…

All Phase A numbers: 1920×1080, K = 100 captures (10 separately seeded chains × 10, spacing 5 — emerald 3 —
from the bursts), warm-up max(256, 4·Mcap), 95% CIs from a bootstrap over chains. ρ̄(r) is the robust
Eq. 21 correlation (clamped luminance, worst 0.01% of pixels out), Δρ̄ its excess over the same scene without
reuse. "Smoke" is m_corr's `medium` block: pixels whose sample scattered in the medium in most frames, on the
no-reuse run's mask. Volume scenes re-rendered after the env-background fix (924506c); bistro has no env
background, emerald's is 1000× dimmer (−0.03%), so theirs stand. `outputs/decorr/summary.tsv` has every run.

### V1 — reuse correlates neighbouring pixels on every scene: confirmed

| Scene | Δρ̄(8) whole | Δρ̄(8) smoke | shared-sample px / 400 (frame) | relMSE reuse / none | bias vs ref |
|---|---|---|---|---|---|
| emerald (fog + surfaces) | 0.0196 | 0.0223 | 147 (+131 emitter) | 0.00046 / 0.0177 | −0.03% |
| bistro (smoke + surfaces) | 0.0142 | 0.0251¹ | 170 (+252 emitter) | 0.00087 / 0.0228 | 0.00% |
| plume g = −0.9 | 0.0141 | 0.0164 | 22 | 0.097 / 2.26 | +0.02% |
| bunny g = 0.8 | 0.0075 | 0.0082 | 29 | 0.034 / 0.458 | 0.00% |
| bunny | 0.0065 | 0.0074 | 28 | 0.035 / 0.477 | +0.01% |
| plume | 0.0063 | 0.0072 | 19 | 0.031 / 0.436 | +0.03% |
| wdas 1× | 0.0053 | 0.0059 | 37 | 0.053 / 0.476 | 0.00% |
| explosion | 0.0053 | 0.0035 | 25 | 0.071 / 0.125 | −0.56% |

¹ bistro's smoke mask is small (0.1% of pixels: most smoke pixels alternate between surface and medium
samples), hence its CI [0.019, 0.031]. Inside the medium 100–110 of 400 pixels per tile share a sample on the
volume scenes (the frame means above include background). No-reuse ρ̄ is 0 ± 1e-4 everywhere except bistro's
smoke, which is slightly anti-correlated at 1 px (−0.016: final shading's stratified sampler). The variance of
a 17×17 box average is 1 + 288 ρ̄ times the independent-pixel variance: 5.7× in the plume's smoke, 7.4× in
emerald's fog, 7.9× in bistro's smoke at the shipped settings. Error: reuse is 1.7–38× lower in relMSE and
1.3–4.1× lower after an 8 px blur — the blotches are correlated, but still less error than no reuse — except
on the explosion, whose blurred error is 2.4× (8 px) to 3.7× (32 px) HIGHER with reuse: its −0.56% reuse
bias is low-frequency by nature and survives the blur that averages the noise away. Open.

### V2 — spatial reuse creates it, temporal history multiplies it: confirmed

Temporal reuse alone adds nothing between pixels (Δρ̄(8) 0.0001 bistro, 0.0000 plume g = −0.9, 0.0004 emerald —
the last flat over r, a frame-wide wobble). Spatial reuse alone adds the same on all three deep scenes
(0.0052 / 0.0047 / 0.0050, dip at r = 2–4, rise at 8: the fixed offsets). Both together: 2.7–3.9× the
spatial-only value — the history carries shared samples forward.

### V3 — the M cap is the strongest lever; radius and rounds trade correlation for error: confirmed

| Δρ̄(8) (smoke on the volumes) | cap 1 | shipped | 10 | 20 | 50 | 200 |
|---|---|---|---|---|---|---|
| plume g = −0.9 (shipped cap 4) | 0.009 | 0.016 | 0.021 | 0.025 | 0.044 | 0.120 |
| bistro whole (cap 10) | 0.0071 | 0.0142 | — | 0.0170 | 0.0275 | 0.078 |
| emerald fog (cap 10) | 0.010 | 0.022 | — | 0.023 | 0.026 | 0.056 |

A longer history lowers error (bistro relMSE 0.00087 → 0.00050 at cap 200) until the correlated samples
start to cost it (plume: 0.025 at cap 50, 0.029 at 200, blurred error 0.0074 → 0.0102). Reuse radius 3
concentrates the correlation (ρ̄(1) ≈ 0.20 on all three), radius 30 removes it (Δρ̄(8) 0.002–0.004) at +37–
69% relMSE — radius 10 is the lowest-error setting on all three, Lin et al.'s choice. Three spatial rounds:
1.75–3× the correlation, reaching 16 px, for −29% relMSE (bistro).

### V4 — the shared R2 offsets shape the correlation but do not cause it: confirmed

Per-pixel offsets (VR_SR_PER_PIXEL_OFFSETS) RAISE Δρ̄(8) by 28–36% on all three deep scenes and shared
samples (bistro 170 → 192 per tile): a frame-wide offset is a translation, so every source pixel feeds exactly
one pixel per slot; per-pixel offsets collide. What the shared pattern does is put the correlation at fixed
offsets — isolated autocorrelation peaks at (5,4) 0.071 and (7,0) 0.056 against a 1-px ring mean of 0.025
(bistro), smoothed away by per-pixel offsets. Keep the shared offsets.

### V5 — exact-sample vs emitter sharing: emitter sharing dominates the surface scenes

Per 20×20 tile, whole frame: bistro 170 pixels share an exact sample and 252 an emissive triangle; emerald 147
and 131; the volume scenes share exact samples only (env map + self-emission, no triangle IDs). Round-1
mutations can break exact sharing, never emitter sharing (V-B2).

### V6 — temporal: shipped ρ(τ = 1) ≈ 0.3, below 0.05 by lag 4–5 (emerald 3): confirmed (bursts)

### V7 — what reaches the denoisers: temporal denoisers keep it, single-frame ones blur it

Δρ̄(8) of the denoised output, reuse against no reuse through the same denoiser (plume g = −0.9, fixed build):
OptiX +0.024, OIDN −0.053, NRD RELAX-SH +0.194, NRD REBLUR-SH +0.124, DLSS RR +0.024; bistro covariance at 8 px
×1.1 / ×0.7 / ×16 / ×60 / ×2.4. NRD accumulates over frames, which averages independent noise away but not a
sample shared across pixels and frames: the residual is 16–60× more low-frequency structure. OptiX and OIDN
filter spatially and hide it (OIDN's ρ̄ even drops with reuse: it smooths the cleaner input less). The
reuse-vs-none comparison after a denoiser is confounded by a 25× difference in input noise, so Phase B
compares the same denoiser with and without mutations. Against the reference, OptiX and RR are dominated by
their own bias (OptiX blurs bistro's facade texture 7% dark; RR's relMSE is unchanged by reuse).

### V8 — Lin et al.'s density figure (wdas 0.2× / 1× / 3×): partly reproduced

Smoke Δρ̄(8) 0.0072 / 0.0059 / 0.0044 — thinner media correlate more, and the 0.2× frames show the chroma
speckle of Lin's figure. But reuse stays far ahead of no reuse on error: relMSE 0.014 vs 0.176, 0.053 vs 0.476,
0.138 vs 0.677, all unbiased. Lin's "ReSTIR worse at 0.2×" compares against equal-time path tracing, not
against the same pipeline without reuse, and ran on the Falcor 4 build.

### V9 — measuring volumes: judge the smoke, not the frame (instrument fix)

The image-wide ρ̄ weights every pixel alike, and 63–82% of a volume frame is near-noiseless background: it
diluted the medium's correlation (plume g = −0.9, M cap 200: 0.106 whole vs 0.120 smoke on the fixed build) and,
before 924506c, the bug's background pixels added their own (the ρ̄(1) = 0.18 spike at cap 50 was the bug).
m_corr's `medium` block, on the no-reuse run's mask, is the volume headline. Also fixed along the way:
emerald's display exposure (0 → run_emerald_square.py's +8.5 EV, display only).

### V-B1 — the mutations are unbiased (R4): confirmed

`outputs/decorr/gate.sh`, 2026-09-27, mutations 0 vs 1 / 5 (light + depth, Kelemen steps as the defaults):

| Scene | Against | 0 mutations | 1 | 5 |
|---|---|---|---|---|
| Plume, one point light (depth moves only), 960×540, 4096 frames | path-traced reference | whole +2.13%, plume box +1.76% | — | +2.14%, +1.77% |
| Bistro, verify pose, 4096 frames (`forkref/score.py @v9sa`) | path-traced reference | plume core +2.47 ± 0.10%, street −0.16 ± 0.03%, facade −0.07%, whole 0.00% | +2.47 ± 0.08, −0.15 ± 0.02, −0.07, 0.00 | +2.46 ± 0.08, −0.14 ± 0.02, −0.07, 0.00 |
| Plume, env map, 1080p, 40 captures | no reuse | whole −0.04%, centre −0.26% | — | −0.04%, −0.26% |
| Explosion, 1080p, 40 captures | no reuse | whole −0.57%, centre −0.66% | — | −0.57%, −0.65% |

Every region's bias with mutations is within the mutation-off error bars; the offsets that remain exist
without mutations (below). Bistro's per-frame error: trimmed MSE 0.00331 → 0.00331 → 0.00330, blurred at 2 px
0.00282 → 0.00268 → 0.00266, at 8 px 0.000353 → 0.000340 → 0.000335 — per-pixel error unchanged, the
low-frequency (blotchy) part down 5–6%, the paper's "little impact on MSE" with the decorrelation where it
should be. Acceptance: plume light (env rotation) 25%, depth 45–52%; bistro light 95% (small emitters: p̂ is
nearly flat over a triangle), depth 39%; explosion depth 38%. The temporal output's `p_y` equalled p̂_S(x₀)
at every pixel (counter 5 = 0), so the Eq. 16 update never had to reconcile two targets.

Offsets present WITHOUT mutations, not caused by them: the one-light plume's +2.1% (on record since July);
Bistro's plume core +2.5% (no reuse is +4.2%: a reference/scene mismatch in that region); the explosion's
−0.6% from reuse. Open.

### V-B2 — how much one round of mutations decorrelates: 2–18% at the shipped M caps, 50–80% at long histories

Relative covariance, Sawhney et al.'s Table 1 form (mean covariance within 8 px, mutated ÷ not, same M cap):

| | 1 mutation (light + depth) | 5 mutations |
|---|---|---|
| Paper, ReSTIR PT, Mcap 50 (their scenes) | 0.69–0.93 | 0.61–0.88 |
| Ours, shipped caps (4 / 10), whole image, all 10 scenes | 0.82–0.98 | 0.87–0.92 |
| Ours, shipped caps, smoke | 0.71 (bistro) – 0.99 | 0.59 (bistro) – 0.91 |
| **plume g = −0.9, Mcap 50** | **0.40 whole / 0.48 smoke** | — |
| **plume g = −0.9, Mcap 200** | **0.22 / 0.21** | — |
| emerald, Mcap 200 | 0.52 / 0.43 | — |

Mutations also halve the pixels that share an exact sample (bistro 170 → 82, emerald 147 → 78, plume 22 → 16
per 20×20 tile) and leave emitter sharing as it was (bistro 252) — round 1 cannot reach it. Per-pixel error is
unchanged at the shipped caps (the paper's "little impact on MSE").

Why small at the shipped caps: (1) with p̂ = luminance(f), Eq. 16 leaves the mutated pixel's own luminance
estimate unchanged (the paper's Eq. 17; measured: 0.15% mean change) — mutations decorrelate only through what
spatial and temporal reuse do with the diversified samples afterwards; (2) spatial reuse runs after the
mutation and re-shares within the frame (the spatial-only part, a third of Δρ̄, is out of reach); (3) a 4–10×
history is diluted by fresh candidates before diversity accumulates. The paper evaluates at Mcap 20–1000.

### V-B3 — mutations make a long history usable: confirmed (the paper's Fig. 11, on volumes)

| plume g = −0.9 | whole ρ̄(8) | smoke ρ̄(8) | relMSE | blurred err 8 px |
|---|---|---|---|---|
| shipped (Mcap 4) | 0.0141 | 0.0164 | 0.0969 | 0.0096 |
| Mcap 50 | 0.0391 | 0.0439 | 0.0250 | 0.0074 |
| Mcap 50 + 1 (depth only) | 0.0160 | 0.0174 | — | — |
| **Mcap 50 + 5** | **0.0140** | **0.0152** | **0.0236** | 0.0073 |
| Mcap 200 | 0.1057 | 0.1200 | 0.0286 | 0.0102 |
| Mcap 200 + 1 | 0.0381 | 0.0415 | 0.0242 | 0.0078 |

Mcap 50 + 5 mutations: the shipped correlation at a quarter of its error, unbiased (+0.02%). Past ~50 the
correlated history costs error back (Mcap 200: relMSE 0.029, blurred 0.0102); one mutation takes that back
(0.024, 0.0078). Emerald: Mcap 50 + 5 mutations has less correlation than shipped (fog 0.0140 vs 0.0223,
whole 0.0162 vs 0.0196; 68 vs 147 shared-sample pixels per tile) at 2.5× lower relMSE (0.00018 vs 0.00046),
bias −0.14% (no reuse −0.09%, within the scatter); depth-only 5: fog 0.0147 (emerald's emissive lamps let light
moves help a little). In its fog the blurred single-frame error halves with the longer history (worst regions
45 / 32 / 26% → 27 / 15 / 12%) and the mutations take the correlation.

Why 50 (`outputs/decorr/mcap_chart.png`): error falls steeply with the cap up to ~50 and then flattens
(emerald, bistro) or turns back up (plume g = −0.9 without mutations), while correlation keeps rising and
accelerates past 50; at 50 the mutations bring it back to or below shipped. Between 50 and 200 with one
mutation the error is the same (plume 0.0241 / 0.0242) and the correlation twice as high (0.022 / 0.042).
Untested: caps 20–100 with mutations (the optimum may sit anywhere in that range), and any camera or medium
motion — a long history keeps stale samples when things move (Lin et al. Fig. 14); every number here is a still
pose on a static medium.

### V-B4 — which moves: depth; light moves do not decorrelate these scenes

Light moves (env rotation 0.1–5° or up to 30°, emitter u steps up to a quarter of the triangle) leave ρ̄ where
it was on every scene (plume g = −0.9: 0.0164 with 1 or 5 light moves, 0.0164 with 30° steps at 14%
acceptance). What a neighbour q gains from p's reused sample scales with p̂_q/p̂_p, and for adjacent pixels that
ratio hardly depends on the light direction or the point on the emitter — it depends on where the scatter point
is. Depth moves change exactly that. Mcap 50: 1 depth-only mutation 0.0174 vs 1 mixed 0.0217 (smoke). The
paper's large DI gains come from glossy BSDF lobes, where p̂_q/p̂_p IS direction-dependent; volumes and diffuse
surfaces lack that. Default depth steps (0.5–16 march steps) beat 0.05–1.6 (smoke 0.0150 vs 0.0160, 1 move;
0.0139 vs 0.0153, 5) and match 2–64: in a dense medium every step exceeds the mean free path, so moves toward
the camera are always accepted and deeper ones rejected (acceptance 0.499 at any step past the free path; 0.74 in
the 0.2× cloud, 0.33 at 3×) — correct MH, one-way exploration. Next: an independence move that redraws the depth
from the free-path distribution along the ray (Pauly's propagation idea), q in the acceptance ratio.

### V-B5 — equal time and cost: on bistro, more initial candidates win

One mutation costs 13.5 ms at 1080p on bistro (+15%; 5 cost 33 ms), the same as mInitialM 4 → 8. At equal time
mInitialM 8 beats one mutation everywhere on bistro (whole ρ̄(8) 0.0119 vs 0.0137, relMSE 0.00072 vs 0.00086,
blurred 0.0150 vs 0.0209) and mInitialM 14 beats five (0.0105 vs 0.0133): bistro's correlation is emitter
sharing, which more candidates dilute and mutations cannot touch. A mutation evaluates p̂ twice (the current
sample, then the proposal); the first is redundant (temporal output p_y equalled p̂(x₀) at every pixel) —
about a third of the pass.

### V-B6 — denoisers: one mutation at the shipped caps changes little

Same denoiser, shipped vs 1 mutation (bistro, plume g = −0.9): ρ̄(8) within ±2.4%, covariance −2 to −6% (RR
bistro −18%), blurred error unchanged — the raw decorrelation at these caps is 5–9%, and the denoisers see
that. The long-history configurations (V-B3) are where a denoised comparison is worth running next.

### V-B7 — root cause of the small effect: the correlation lives in shared normalizations, which mutations keep

Not a bug: the kernel is unbiased (V-B1), its moves are accepted at sane rates, and a step size of 10⁶ drops
acceptance to 0 as it must. The limit is structural. A pixel's estimate is f(y)·W = (f/p̂)(y) · runningSum/M,
and here p̂ is the final shading's integrand evaluated on the coarse grid, so f/p̂ ≈ 1 and the estimate is
≈ runningSum/M, the reservoir's normalization. Eq. 16 keeps that normalization by construction (the paper's
Eq. 17). Pixels that resampled from the same inputs share their normalizations, and that part of the covariance
is out of any mutation's reach; in the supplement's analysis it is the (p̄·W − 1) factor of Eq. 11, the input's own
importance-sampling error, which mutations do not change; what they remove is the mismatch of neighbouring
targets (Eq. 18), which is small in a smooth medium. Evidence, plume g = −0.9, smoke ρ̄(8):

| | 0 mutations | 1 | 5 | 32 (depth) |
|---|---|---|---|---|
| spatial reuse only | 0.0054 | — | 0.0054 | — |
| shipped (Mcap 4) | 0.0164 | 0.0150 | 0.0139 | 0.0136 |
| Mcap 50 | 0.0439 | 0.0217 | 0.0152 | 0.0120 |

1. Spatial-only correlation is identical to four decimals with 5 mutations: within one frame the mutations
   change which sample a pixel offers, not the weight its neighbours receive for it.
2. The mutations saturate: 32 remove 17% at the shipped cap and 73% at Mcap 50, leaving 0.012–0.014 — 2.2–2.5×
   the spatial-only level.
3. Sample identity is not the carrier: with 5 or 32 mutations a frame holds fewer duplicated samples than
   spatial-only reuse (13.6 vs 18.3 pixels per 20×20 tile) and 2.5× its correlation. What mutations remove is
   the persistence of "winner" samples, which grows with the M cap (Mcap 50: 29.0 → 13.0 duplicates per tile);
   the rest is spatially shared normalization compounded through the history (spatial output → history →
   next frame's spatial reuse).

Literature agreeing: Lin et al. 2026 (ReSTIR PT Enhanced, §5) note that mutations "only reduce certain types of
correlation" and cut the M cap where samples are duplicated instead; Zhou 2025 (thesis §5.5.5) keeps spatial
output out of the history ("decoupled"), which "rarely suffers from correlation artifacts" at more noise;
Junkins et al. 2026 frame ReSTIR's error–correlation trade-off as a Pareto curve that the M cap and the reuse
radius move along. On that curve (`outputs/decorr/pareto_chart.png`) the mutations are a real improvement where the
paper evaluates them — at a long history, equal error with 47–73% less correlation (plume Mcap 50: 0.044 →
0.012; emerald: 0.026 → 0.014) — and a small one at the shipped caps, which already sit at the low-correlation
end. Radius 30 at the shipped cap is well below the M-cap curve on both scenes (plume relMSE 0.166 at
ρ̄ 0.0020; emerald 0.00063 at 0.0055).

### V-B8 — sharing less: a decoupled history wins; a wide radius makes mutations pay; the duplication cap fails here

Three fixes from the literature for the normalizations V-B7 found shared (b8ea445, all opt-in): a decoupled
history (`VR_DECOUPLED=1`: the history is the temporal and mutated reservoir, spatial reuse only shades; Zhou 2025
§5.5.5), a duplication-driven M cap (`VR_DUP_CAP=0.5`; Lin et al. 2026 §5, RTXDI's strength curve), and the
reuse radius (Junkins et al. 2026 §6). Correlation in the medium, ρ̄(8); bias relative; blurred = RMS error at
8 px (`outputs/decorr/pareto_chart.png`, `run_share.sh`, `run_share2.sh`):

| plume g = −0.9 | smoke ρ̄(8) | relMSE | blurred 8 px | bias |
|---|---|---|---|---|
| shipped (Mcap 4) | 0.0164 | 0.0969 | 0.0096 | +0.02% |
| Mcap 50 / + 5 mutations | 0.0439 / 0.0152 | 0.0250 / 0.0236 | 0.0075 / 0.0073 | +0.02% |
| decoupled, Mcap 4 | 0.0050 | 0.2341 | 0.0098 | +0.01% |
| decoupled, Mcap 50 (+ 5 mutations) | 0.0032 (0.0032) | 0.0462 (0.0452) | 0.0071 | +0.02% |
| **decoupled, Mcap 200** | **0.0020** | **0.0265** | **0.0071** | +0.02% |
| radius 30, Mcap 50 / + 5 mutations | 0.0077 / 0.0021 | 0.0643 / 0.0617 | 0.0075 / 0.0073 | +0.01% |
| duplication cap, Mcap 50 / 200 | 0.0184 / 0.0304 | 0.335 / 1.24 | 0.138 / 0.222 | −0.1% |

| Emerald (fog) | fog ρ̄(8) | relMSE | blurred 8 px | bias |
|---|---|---|---|---|
| shipped (Mcap 10) | 0.0223 | 0.00046 | 0.160 | −0.03% |
| Mcap 50 / + 5 mutations | 0.0262 / 0.0140 | 0.00018 / 0.00018 | 0.100 / 0.105 | −0.09 / −0.14% |
| decoupled, Mcap 10 | 0.0043 | 0.00192 | 0.176 | −0.01% |
| decoupled, Mcap 50 (+ 5 mutations) | 0.0033 (0.0033) | 0.00069 (0.00069) | 0.127 | +0.02% |
| **decoupled, Mcap 200** | **0.0025** | **0.00033** | **0.047** | −0.08% |
| radius 30, Mcap 50 / **+ 5 mutations** | 0.0075 / **0.0035** | 0.00027 / **0.00026** | 0.119 / 0.109 | −0.04 / +0.01% |

- **Decoupled history, long cap: better than shipped on every axis on both scenes** — plume 8× less correlation
  and 3.7× less error, emerald 9× less correlation, 28% less error and 3.4× less blurred error. Without spatial
  feedback the history no longer grows correlation with the cap (Mcap 200: 0.0020 decoupled vs 0.120 coupled),
  so the cap can go long. Mutations add nothing there (0.0032 → 0.0032 on both scenes): the history-borne
  sharing they remove is gone. Cost: none (a copy moves). Untested: motion — a decoupled history gets no
  spatial help after disocclusion, and a long cap keeps stale samples when things move (Lin et al. Fig. 14).
- **Radius 30 is where mutations pay off**: 5 mutations take plume 0.0077 → 0.0021 and emerald 0.0075 → 0.0035
  (−54 to −73%; exact-sample sharing 72 → 8 pixels per tile on emerald). Neighbours 30 px apart have less
  similar targets, and that mismatch (supplement Eq. 18) is what mutations remove. Emerald radius 30, Mcap 50,
  5 mutations beats shipped by 84% in correlation and 43% in relMSE.
- **The duplication cap fails on these volumes**: stationary bright blobs (≈50 where the reference is 0.15,
  up to 1300 px) at the same two places near the plume's bright flame in independently seeded chains —
  a systematic bias, not noise. The paper reports that the cap "introduces some bias"; here it is severe. The
  control — the same cap curve from a random fraction that depends on no sample (`-DVR_DUP_CAP_RANDOM=1`,
  Mcap 50) — has no blobs (largest 6 px vs 1285) and the plain cap's bias (+0.018% vs +0.019%): the per-pixel
  caps are handled correctly, and the blobs come from the cap depending on the pixel's own sample (how widely
  it was duplicated), which breaks GRIS's unbiasedness. The emerald runs failed on a pass-creation bug (surface
  scenes need the scene's shader modules; fixed) and are being re-run.

### Found while checking the plume's look: temporal reuse brightened the env background (fixed, 924506c)

`ReSTIRHelper.slang` looked background samples up with `envMapSampler.eval(ray.dir, isLastFrame)`; Falcor 9's
signature is `eval(dir, lod, isPrevFrame)`, so every previous-frame evaluation of a background sample — the
temporal Talbot weights' — read the env map's mip 1. Plume at 1080p, temporal reuse vs no reuse: +7.89% before,
−0.04% after (`outputs/decorr/bias_diag.sh`), the same as with Talbot MIS off; the brightest 1% of background
pixels had been +9.4%, mid-bright ones −6%, medium pixels exact. It affected every Phase A run with temporal
reuse on an env-lit volume scene in its background pixels only; `run_extra.sh` re-renders those.

## Out of scope

- Multi-bounce mutations (round 2) and vertex-reuse mode.
- Changing any default. Mutations and `VR_SR_PER_PIXEL_OFFSETS` stay opt-in.
- Ghost ReSTIR's null-scattering reformulation, and Langevin/HMC or guided proposals.
- Cross-pixel mutations (paper §7), which need shift maps and MIS.
