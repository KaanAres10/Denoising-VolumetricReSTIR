# Metropolis–Hastings mutations at two bounces

**Date:** 2026-10-03
**Status:** design approved in chat; awaiting spec review
**Branch:** decorrelation
**Builds on:** `2026-09-27-restir-mcmc-decorrelation-design.md` (Phase B and V-B1–V-B10)

## Intent

The decorrelation study ran every scene at one bounce, and the mutation pass refuses more
(`VolumetricReSTIR::mutationsActive()` requires `mMaxBounces == 1`).

The paper's explosion (`run_LGHExplosion.py`) renders 2 bounces. Its look depends on the second
one, which lets the fire light the smoke. Checked side by side against the legacy build, the port's
`explosiondusk` scene matches the paper at 1 bounce in fire and sky, but its smoke is darker.

The user wants the mutations to work at 2 bounces, so the explosion and other scenes can be studied
in the paper's setup. Success is judged the same way as at one bounce:

1. **No bias added.** At 2 bounces, the 100-frame mean with 5 mutations matches the run without
   them, within chain-level error bars.
2. **Visibly fewer reuse blotches after the denoiser.** The same zoomed comparison as the
   one-bounce variety figures, at M cap 200, through OptiX and through DLSS Ray Reconstruction.

### Decided in chat

- **The mutations move the whole path:**
  - the existing moves, made bounce-aware;
  - new moves for the extra bounce: direction, distance, and a redraw.
- **First round:** the paper-look explosion plus four scenes where the second bounce matters:
  cathedral god rays, the backlit rim, the warm and cool panel lights, and the cloud at sunset.
  Each gets a 2-bounce reference and 0 vs 5 mutations through OptiX and RR.
- **Approach:** extend `MutateSamples.cs.slang` in place. The new moves live in their own include
  file, compiled only when `MAX_BOUNCES > 1`, so one-bounce output stays byte-identical.
- **A validation gate comes first.** Plain 2-bounce ReSTIR is checked against the legacy build and a
  2-bounce reference before any mutation code is trusted.
- **Order:**
  1. The current queue: the RR variety set, then the 1-bounce `explosiondusk` runs.
  2. A pause and rebuild. Never build while a study render runs.
  3. This work.
  4. The rest of the older queue: scene matrix rest, free-flight study, post, den2.
- **Vertex reuse stays off** (`mVertexReuse = false`, the default).

## What exists (read 2026-10-03)

- **A 2-bounce sample** (`Reservoir` plus `ExtraBounceReservoir`):
  - x1 lies at `depth` along the camera ray.
  - `sampledPixel` encodes the number of extra bounces (`decodeMaxIndirectBounces`) and a path tag
    (`decodePathTag`).
  - The extra bounce is entry `extraBounceStartId` of the per-pixel extra-bounce buffer.
- **The extra bounce is stored one of two ways**, depending on the path tag:
  - **Tag 0, scatter at x2:**
    - `wi_dist` holds a direction ω (as x, y and the sign of z; `encodeWiDist` / `decodeWiDist`)
      and the distance d from x1 to x2.
    - The light sample (`lightID`, `lightUV`) connects from x2.
    - p̂ is a density in dt1 · dω · dd · (light measure).
    - `wi_dist.w == kRayTMax` marks a surface x2. Distance is then not a coordinate: x2 is the first
      surface hit along ω.
  - **Tag 1, emission at x2:**
    - x2's world position is packed into `lightID` and `lightUV` (`encodeEmissivePosition`:
      `lightID = asint(z)`, `lightUV = xy`).
    - `evaluate_F_` multiplies by 1/d² (`ReSTIRHelper.slang:296` and the `isCurrentVertexEmissive`
      branch), so p̂ is a density in dt1 · dV(x2).
    - There is no light sample. `lightID` is NOT a light index for these paths.
- **Samples with no extra bounce** connect the light, or fire emission, at x1.
- **p̂** (`evaluate_P_hat`, `evaluate_F_`) already evaluates the full path, given an
  `ArrayDataProvider` for the extra-bounce entries. Visibility is cached per segment through
  `IExternalVisibilityProvider`:
  - index 0 is camera → x1;
  - index `bounceId + 1` is each later segment.
