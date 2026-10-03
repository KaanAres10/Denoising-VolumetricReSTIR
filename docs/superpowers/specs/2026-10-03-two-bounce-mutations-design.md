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
