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

None yet. Phase A results are recorded here as V1…Vn, each confirmed or dismissed, as in the earlier
specs.

## Out of scope

- Multi-bounce mutations (round 2) and vertex-reuse mode.
- Changing any default. Mutations and `VR_SR_PER_PIXEL_OFFSETS` stay opt-in.
- Ghost ReSTIR's null-scattering reformulation, and Langevin/HMC or guided proposals.
- Cross-pixel mutations (paper §7), which need shift maps and MIS.