- **The mutation pass** already binds `gCurExtraBounceReservoirs`. It reads the extra-bounce entries
  through a `StructuredBufferArrayDataProvider` and caches only segment 0 (`CachingVisibilityProvider`).
- **`applicable()` treats `lightID < 0` as the environment light.** For a tag-1 path that test reads
  bits of x2's z coordinate. It is harmless today only because tag-1 paths cannot exist at one bounce.

## Design

### Step 0 — validation gate (no mutation code yet)

1. **A harness knob.** `VR_MAX_BOUNCES` sets `mMaxBounces` (vr_graph.py). A `_b<n>` label suffix sets
   it from `run_study.sh`'s `scene_env`, as `_g` and `_d` do.
2. **The port against the legacy build.** Render `explosiondusk` at 2 bounces in the port, and
   `run_LGHExplosion.py` as written (2 bounces) in the legacy build. Both at 960×540 with the same
   accumulation, both shown at exposure 1.
   - The sky must agree to 3 digits, as it does at 1 bounce.
   - The smoke and fire must agree visually and in the in-medium mean, within 2%.
3. **The reference renderer at 2 bounces.** Render a 2-bounce reference, and check that the port's
   plain 2-bounce ReSTIR (no mutations) matches its 100-frame mean within error bars
   (`bias_check.py`).

If either check fails, the cause is found and fixed before Step 1, using systematic debugging.
Recording the plain 2-bounce bias is part of this gate.

### Step 1 — the moves

The chain, the weight update (Eq. 16: `runningSum *= p0 / p_y_old`, `p_y = p̂(z)`), the invalid
reservoir guards and the fixed strategy probabilities are unchanged. Every new move preserves the
path's type and its number of extra bounces: no move changes dimension. A picked move that does not
apply to the current state is a self-transition, as now.

**Applicability, extended.** The path tag is read first.

- **Tag 1 (emission at x2):**
  - the light moves (`light`, `select`) do not apply;
  - the bounce moves act on the position x2.
- **Tag 0 with an extra bounce:**
  - the light moves act at x2;
  - the bounce moves act on (ω, d).
- **No extra bounce:** exactly as at one bounce.

**Existing moves, made bounce-aware:**

- **`depth` and `flight`** move t1 along the camera ray. They are unchanged, and x2 moves with x1
  because (ω, d) are relative to x1. A tag-1 x2 is an absolute position and does not move.
- **`light` (emissive torus step, environment rotation)** is unchanged. It acts on `lightUV`
  wherever the light connects.
- **`select` (weighted analytic re-selection)** evaluates its proposal weights at the vertex the
  light connects from: x2 when there is an extra bounce.

**New moves**, as strategy bits 4–6 (`direction`, `distance`, `rebounce` in `MUTATION_STRATEGIES`):

1. **`direction`:** a scattering perturbation at x1.
   - **Tag 0:** rotate ω by θ around itself, with uniform azimuth, θ drawn by `kelemenStep(gDirStepMin,
     gDirStepMax)` as the environment move does. The step is symmetric in solid angle, so acceptance
     is min(1, p̂(z)/p̂(x)).
   - **Tag 1:** a symmetric isotropic step of x2 in volume: a uniform direction times
     `depthUnit · kelemenStep(gDepthStepMin, gDepthStepMax)`. Acceptance is min(1, p̂(z)/p̂(x)), since
     p̂ is a density in dV for these paths.
2. **`distance`:** a propagation perturbation of the extra bounce. Tag 0 only.
   - d′ = d + `depthUnit · kelemenStep(gDepthStepMin, gDepthStepMax)`. Symmetric in dd, so acceptance
     is min(1, p̂(z)/p̂(x)).
   - d′ ≤ 0 has p̂ = 0 and is rejected.
