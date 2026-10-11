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

### V-C6 — why the shipped pass is unbiased (2026-10-08)
The pass as it ships: 5 steps after spatial reuse, coherent move choice (Stage 2), early rejection (A), all seven
moves at 2 bounces (four at 1).

1. **ReSTIR's guarantee (the input).** After spatial reuse a pixel holds x0 with W0 = runningSum / (p_y M), and for
   every f that vanishes outside supp p̂: E[f(x0) W0] = ∫ f (Lin et al. 2021; Talbot MIS). The mutation pass draws its
   own random numbers, so given x0 its moves are independent of W0.
2. **Eq. 16 needs only invariance.** Let K be any kernel with ∫ p̂(x) K(x, z) dx = p̂(z) that never moves to p̂ = 0,
   and set W(z) = W0 p̂(x0) / p̂(z). With h(x) = p̂(x) ∫ K(x, z) f(z) / p̂(z) dz (zero outside supp p̂):
   E[f(z) W(z)] = E[W0 h(x0)] = ∫ h = ∫ f(z) / p̂(z) [∫ p̂(x) K(x, z) dx] dz = ∫ f.
3. **Every step leaves p̂ invariant** (detailed balance in the measure p̂ is a density in):
   - symmetric moves (light u on the torus, env and ω rotations, depth and distance steps, the x2 step in volume)
     accept with min(1, p̂(z)/p̂(x)); their symmetry is checked numerically in `test_mutation_measures.py`;
   - independence moves (re-selection, free flight, rebounce) propose z ~ q independently of x and accept with
     min(1, p̂(z) q(x) / (p̂(x) q(z))), q(x) and q(z) from the same evaluator; an escape (no proposal) has a probability
     that does not depend on x and is a self-transition;
   - a proposal with p̂(z) = 0 is rejected, never redrawn; an inapplicable kind is a self-transition, and no move
     changes a sample so that the reverse move becomes inapplicable;
   - the kind is drawn with fixed probabilities independent of the state. With coherent moves the draw is shared by
     all pixels, but given it each pixel applies a fixed sequence of p̂-invariant steps, which is p̂-invariant; 2 holds
     for every sequence, so for their mixture.
4. **The implementation is that kernel.** Stage 1 kept the arithmetic (bit-identical). Early rejection stops a
   march only when p̂(z) ≤ (unoccluded term) × (transmittance so far) < u p̂(x) q(z)/q(x) (1 − 1e-4), so it rejects
   only what the full value rejects (bit-identical). The skipped re-selection has z = x (bit-identical). The
   write-back runningSum ← runningSum p̂(x0)/p_y, p_y ← p̂(z) is W(z) = W0 p̂(x0)/p̂(z) with p̂(x0) recomputed.
5. **Downstream.** The mutated reservoir is an unbiased contribution weight for its sample: shading f(z) W(z) is
   unbiased, and reusing it next frame is what ReSTIR's reuse assumes of its inputs.

What the argument assumes rather than proves: W0 unbiased over all of supp p̂ (the candidates' coverage, a property
of the plain pipeline), a deterministic p̂ (the host allows mutations only with ray marching or analytic tracking),
and floating point (ties within the 1e-4 margin or 1e-7 rounding). Tests so far: V-B1, V-B9/10 (one bounce),
V-C1, V-C1b (two bounces), Stage 2's paired explosion test (V-C4); the shipped pass on all ten setups:
`run_bias_final.sh` (results below).

**Results (2026-10-09, `bias_summary.py outputs/decorr/biasfinal`).** The shipped pass (coherent moves, early
rejection, 5 mutations of every kind after spatial reuse) against plain ReSTIR, M cap 200, 480x270, 64 seed-paired
chains x 12 frames after 800 warm-up frames, seeds from 2000000, statistics off. Luminance bias, 1 s.e. over chains:

| Setup | 1 bounce | z | 2 bounces | z |
|---|---|---|---|---|
| explosiondusk | -0.06% +- 0.44% | -0.15 | +0.33% +- 0.60% | +0.55 |
| bunnycathedral_d0.3 | -0.10% +- 0.61% | -0.17 | +0.04% +- 0.45% | +0.08 |
| bunnyback_g0.8 | -0.72% +- 1.25% | -0.57 | -0.66% +- 1.97% | -0.33 |
| bunnysoftbox | -0.02% +- 0.02% | -1.35 | +0.04% +- 0.03% | +1.56 |
| wdassunset_g0.85 | -0.19% +- 0.11% | -1.80 | -0.09% +- 0.13% | -0.69 |

Largest |z| 1.80, none beyond 2; the ten z's give chi-square 8.77 on 10 degrees of freedom, p = 0.55: no bias
detected. The tests' reach differs by setup: a +1% bias would have shown at z = 50 on the soft box (1 bounce) and z = 9
on the sunset, but only z = 0.5-0.8 on the backlit rim, whose chains are too noisy to see 1%. Per-channel z's are all
within 2 except the soft box's blue at 1 bounce (-2.0), with its luminance at -1.35. The queue was cut off once,
during the 2-bounce soft box's mutated capture; `run_bias_final.sh` now keeps a capture that finished (all 768
frames, no errors), so the rerun reused its plain capture.

### V-C7 — scenes where one mutation is not enough (2026-10-10)

The user: "one mutation is enough; create scenes where multiple mutations are required to get rid of significant
artifacts". On the first-round scenes one step already breaks most duplicates (V-C5 C: 3 mutations within 2-12% of 5).
A pixel stops sharing its neighbours' artifact only when a step changes what it shows, so a count matters where that
chance per step is small: (1) a target sharply peaked against the step (most proposals rejected); (2) an artifact
carried by a choice only one rare move changes (which coloured light: re-selection is the move in about one step in
four under the coherent choice, and accepts rarely among many lights); (3) a long correlation length (M cap 200).
Judged mainly at M cap 200 (user's choice), the pass as shipped, 960x540, run_study.sh's capture (100 frames per
config). Scenes (`Scripts/scenes/`, b81b723): **bunnyswarm** (192 point lights of six shuffled hue families in a jittered
grid through the cloud, density x3), **bunnybeam** (one 1.4-degree beam), **bunnypinback** (one light hidden behind the
cloud on the camera axis, g = 0.97, 1 and 2 bounces), **bunnyclosebox** (24 x 24 warm and cool panels 2 units from the
cloud, 2 bounces). `run_counts.sh` (smoke, pilot, fill, ship, optix), `count_curve.py`, `counts_figures.py` ->
`figs/mutation_counts_{curve,gallery,optix}.png`.

**Raw frames, M cap 200** (rho(8): medium; colour for the coloured scenes; duplicates per 20x20 tile):

| scene | 0 | 1 | 2 | 3 | 5 | 10 | 20 | one leaves, vs 20 |
|---|---|---|---|---|---|---|---|---|
| swarm, colour | 0.0612 | 0.0157 | 0.0104 | 0.0078 | 0.0057 | 0.0033 | 0.0018 | 8.9x |
| swarm, medium | 0.0776 | 0.0319 | 0.0262 | 0.0226 | 0.0203 | 0.0169 | 0.0178 | 1.8x |
| swarm, duplicates | 67.5 | 21.1 | 11.9 | 7.4 | 3.4 | 0.8 | 0.15 | |
| close panels b2, colour | 0.0304 | 0.0168 | 0.0155 | 0.0124 | 0.0103 | 0.0066 | 0.0056 | 3.0x |
| close panels b2, medium | 0.0856 | 0.0365 | 0.0295 | 0.0275 | 0.0229 | 0.0204 | 0.0225 | 1.6x |
| hidden backlight, medium | 0.1410 | 0.0869 | 0.0775 | 0.0719 | 0.0665 | 0.0583 | 0.0557 | 1.6x |
| hidden backlight b2, medium | 0.1594 | 0.1336 | 0.1188 | 0.1164 | 0.1126 | 0.1030 | 0.0997 | 1.3x |
| beam, medium | 0.0808 | 0.0089 | 0.0145 | 0.0126 | 0.0101 | 0.0150 | 0.0022 | (noise) |

Light re-selection accepts 17% on the swarm. The beam lights only 390 medium pixels, so its CIs (m1: -0.004..0.024)
are wider than the effect: one mutation already takes it to noise level, and it is left out of the OptiX stage.

**Through OptiX, M cap 200, against a path-traced reference** (2048 x 16 spp; relMSE in the medium, clipped at its
brightest 0.5%, mean over the two kept frames, so rough):

| scene | no reuse | 0 | 1 | 3 | 10 | one vs ten |
|---|---|---|---|---|---|---|
| large close panels, 2 bounces | 0.023 | 0.127 | 0.062 | 0.048 | 0.034 | +82% |
| hidden backlight, 2 bounces | 0.079 | 0.196 | 0.094 | 0.084 | 0.071 | +32% |
| 192 coloured lights, dense (fixed reference) | 0.331 | 0.216 | 0.071 | 0.055 | 0.050 | +41% |
| hidden backlight | 0.027 | 0.101 | 0.040 | 0.041 | 0.031 | +28% |

One mutation is 28-82% worse than ten after the denoiser on all four, and the strip shows why: plain ReSTIR's blotches
become wormy streaks after one mutation (close panels) or colour streaks (swarm) and fade with the count.

**The swarm's reference was wrong** (user: "is the top reference correct?"): a sharp-edged orange bar in both its captures
(1024 and 2048 frames), and in bunnylanterns' 1080p reference a large cyan wedge next to a lantern, both absent from
every ReSTIR frame. The reference path tracer (`VolumePathTracingFunctions.slang`) estimated shadow rays by residual
ratio tracking, whose control and majorant come from each GVDB brick's stored density bounds; ReSTIR's shading uses
analytic tracking, which reads no bounds. One-variable A/B at 640x360, 512 frames: with global-majorant ratio tracking
the wedge is gone (its box -36%, the lit image -2%); residual vs ratio, lit pixels >25% too bright: lanterns 5.2%, swarm
2.6% (patches), the hidden backlight (light outside the cloud) 0.0% and identical. Fixed in a2a3aa8 (both NEE calls use
ratio tracking; the built shader renders bit-identically to the A/B). Only references with lights INSIDE the medium
were affected (bunnylanterns, bunnyswarm); the first-round scenes' and the bias suite's results stand (the bias suite
compares against plain ReSTIR). The swarm's reference is re-rendered (its old one kept as ref_residual); bunnylanterns'
V-B10 relMSE numbers used the old one. Not yet tested the same way: the reference's free-path sampling (decomposition
tracking) also uses the brick bounds.