3. **`rebounce`:** an independence proposal for the whole extra bounce.
   - **Proposal:** ω′ from the phase function at x1 (`mi.phaseFunction` sampling, wo = −camera
     direction). Then d′ from the renderer's free-flight distribution along ω′: q(d) = σ_t(x′) ·
     T(x1→x′). It is evaluated by `FreeFlightPdfAdapterGVDB` on the full ray, as the `flight` move
     does, with `gFlightMipLevel`.
   - **Tag 0:** q(ω, d) = phase(ω) · q(d). Acceptance min(1, p̂(z) q(x) / (p̂(x) q(z))).
   - **Tag 1:** the same draw gives x2′ = x1 + d′ ω′, with q_V = phase(ω′) · q(d′) / d′².
   - **A draw that leaves the medium without an event** has no x2. It counts as p̂ = 0 and is
     rejected, never redrawn, so the proposal density keeps its escape mass and stays exact.

**Surfaces.** A tag-0 sample whose x2 is a surface (`wi_dist.w == kRayTMax`) is not moved by
`direction`, `distance` or `rebounce`: self-transition. A proposal that puts x2 on a surface is
rejected. Both keep detailed balance:

- no transition enters or leaves the surface-x2 set;
- the kernel restricted to medium-x2 paths is reversible with respect to p̂.

The light moves on such a sample act as now. For the first round, surface x2 vertices are simply
not explored by the bounce moves.

**Stored precision.** ω is stored as (x, y, sign z), and z is recomputed by `decodeWiDist`. A proposal
is written with `encodeWiDist` and decoded again before p̂ is evaluated. p̂ always sees the stored
state, so the acceptance agrees with what is kept.

### Step 1 — pass mechanics

- **Proposed extra bounce.** A small `ArrayDataProvider` returns the proposal's `wi_dist` for this
  pixel's entry and the buffer for every other index. p̂(z) sees the proposed bounce without writing
  the buffer. On acceptance the entry is written back with the reservoir.
- **Visibility cache per segment** (`CachingVisibilityProvider` grows to `MAX_BOUNCES + 1` entries):
  - `light` and `select` change only the light, so they keep segments 0 and 1;
  - `direction`, `distance` and `rebounce` keep segment 0;
  - `depth` and `flight` move x1 and keep nothing.
- **Code layout.** The new moves and their q densities go in `BounceMoves.slang`, included by
  `MutateSamples.cs.slang` under `#if MAX_BOUNCES > 1`.
- **The guard.** `mutationsActive()` drops `mMaxBounces == 1` and keeps `!mVertexReuse`. The guard
  still rejects deterministic-tracking violations and reference mode.
- **Counters.** Stats are appended to `kMutationStatNames`, one each per new move: proposed,
  accepted, not applicable, rejected for a surface, escaped (`rebounce`). The host log prints
  acceptance by kind, as it does for the existing moves.

### Harness

- **`vr_graph.py`:**
  - the `VR_MAX_BOUNCES` knob;
  - the new strategy names;
  - `explosiondusk` keeps `mMaxBounces` at whatever the knob sets: 1 by default, 2 with `_b2`.
- **`run_study.sh`:** `_b<n>` in `scene_env`.
- **A new `run_two_bounce.sh`.** Per scene, with labels `explosiondusk_b2`, `bunnycathedral_d0.3_b2`,
  `bunnyback_g0.8_b2`, `bunnysoftbox_b2` and `wdassunset_g0.85_b2`:
  - a 2-bounce reference;
  - `noreuse`;
  - `den_optix_mut{0,5}cap200` and `den_rr_mut{0,5}cap200`, with
    `VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce` and `VR_MUT_AFTER_SPATIAL=1`.
- **Figures.** `variety_figures.py` and `gallery_figure.py` cover the `_b2` labels, with titles that
  say "2 bounces". `explosiondusk_b2` uses `--paper-display`.

### Tests

- **CPU** (`Scripts/tests/test_mutation_measures.py`), each with a Python copy of the shader math, as
  the existing environment and free-flight tests do:
  - the `direction` rotation is symmetric in solid angle: the histogram of x→z equals the one for
    z→x;
  - the tag-1 isotropic step is symmetric in volume;
  - `encodeWiDist` / `decodeWiDist` round-trip to within 1e-6 in angle away from the horizon. The
    measured error near |z| → 0 is recorded;
  - the `rebounce` density integrates to 1 − (escape probability) on an analytic homogeneous medium;
  - the acceptance ratios match the copies.