**Why the swarm and the close panels keep artifacts after 10 mutations** (`run_swarm_dig.sh`, `run_dig2.sh`; OptiX, M cap
200, relMSE in the medium against the fixed references):

| config | swarm | close panels b2 |
|---|---|---|
| 10 mutations | 0.0499 | 0.0337 |
| 20 mutations | 0.0489 | |
| 10 mutations, 16 initial candidates | 0.0489 | |
| decoupled history, no mutations | **0.0273** | **0.0091** |
| decoupled history + 10 mutations | 0.0283 | 0.0091 |

More mutations stop helping past ~10 and more candidates do not help (so not plain variance); keeping spatial reuse's
output out of the history removes 45% (swarm) and 73% (close panels, below no reuse's 0.0229) of what 10 mutations leave,
and mutations add nothing on top. What outlasts the mutations is the one thing they cannot change: Eq. 16 keeps each
reservoir's normalization c_hat = runningSum/M, and a pixel's estimate is (f/p_hat)(X) c_hat with p_hat close to f's
luminance, so a pixel's BRIGHTNESS is mostly c_hat. With a coupled history spatial reuse's output (neighbours' reservoirs
mixed in) is the next frame's history, so over a 200-frame history neighbouring pixels' c_hat becomes one shared, blotchy
field. Evidence (raw, M cap 200): colour rho(8) falls 97% with 20 mutations but luminance stalls at 0.017 from 10 on;
the decoupled history reaches 0.0005 WITHOUT mutations although its tiles share the same light as often (114 per tile,
as with 10 or 20 mutations; no reuse 76: the target's own preference for the nearest light, not an artifact) and hold
more exact duplicates (18 vs 0.8). Directly (`chat_maps.py`; a diagnostic runtime-shader copy wrote c_hat into the sample
identity, `run_chatz.sh`): split against the reference, 97-98% of the brightness error's blotch variance (2-24 px, in the
medium) is in c_hat for every config, and that variance is 0.89 plain, 0.59 after 10 mutations (they act on c_hat only
indirectly, through the samples later reuse weighs), 0.30 decoupled (mostly independent noise there). Map:
`figs/swarm_chat_maps.png` -- the blotches left after 10 mutations sit exactly where c_hat's are. (An earlier reading of
the light-sharing count as the cause was wrong.)

**Through DLSS Ray Reconstruction** (`run_rr_swarm.sh`; `chat_maps.py` -> `figs/swarm_denoised_maps.png`, raw / OptiX / RR
and their error maps). relMSE in the medium, and the kept frames' mean brightness in the medium over the reference's:

| swarm, M cap 200 | OptiX relMSE | OptiX mean | RR relMSE | RR mean |
|---|---|---|---|---|
| no reuse | 0.331 | 0.75-0.82 | 0.254 | 0.70-0.71 |
| plain ReSTIR | 0.216 | 0.95-0.96 | 0.201 | 0.69-0.72 |
| 10 mutations | 0.050 | 0.96-0.98 | 0.156 | 0.77-1.00 |
| decoupled history | 0.027 | 0.97 | 0.493 | 0.32-0.33 |
| decoupled + 10 | 0.028 | | 0.481 | 0.33-0.34 |

RR darkens every input here, and the decoupled history's by two thirds, with horizontal streaks; with its darkening
divided out it still leaves large patches there, while 10 mutations give RR its most even result. OptiX keeps the mean
within 3-5% for every reuse configuration. So RR's ranking is RR's own behaviour on this input, not the inputs' quality
(the raw frames: lag-1 spatial autocorrelation 0.27 plain, 0.039 after 10 mutations, 0.004 decoupled, 0 no reuse). Not
yet tested: whether RR's temporal accumulation rejects the decoupled input's frame-to-frame changes (a burst run), or a
guide buffer disagrees with the shaded reservoir when the history is decoupled.