- **`test_vr_graph_study.py`:** the knob, the `_b2` label suffix and the strategy names.
- **GPU:**
  - byte-identity at 1 bounce with mutations off and with mutations on, before vs after the change
    (`mask_check.sh raw`, `verify.sh quick`);
  - 2 bounces with mutations off, byte-identical before vs after;
  - a 2-bounce smoke run in which every new move is accepted at a rate strictly between 0 and 1, and
    the not-applicable counters match the path-type mix.

### Bias gate

For each first-round scene at 2 bounces, `bias_check.py` compares `mut5` against `mut0` (chain-level
standard errors) and both against the 2-bounce reference. A difference beyond 3 standard errors
stops the round and is debugged before any figure is made.

## Risks

- **2-bounce ReSTIR in the port may itself be off.** It has never been exercised since the Falcor 9
  port. Step 0 exists for this.
- **`rebounce` acceptance may be tiny** in dense media, where the phase × free-flight proposal rarely
  lands near what p̂ favours. The direction and distance moves carry those scenes; the counters show
  it.
- **Cost.** Each p̂ evaluation now marches two segments plus a light connection. 5 mutations at
  2 bounces cost roughly 2–3× the 1-bounce pass. It is measured per pass, as before.
- **ω precision near the horizon.** It is bounded by the round-trip test, and p̂ is always evaluated
  on the stored state.

## Out of scope

- Vertex reuse (`mVertexReuse`): the stored vertex becomes a position past `vertexReuseStartBounce`.
- More than 2 bounces. The design generalises, but the round tests 2.
- Moving surface x2 vertices, and changing a path's type or its number of bounces (reversible jump).
- The older queue items, which resume after this round.

## Verification results

### V-C0 — plain 2-bounce ReSTIR (2026-10-03): matches the legacy build and the 2-bounce reference
- **Port vs legacy, explosion at 2 bounces, 960x540, 1024 frames.** The port's 2-bounce reference
  against the legacy build's `run_LGHExplosion.py` as written (ReSTIR, accumulated):
  - sky (top-left patch) identical: 0.0000 per channel;
  - explosion box +0.68% / +0.53% / +0.13% (R/G/B);
  - whole frame +0.51% / +0.29% / +0.04% (`compare_legacy.py`).
  - For scale: the port at 1 bounce against the same legacy image gives −36% in the box, so the
    comparison sees the second bounce.
  - Figure: `figs/explosion_b2_port_vs_legacy.png`.
- **`explosiondusk_b2` against its 2-bounce reference** (1080p, 2048 frames x 16 spp), 100-frame
  means from `m_corr`:
  - shipped reuse −0.35%;
  - no reuse +0.002%.
  - Reuse adds correlation as at one bounce: ρ̄(8) is 0.010 shipped against 0.000 with no reuse.
- **The chain-level `bias_check.py`** cannot run on pruned study runs (2 kept frames). The mutation
  bias gate uses dedicated unpruned runs (Task 5).

### V-C1 — mutations at 2 bounces are unbiased (2026-10-03)
- **Gate setup.** Dedicated unpruned runs, 480x270, M cap 200, 16 chains x 12 frames (warm 800). Each
  run is compared with plain reuse by `bias_check.py`; errors are 1 s.e. over chains.

  | scene | 5 moves of every kind (R / G / B) | 5 light moves only (R / G / B) |
  |---|---|---|
  | explosion | +3.03 / +1.82 / +0.14% (±1.43 / 0.97 / 0.32) | +0.76 / +0.51 / +0.17% (±1.30 / 0.82 / 0.29) |
  | cathedral | −0.99% (±0.96) | −0.10% (±0.88) |
  | backlit rim | +0.77% (±2.44) | −0.08% (±2.52) |
  | panel lights | −0.15 / −0.08 / −0.00% (±0.07 / 0.04 / 0.02) | −0.10 / −0.04 / +0.02% (±0.08 / 0.05 / 0.03) |
  | sunset | −0.04 / −0.04 / −0.09% (±0.34 / 0.26 / 0.24) | +0.13 / +0.05 / −0.10% (±0.41 / 0.30 / 0.25) |

  All are within 3 s.e.
- **The explosion, sharper.** Its all-moves R/G sat near 2 s.e., so it was rerun with 64 chains and
  each move kind alone (`run_b2_bias_explosion.sh`):

  | moves | R / G / B against plain reuse |
  |---|---|
  | existing moves | −0.01 / −0.01 / +0.01% |
  | direction | +0.53 / +0.32 / +0.02% |
  | distance | +0.42 / +0.02 / −0.08% |
  | rebounce | +1.30 / +0.97 / +0.34% (±0.75 / 0.49 / 0.15) |
  | all | +0.88 / +0.54 / +0.10% (±0.67 / 0.46 / 0.16) |

- **Rebounce alone, at ~2 s.e., was traced:**
  - **The proposal's own density is right.** The q evaluator against the sampler's density on these
    rays, which start inside the medium (new stats 59–62): 2 of 15.8M proposals differ by more than
    1e-3, which is float rounding.
  - **Amplification does not grow it.** 20 rebounces per pixel instead of 5 read
    +0.84 / +0.56 / +0.17% (±0.69 / 0.45 / 0.15), smaller rather than larger. A biased kernel moves
    further from p̂ with more steps.
  - **The deviation is shared.** Every mutated configuration compared with that baseline reads
    slightly positive, which points to the baseline's own fluctuation, not a move.
- **Acceptance** (direction / distance / rebounce):

  | scene | direction | distance | rebounce |
  |---|---|---|---|
  | explosion | 0.40 | 0.41 | 0.13 |
  | cathedral | 0.81 | 0.66 | 0.08 |
  | backlit rim | 0.70 | 0.56 | 0.03 |
  | panel lights | 0.81 | 0.55 | 0.12 |
  | sunset | 0.93 | 0.50 | 0.24 |

  Rebounce is rare under strong forward scattering, where the local moves carry the scene, as the spec
  expected.

### V-C2 — what a viewer sees at 2 bounces: mutations cut the denoised error 45–89% (2026-10-06)
- **Setup.** M cap 200, 0 vs 5 moves of every kind after spatial reuse, no decoupled history. Error is
  the in-medium clipped relMSE after the denoiser, averaged over the kept first frames of 2
  independent chains (`run_two_bounce.sh`).
  - The explosion's pairs ran with 10 chains, the other four with 4 (K = 40): at 2 bounces the
    cathedral's chain is ~21 min at 1080p.

  | scene | 1 bounce, OptiX | 1 bounce, RR | 2 bounces, OptiX | 2 bounces, RR |
  |---|---|---|---|---|
  | explosion (paper setup) | 0.0418 → 0.0100 (−76%) | 0.0336 → 0.0034 (−90%) | 0.0612 → 0.0144 (−76%) | 0.0619 → 0.0122 (−80%) |
  | cathedral god rays | 0.0141 → 0.0027 (−81%) | 0.0118 → 0.0010 (−91%) | 0.0165 → 0.0030 (−82%) | 0.0113 → 0.0012 (−89%) |
  | backlit rim | 0.0668 → 0.0168 (−75%) | 0.0602 → 0.0097 (−84%) | 0.0870 → 0.0316 (−64%) | 0.0798 → 0.0291 (−64%) |
  | panel lights | 0.0472 → 0.0089 (−81%) | 0.0427 → 0.0048 (−89%) | 0.0546 → 0.0105 (−81%) | 0.0489 → 0.0064 (−87%) |
  | sunset cloud | 0.0503 → 0.0251 (−50%) | 0.0567 → 0.0227 (−60%) | 0.0639 → 0.0244 (−62%) | 0.0503 → 0.0275 (−45%) |

- **Figures.**
  - `figs/variety_<label>_b2.png` and `figs/variety_rr_<label>_b2.png`;
  - `figs/gallery_mutations_b2{,_rr}.png`;
  - `figs/explosion_b2_port_vs_legacy.png`.
- **Findings.**
  - The gain carries over to 2 bounces.
  - It is smaller on the backlit rim (g = 0.8), where the rebounce is accepted 3% of the time and
    x2 moves only by small steps.
  - The cathedral's walls, lit at 2 bounces by light scattered from the dust, keep their reuse streaks
    in both runs: a pixel whose camera ray hits a surface first is not moved (out of scope, see
    above). That is the next target.