**The count through both denoisers, up to 64** (the UI maximum; `run_counts_rr.sh`, `figs/swarm_counts_denoisers{,_curve}.png`;
relMSE in the medium, mean brightness over the reference's):

| swarm, M cap 200 | 0 | 1 | 3 | 10 | 20 | 64 |
|---|---|---|---|---|---|---|
| OptiX | 0.216 | 0.071 | 0.055 | 0.050 | 0.049 | 0.045 |
| RR | 0.201 (0.72x) | 0.128 (0.86x) | 0.096 (0.75x) | 0.156 (1.00x) | 0.100 (0.81x) | 0.119 (0.93x) |
| raw rho(8), luminance / colour | 0.078 / 0.061 | 0.032 / 0.016 | 0.023 / 0.0078 | 0.017 / 0.0033 | 0.018 / 0.0018 | 0.018 / 0.0006 |

OptiX falls monotonically, most of it by 3, with little after 10 (64: -9% on 10). RR's numbers are dominated by its
overall brightness, which swings 0.72-1.00x between kept frames, so they do not rank the counts; with its darkening
divided out its error maps grow more even with the count like OptiX's. In the raw frames the colour keeps decorrelating
to 64 (0.0006, duplicates 0.03 per tile) while the luminance stays at 0.018 from 10 on: c_hat, as above. (The close panels' raw duplicates that stay at ~41 per tile are pixels seeing the panels or the
background; in medium tiles they fall 223 -> 1.4.) So at a long history the decoupled history, not more mutations, is
the remedy, as V-B9/V-B10 found on Phase B's scenes. On the close
panels and the hidden backlight even ten mutations stay above no reuse at all: at a 200-frame history these artifacts
outlast ten steps. At the shipped cap the effect is small: rho(8) 0.004-0.10 without mutations, five mutations cut it
3-14% except the swarm's colour (-48%; one mutation takes 37% of that) and the beam (-44%, noisy). So the count matters
with a long history and a hard-to-change choice, which is where the long history is wanted for its low noise.

**Real-world shots** (user: "a scene representative of movies or real life where mutation, or multiple mutations,
matters; run OptiX and RR on it; multiple different scenes"; d0a1145, `run_film.sh`, `film_figures.py` ->
`figs/film_<label>.png`, `figs/film_summary.png`): a concert lighting rig in stage haze (**plumerig_g0.6**, 46 coloured
fixtures), an LED video wall behind thin haze (**plumewall_g0.6_d0.3**, 32 emissive tiles), a night thunderstorm
(**wdasstorm_g0.5**, six lightning lights inside the cumulus, city lights below), a neon street in fog
(**emeraldneon_d3**, 40 signs). M cap 200, the pass as shipped, 960x540, the Look configuration; relMSE in the medium
(equal_time_table's), mean of the two kept frames (separate chains; the figures give their range). The reference's own
noise, its 1024-frame accumulation against its 2048-frame one (their difference has the 2048-frame mean's variance, so
this is what each score carries from the reference): 0.0008, 0.0001, 0.0010 and **0.016** -- over half of every neon
score.

| shot | denoiser | no reuse | 0 | 1 | 3 | 10 | one vs ten |
|---|---|---|---|---|---|---|---|
| concert rig | OptiX | 0.100 | 0.067 | 0.020 | 0.017 | 0.017 | +20% |
| | RR | 0.024 | 0.067 | 0.023 | 0.018 | 0.017 | +36% |
| LED wall | OptiX | 0.053 | 0.042 | 0.024 | 0.028 | 0.025 | -4% |
| | RR | 0.025 | 0.036 | 0.028 | 0.032 | 0.029 | -2% |
| thunderstorm | OptiX | 0.104 | 0.108 | 0.037 | 0.030 | 0.025 | +48% |
| | RR | 0.021 | 0.090 | 0.027 | 0.025 | 0.019 | +39% |
| neon street | OptiX | 0.265 | 0.064 | 0.031 | 0.031 | 0.028 | +8% |
| | RR | 0.104 | 0.052 | 0.035 | 0.026 | 0.027 | +26% |

One mutation is where most of the gain is in every shot: it removes 42-70% of plain ReSTIR's OptiX error and 20-70% of
its RR error. More than one: the **thunderstorm** keeps paying to 10 (OptiX -33% and RR -28% on one mutation, falling
at every step in both kept frames); like the swarm, its lights sit inside a dense cloud. The **concert rig** gains at 3
(-16% OptiX, -22% RR, in both frames) and nothing after. The **LED wall** (area lights behind the haze) needs one: 3 and
10 are no better, 3 above 1 in both frames. The **neon street** cannot rank the counts after denoising until its
reference is longer (the frames' ranges overlap and 0.016 of each score is the reference's). In the raw frames all four
pass count_curve's "needs more than one": the colour rho(8) one mutation leaves is 7.1x / 4.0x / 3.9x / 3.0x what ten
leave (luminance 1.9x / 1.2x / 1.8x / 2.1x), but only the storm's and the rig's survive a denoiser.

Through RR plain ReSTIR is the worst input in all four shots (0.036-0.090), worse than no reuse (0.021-0.025 on the rig,
wall and storm); with mutations it gets back to about no reuse (rig 0.017 vs 0.024, storm 0.019 vs 0.021, wall 0.029 vs
0.025), at the cost of reuse (not equal time). RR's mean brightness is 0.83-0.97x the reference's, darkest on plain
ReSTIR (0.83-0.95x); OptiX's 0.97-1.04x except no reuse on the storm (0.93x) and the neon street (0.57x, a frame too
sparse for it). The solid red patch at the top left of every storm RR error map is RR brightening a nearly black part of
the cloud, the same for every input.