### V-C1b — the explosion's rebounce, settled with independent seeds and a reference (2026-10-06, final review)
- **What the final review found** in V-C1's gate:
  - every configuration used the same chain seeds (`VR_SEED_BASE + i × 10000`);
  - `bias_check.py` used unpaired error bars;
  - the 64-chain run contained the 16-chain run's chains;
  - no configuration was compared with a reference.
- **The rerun** (`run_b2_bias_paired.sh`):
  - fresh seeds, `VR_SEED_BASE=1000000`, clear of the earlier 100000–730000;
  - a converged 480x270 reference of the same pose (8192 frames x 16 spp);
  - 64 chains x 12 frames, M cap 200;
  - read with `bias_check.py --paired --ref`. Chain means are in `b2bias_paired/explosiondusk_b2/chains.json`.

  | explosion, 2 bounces | vs plain reuse, paired (R / G / B) | vs reference (R / G / B) |
  |---|---|---|
  | plain reuse | — | −0.10 / −0.06 / +0.05% (±0.68 / 0.41 / 0.14) |
  | rebounce only | −0.13 / −0.03 / −0.02% (±0.82 / 0.55 / 0.19) | −0.24 / −0.09 / +0.02% (±0.55 / 0.37 / 0.10) |
  | all moves | +0.50 / +0.24 / −0.09% (±0.94 / 0.63 / 0.20) | +0.40 / +0.18 / −0.05% (±0.58 / 0.41 / 0.11) |

- **Verdict.** Every value is within 1 s.e. of plain reuse and of the reference. V-C1's +1.30 / +0.97 /
  +0.34% for rebounce belonged to that seed set. Pairing barely narrows the error bars here (unpaired:
  ±0.87 / 0.55 / 0.17%): the mutation pass draws its own random numbers, so the chains diverge from the
  baseline's within the 800 warm-up frames.

### V-C3 — cost and equal time: the mutations win at equal time at M cap 200 (2026-10-07)
- **Cost** (`run_cost.sh`, `cost_table.py`). Median GPU ms per frame of the VolumetricReSTIR pass at 1080p, M cap 200,
  before the denoiser, stats off; 5 moves of every kind (4 at 1 bounce, 7 at 2), with the code at 3c0456b.

  | scene | bounces | plain | 1 mutation | 5 mutations | 5 mutations cost as much as |
  |---|---|---|---|---|---|
  | explosion (paper setup) | 1 / 2 | 55.6 / 79.8 ms | +12 / +22% | +71 / +114% | 21 / 32 initial candidates |
  | cathedral god rays | 1 / 2 | 72.4 / 561 ms | +20 / +11% | +79 / +34% | 18 / 13 |
  | backlit rim | 1 / 2 | 62.9 / 102 ms | +26 / +50% | +120 / +217% | 61 / 74 |
  | panel lights | 1 / 2 | 79.3 / 129 ms | +38 / +38% | +140 / +167% | 35 / 28 |
  | sunset cloud | 1 / 2 | 93.8 / 142 ms | +37 / +41% | +129 / +135% | 36 / 29 |

  - The shipped count is 4 initial candidates; above 32 the count is extrapolated linearly.
  - The paper's Table 1 reports +21 to +129% for 5 mutations.
  - One step costs as much as 4 to 11 initial candidates. It evaluates the reuse target (mip 1, full step, no Russian
    roulette), and before V-C4 a warp ran every move its pixels picked.
- **Equal time** (`run_equal_time.sh`, `equal_time_table.py`): plain ReSTIR given the 5 mutations' time as initial
  candidates, through OptiX, same chains, seeds and kept frames as V-C2's pairs; in-medium relMSE.

  | scene | plain | + 5 mutations | plain, equal time |
  |---|---|---|---|
  | explosion, 1 / 2 bounces | 0.0418 / 0.0612 | −76 / −76% | −16 / +4% (21 / 32 candidates) |
  | cathedral | 0.0141 / 0.0165 | −81 / −82% | −21 / +4% (19 / 13) |
  | backlit rim | 0.0668 / 0.0870 | −75 / −64% | −6 / +4% (61 / 74) |
  | panel lights | 0.0472 / 0.0546 | −81 / −81% | +1 / −10% (35 / 28) |
  | sunset cloud | 0.0503 / 0.0639 | −50 / −62% | +16 / +6% (35 / 29) |

  - At M cap 200 more candidates do not reach the correlation; on bistro at its shipped cap they won (V-B5 of the
    decorrelation spec).
  - The equal-time runs time their chosen count right after a 20-minute render, while that render is scored. The
    first five of those checks read 20–50% high, which gave plain ReSTIR more time than the mutations, not less.
- **Caveat: the long history.** Both arms run at M cap 200; the shipped cap is 4. At the shipped cap plain ReSTIR is
  already as good as cap 200 + 5 mutations on the cathedral, panel lights and sunset (in-medium relMSE 0.0022 vs
  0.0027, 0.0082 vs 0.0089, 0.0117 vs 0.0251), and 5 mutations there cut 3–26%. Most of the −50..−82% is mutations
  undoing what the 200-frame history does; cap 200 + mutations wins outright only with many lights (lanterns 0.0199
  vs 0.0246, concert 0.0175 vs 0.0254).

### V-C4 — the mutation pass made 2.5–4.1x faster (2026-10-07)
- **Cause.** Each pixel drew its move at random, and each move ran its own marches (four p̂ call sites at 2 bounces,
  plus the proposals' own marches: free-flight sampling, light sampling, rebounce). A warp ran every move its pixels
  picked, one after another.
- **Stage 1, exact** (8e64a78). Every move only builds its proposal (and an independence move's q terms; 1 for the
  symmetric ones), then one shared p̂(z) and acceptance test. Same arithmetic, same random-number order. The
  rebounce's q(x) is cached as the free flight's already was.
- **Stage 2, the same chain in law** (2af014f, `mMutationCoherentMoves` / `VR_MUT_COHERENT=1`, off by default). Each
  step's move kind is drawn from a stream every pixel shares, so a warp runs one move per step. A re-selection that
  draws x's own light (with one light, every one) is a self-transition and skips p̂; its random number is still drawn.
  The default since 2026-10-07 (user's request): with no setting a run renders Stage 2's frames bit for bit; `VR_MUT_COHERENT=0`
  (`run_study.sh STUDY_MUT_COHERENT=0` for a whole study) renders Stage 1's, for studies begun before.
- **A/B** (`run_speed_ab.sh`, `speed_ab_check.py`). One binary, the runtime shader copy swapped, A B B A per setup,
  1080p, M cap 200, 5 mutations of every kind. Mutate Samples ms, and its cost relative to the rest of the frame:

  | scene | before | Stage 1 | Stage 2 (coherent) |
  |---|---|---|---|
  | explosion, 1 / 2 bounces | 48.6 / 76.4 (+95 / +111%) | 43.9 / 55.2 | 18.5 / 18.7 (+36 / +29%) |
  | cathedral | 59.9 / 184 (+87 / +33%) | 48.9 / 146 | 18.3 / 55.0 (+25 / +10%) |
  | backlit rim | 72.7 / 177 (+120 / +166%) | 65.5 / 135 | 20.4 / 43.1 (+34 / +40%) |
  | panel lights | 112 / 178 (+146 / +134%) | 96.0 / 145 | 41.4 / 55.5 (+52 / +41%) |
  | sunset cloud | 118 / 170 (+125 / +133%) | 109 / 140 | 48.1 / 54.9 (+51 / +37%) |

- **Verification.**
  - Stage 1: 40/40 frames bit-identical to the code before it; repeated old runs are bit-identical too.
  - Stage 2 off: 40/40 frames bit-identical to Stage 1, so the skip is exact.
  - Stage 2 on, bias (`run_coherent_quality.sh`, V-C1b's 64 chains and seeds, `bias_check.py --saved`): −0.56 /
    −0.39 / −0.12% vs plain (±0.85 / 0.58 / 0.18), −0.66 / −0.45 / −0.07% vs the reference (±0.52 / 0.36 / 0.11).
  - Stage 2 on, quality: V-C2's runs with the switch on, `equal_time_table.py --configs`. In-medium relMSE within the
    2-frame noise of the per-pixel runs on 9/10 setups (sunset at 2 bounces 0.0350 vs 0.0244: one kept frame catches a
    transient dark patch); m_corr's all-frame relMSE equal or lower on 10/10 (sunset 2 bounces 0.0079 vs 0.0091);
    ρ̄(8) unchanged. `figs/coherent_*.png` compare one frame of each.

### V-C5 — after the speed-up: early rejection kept, one-move programs not (2026-10-07)
- **Where Stage 2's time goes** (`run_move_cost.sh`, `move_cost_table.py`; one kind alone, frame-wide, ms per step at
  1080p): re-selection, free flight and rebounce are the dear moves (panel lights at 2 bounces 15.0, 11.5 and 13.6;
  light, depth, direction, distance 6.2–7.8), plus a fixed ~7.5 ms for p̂(x0). They are also the most rejected (3–41%
  accepted).
- **A, early rejection** (64fb0b2, `mMutationEarlyReject` / `VR_MUT_EARLY_REJECT`, on by default). The test's random
  number is drawn before p̂ (which draws none), giving what p̂(z) must exceed, u p̂(x) q(z) / q(x). The light's
  unoccluded term is known before the shadow march and the transmittance only shrinks along it, so the march stops,
  returning 0, once their product is below that (less a 1e-4 margin for the full product's rounding), or is skipped
  when the unoccluded term already is. Compiled into the mutation program alone (`VR_EARLY_REJECT`).
  - Exact: on vs off 40/40 frames bit-identical, off vs Stage 2 40/40, plain ReSTIR vs before 12/12
    (`run_speed_stageA.sh`). The first build read an uninitialized threshold (a declared default is not applied to
    a local adapter) and differed run to run; fixed by setting it in `InitializeValues`.
  - Mutate Samples: explosion −24 / −11% (1 / 2 bounces), sunset −29 / −17%, panel lights −15 / −16%; the backlit
    rim −3 / −4% and the cathedral −3 / 0%, whose single light sits outside the medium (short shadow marches).
- **B, one program per move** (`run_speed_probeB.sh`, `VR_MUT_STATIC_MASK`): each kind in a program compiled for it
  alone vs the full one, frames bit-identical, Mutate Samples −1 to −11% (mean ~5%), the frame unchanged within the
  timing noise. A dispatch per step with the chain's state kept in a buffer between them would cost about that, so B
  is not built; the define stays for the probe.
- **C, fewer mutations** (`run_fewer_mutations.sh`, `count_gallery.py` -> `figs/count_gallery.png`): 1, 3 and 5
  mutations with A and Stage 2, timed (A B B A) and rendered through OptiX like V-C2's runs (same chains and kept
  frames). All-frame relMSE (m_corr, whole image) and the whole pass per frame:

  | scene, 1 / 2 bounces | plain | 1 mutation | 3 mutations | 5 mutations |
  |---|---|---|---|---|
  | explosion | 0.0262 / 0.0332 | 0.0127 / 0.0134 | 0.0112 / 0.0109 | 0.0100 / 0.0102 |
  | cathedral | 0.0040 / 0.0248 | 0.0014 / 0.0179 | 0.0011 / 0.0175 | 0.0010 / 0.0171 |
  | backlit rim | 0.0057 / 0.0119 | 0.0022 / 0.0057 | 0.0018 / 0.0042 | 0.0017 / 0.0040 |
  | sunset | 0.0189 / 0.0257 | 0.0071 / 0.0107 | 0.0066 / 0.0083 | 0.0060 / 0.0079 |
  | frame time (range over the 10 setups) | | −3..−22% of 5's | −3..−14% of 5's | 59–629 ms |

  (The panel lights' whole-image relMSE is the denoiser's soft emitter edges for every config; in the medium it is
  0.0472 / 0.0126 / 0.0088 / 0.0089 at 1 bounce.) Three mutations are within 2–12% of five's error, one is 18–43% worse
  (its streaks show on the cathedral and at 2 bounces); every count keeps most of the cut against plain ReSTIR.
