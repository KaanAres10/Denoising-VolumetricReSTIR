# Volumetric ReSTIR Decorrelation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the pixel correlation that volumetric ReSTIR's reuse causes on every available
scene (Phase A). Then add opt-in Metropolis–Hastings mutations after temporal reuse and measure what
they fix (Phase B).

**Architecture:**
- Phase A adds diagnostics only, all opt-in so default captures stay byte-identical:
  - a `frameSeed` property for separately seeded chains;
  - sample-identity outputs from Final Shading;
  - a `-D` define for per-pixel spatial offsets;
  - scene loaders and knobs in `vr_graph.py`;
  - a capture script and a numpy metric tool.
- Phase B adds a lazily created `MutateSamples` compute pass between Temporal and Spatial Reuse. It
  uses the Eq. 16 weight update, stored as `p_y ← p̂(z)`, `runningSum ← runningSum·p̂(x₀)/p_y_old`.

**Tech Stack:** Falcor 9 (C++ render pass, Slang compute shaders), Mogwai Python scripts, Python 3.14
with numpy, OpenCV (EXR) and scipy, stdlib `unittest` (pytest is not installed).

**Spec:** `docs/superpowers/specs/2026-09-27-restir-mcmc-decorrelation-design.md`

## Global Constraints

- Every change is opt-in. With no new env var or property set, `outputs/mask_check.sh raw` and
  `outputs/pending_9p/spec/verify.sh quick` report all frames byte-identical.
- Commits carry no co-author or AI trailer (user preference).
- Branch: `decorrelation`.
- Build (C++ and shader deploy) with
  `./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR`,
  then `--target restore_runtime_dlls`: building a pass target drops `libprotoc.dll`/`z.dll`.
- Run Mogwai with `build/windows-vs2022/bin/Release/Mogwai.exe --script <script>`. Never run two
  Mogwai instances at once (the verify scripts abort if one is running).
- Round-1 mutations are single scatter only: disabled for `mMaxBounces>1`, `mVertexReuse` and
  reference mode.
- Headline metric: Δρ̄(r) = ρ̄_reuse(r) − ρ̄_noreuse(r), with bootstrap CIs over chains. Covariance is
  reported both raw (Eq. 21) and robust.
- Acceptance rate is reported, never gated. Correctness is decided by the unbiasedness gate.
- A checkpoint with the user comes after Phase A (Task 6) and before any Phase B task.

## Review Focus

1. **Chains whose frame-count ranges overlap.** All random streams are seeded from `mFrameCount`, so
   two chains that overlap in frame count reuse the same random numbers and converge to the same
   images once their history is forgotten. Expected: the harness assigns non-overlapping ranges and
   refuses to run otherwise. Pinned in Task 3.
2. **Pixels with zero variance** (black background, sky outside the medium) in the ρ̄ normalisation.
   Expected: they are excluded from both ends, with no NaN or inf. Pinned in Task 4's
   `test_constant_pixels_are_excluded`.
3. **A reservoir with invalid `p_y`** (0, NaN, inf) reaching the mutation pass. Expected: it is
   untouched, with no division. Pinned in Task 9's `guard` block and its no-mutation byte-identity
   check.
4. **Captures that contain fireflies** (lamp-edge samples of ~1e5). Expected: raw covariance reports
   them, robust covariance stays readable, and neither crashes or produces NaN. Pinned in Task 4's
   `test_robust_is_finite_with_fireflies`.
5. **An env-lit sample on a scene without an env map**, or a delta light. Expected: the light
   strategy does not apply, so the step is a self-transition. Pinned in Task 9's `applicable()` rules
   and exercised by the plume one-light bias test in Task 11.

---

## Phase A — the correlation study

### Task 1: Host diagnostics: `frameSeed`, and the sample-identity output

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/VolumetricReSTIR.h` (member `mFrameSeed`)
- Modify: `Source/RenderPasses/VolumetricReSTIR/VolumetricReSTIR.cpp`:
  - channel list: add `sampleIdentity`;
  - `parseProperties`;
  - the reset in `beginFrame` (line ~634);
  - Final Shading binding (~1290) and specialize defines (~903).
- Modify: `Source/RenderPasses/VolumetricReSTIR/FinalShading.cs.slang` (CB flag, output texture,
  write).

**Interfaces:**
- Produces:
  - **property `frameSeed` (int ≥ 0):** forces a history reset, and the next frame starts with
    `mFrameCount = frameSeed`. It is not persisted by `getProperties`.
  - **output channel `sampleIdentity`** (RGBA32Float, optional):
    - `.x` = low 24 bits of the sample hash, as a float;
    - `.y` = high 8 bits;
    - `.z` = `lightID + 4`, as a float;
    - `.w` = 1 where the pixel has a sample (`runningSum > 0`), else 0 (and xyz = 0).

- [ ] **Step 1: Add the member and property.**
  - `VolumetricReSTIR.h`, next to `mRandomizeFrameSpeed`:
    ```cpp
    /// >= 0: the next history reset starts mFrameCount here, then this reverts to -1. Every random
    /// stream is seeded from mFrameCount, so chains given non-overlapping ranges are separately
    /// seeded; overlapping ranges would replay the same random numbers (correlation_pose.py).
    int mFrameSeed = -1;
    ```
  - `parseProperties`: `props.getTo("frameSeed", mFrameSeed);`
  - The reset in `beginFrame` becomes:
    ```cpp
    if (mFrameSeed >= 0) { mFrameCount = mFrameSeed; mFrameSeed = -1; }
    else if (mRandomizeFrameSpeed) mFrameCount = rand() % 65536;
    else mFrameCount = 0;
    ```
  - `setProperties` already sets `mOptionsChanged = true`, so setting `frameSeed` resets the history.

- [ ] **Step 2: Add the output.** Add `const std::string kSampleIdentity = "sampleIdentity";` and a
  channel-list entry:
  ```cpp
  // Diagnostic for the decorrelation study (docs/superpowers/specs/2026-09-27-...): which sample the
  // final reservoir holds. .xy = 32-bit hash of (lightID, lightUV, depth) split 24/8 so a float EXR
  // stores it exactly, .z = lightID + 4, .w = 1 where the pixel has a sample.
  { kSampleIdentity, "gSampleIdentity", "final reservoir sample identity (diagnostic)", true /* optional */, ResourceFormat::RGBA32Float },
  ```
  - In the Final Shading block, next to `pLightDir`:
    ```cpp
    ref<Texture> pSampleIdentity = renderData.getTexture(kSampleIdentity);
    if (pSampleIdentity) vars["gSampleIdentity"] = pSampleIdentity;
    vars["CB"]["gOutputSampleIdentity"] = pSampleIdentity != nullptr;
    ```
  - In the FS specialize block:
    ```cpp
    program->addDefine("VR_OUTPUT_SAMPLE_IDENTITY", b(renderData.getTexture(kSampleIdentity) != nullptr));
    ```

- [ ] **Step 3: Shader.** In `FinalShading.cs.slang`:
  - Add `bool gOutputSampleIdentity;` to the CB.
  - Add the macro in both branches:
    - specialized: `#define OUTPUT_SAMPLE_IDENTITY (VR_SPECIALIZES(25) ? VR_OUTPUT_SAMPLE_IDENTITY : gOutputSampleIdentity)`
    - unspecialized: `#define OUTPUT_SAMPLE_IDENTITY gOutputSampleIdentity`
    - Bit 25 is inside the default `VR_SPECIALIZE_FIELDS` 0x3fffffb.
  - Add `RWTexture2D<float4> gSampleIdentity;` and `import Utils.Math.HashUtils;`.
  - At the end of `main`, after the lightDir block:
    ```slang
    if (OUTPUT_SAMPLE_IDENTITY)
    {
        // The exact sample the final reservoir holds. Shifts copy depth and the light sample verbatim,
        // so reservoirs sharing one sample share this hash (decorrelation study, duplicate heatmaps).
        const Reservoir res = gCurReservoirs[pixelId];
        float4 id = 0.f;
        if (!USE_REFERENCE && res.runningSum > 0.f)
        {
            uint h = jenkinsHash(asuint(res.depth));
            h = jenkinsHash(h ^ asuint(res.lightUV.x));
            h = jenkinsHash(h ^ asuint(res.lightUV.y));
            h = jenkinsHash(h ^ asuint(res.lightID));
            id = float4(float(h & 0xFFFFFFu), float(h >> 24), float(res.lightID + 4), 1.f);
        }
        gSampleIdentity[pixelPos] = id;
    }
    ```

- [ ] **Step 4: Build and deploy.**
  - Run: `./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR`
    and then `--target restore_runtime_dlls`.
  - Expected: builds with no errors.

- [ ] **Step 5: Check byte-identity.**
  - Run: `bash outputs/mask_check.sh raw none`
  - Expected: `raw: frames compared N, byte-identical N, stall False`.
  - Then run `bash outputs/pending_9p/spec/verify.sh quick`; expected: all frames identical.

- [ ] **Step 6: Commit.** Message: "Add a frameSeed property and a sample-identity output for the
  decorrelation study".

### Task 2: `VR_SR_PER_PIXEL_OFFSETS`, and the `vr_graph` loaders and knobs

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/SpatialReuse.cs.slang` (`generateNeighborOffset`)
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/vr_graph.py`

**Interfaces:**
- Produces:
  - `-DVR_SR_PER_PIXEL_OFFSETS=1`, set through `VR_SLANG_ARGS`.
  - `vr.SCENES` gains the keys `emerald`, `bunny`, `wdas`, `fireplume`, `dust`.
  - Env knobs, applied only when set: `VR_PHASE_G` (float), `VR_MTHRESH` (float), `VR_SR_RADIUS`
    (float), `VR_SR_COUNT` (int), `VR_SR_ROUNDS` (int).

- [ ] **Step 1: Per-pixel rotation of the neighbour pattern.** In `generateNeighborOffset`, after `u`
  is computed:
  ```slang
  #if VR_SR_PER_PIXEL_OFFSETS
      // Diagnostic (decorrelation study): the same R2 point set, rotated per pixel (Cranley-Patterson),
      // instead of one pattern shared by every pixel in the frame. sampleId 0 stays the centre pixel.
      if (sampleId != 0)
      {
          const uint h = jenkinsHash(uint(pixelId));
          u = frac(u + float2(h & 0xFFFFu, h >> 16) / 65536.f);
      }
  #endif
  ```
  - Add `#ifndef VR_SR_PER_PIXEL_OFFSETS` / `#define VR_SR_PER_PIXEL_OFFSETS 0` / `#endif` above it,
    and `import Utils.Math.HashUtils;`.
  - The Talbot loop calls the same function with the same `pixelId`, so each pixel's neighbour set is
    consistent between selection and MIS.

- [ ] **Step 2: Loaders.** Add `load_emerald`, `load_bunny`, `load_wdas`, `load_fireplume`,
  `load_dust` to `vr_graph.py`:
  - Copy the volume parameters and camera poses verbatim from `run_emerald_square.py`,
    `run_bunny_cloud.py`, `run_disney_cloud.py` and `run_volume_dataset.py` (EmberGen: the sequence
    via `vdb_pipeline`, then held at its middle frame).
  - Pass `g=env_float("VR_PHASE_G", <current g>)` in every loader, including plume, bistro and
    explosion. Unset keeps today's value, so the locked config is unchanged.
  - Each loader returns `{"scatterAlbedo": …, "exposure": 0.0, "params": {...}}`:
    - emerald: `{"mUseSurfaceScene": True, "mUseEmissiveLights": True, "mUseEnvironmentLights": True, "mTemporalReuseMThreshold": 10.0}`;
    - the others: `{"mUseEnvironmentLights": True, "mUseEmissiveLights": False}`.
  - Set the camera near and far planes as in `load_plume`.
  - Register all five in `SCENES`.

- [ ] **Step 3: Knobs.** At the end of `add_restir`, just before `g.addPass(...)`:
  ```python
  # Decorrelation study knobs, applied only when set, so every existing script is unchanged.
  for _key, _var, _conv in (("mTemporalReuseMThreshold", "VR_MTHRESH", float),
                            ("mSampleRadius", "VR_SR_RADIUS", float),
                            ("mSpatialSampleCount", "VR_SR_COUNT", int),
                            ("mSpatialReuseRounds", "VR_SR_ROUNDS", int)):
      if os.environ.get(_var):
          props["mParams"][_key] = _conv(os.environ[_var])
  ```

- [ ] **Step 4: Smoke-test every loader.**
  - For each new scene run
    `VR_SCENE=<s> VR_FRAMES=8 VR_DENOISER=none VR_OUT_DIR=<tmp> VR_TAG=t Mogwai.exe --script capture_orbit.py`.
  - Expected: a non-black PNG per scene.
  - Also run a plume with `VR_SLANG_ARGS="-DVR_SR_PER_PIXEL_OFFSETS=1"`; expected: it renders.

- [ ] **Step 5: Byte-identity**, as in Task 1 Step 5.

- [ ] **Step 6: Commit.** Message: "Add study scene loaders, reuse knobs and a per-pixel spatial
  offset diagnostic".

### Task 3: The `correlation_pose.py` capture harness

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py`
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_correlation_schedule.py`

**Interfaces:**
- Consumes: `vr.load_scene`, `vr.add_restir`, `vr.pin_clock`, the `frameSeed` property, the
  `sampleIdentity` output.
- Produces, in `VR_OUT_DIR`:
  - `<TAG>.VolumetricReSTIR.accumulated_color.<frame>.exr`;
  - optionally `<TAG>.VolumetricReSTIR.sampleIdentity.<frame>.exr`;
  - `<TAG>.schedule.json`:
    `{"chains":[{"seed":s,"frames":[f,…]}], "burst":[f,…], "W":…, "S":…, "m":…, "scene":…, "env":{…}}`.
  - In reference mode: `<TAG>.Accum.output.<frame>.exr` at FRAMES/2 and at FRAMES.
- The pure schedule function `build_schedule(f0, R, m, W, S, burst, seed_base, seed_stride)` lives in
  a Mogwai-free module `correlation_schedule.py`, so it can be unit-tested.

- [ ] **Step 1: Write a failing test for the schedule.** In
  `Scripts/tests/test_correlation_schedule.py` (unittest):
  - The first chain's first capture is at `f0 + W + 1 - 1`.
  - Captures within a chain are exactly S apart.
  - Seed frame-count ranges `[seed, seed + W + (m-1)*S + 1)` are pairwise disjoint.
  - `build_schedule` raises `ValueError` when `seed_stride <= W + (m-1)*S + 1` (Review Focus 1).
  - A burst of B frames captures B consecutive frames after its own warm-up, with a seed range
    disjoint from every chain's.

- [ ] **Step 2: Run the test and see it fail.**
  - Run: `python -m unittest Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_correlation_schedule.py -v`
  - Expected: ImportError (no module yet).

- [ ] **Step 3: Implement `correlation_schedule.py`.** It returns the list of per-chain dicts
  `(seed, first_frame, capture_frames)`, the burst dict, and the total number of frames to render.
  Each chain renders `W + (m-1)*S + 1` frames.

- [ ] **Step 4: Run the test and see it pass.**

- [ ] **Step 5: Write `correlation_pose.py`.**
  - **Environment variables:** `VR_SCENE` (default bistro), `VR_MODE` restir|reference,
    `VR_DISPLAY` (default 1920x1080), `VR_CHAINS` (10), `VR_PER_CHAIN` (10), `VR_SPACING` (33),
    `VR_WARM` (default max(256, 4·Mcap)), `VR_BURST` (0), `VR_SEED_BASE` (100000), `VR_SEED_STRIDE`
    (default: the smallest multiple of 10000 above the chain length), `VR_IDS` (0),
    `VR_NO_TEMPORAL`/`VR_NO_SPATIAL`, `VR_FRAMES`/`VR_SPP` (reference mode), `VR_OUT_DIR`, `VR_TAG`.
  - **Pose:** Bistro uses `reference_pose.py`'s verify pose (orbit pose 150 about (-11, 6.025879, 0))
    with `m.scene.animated = False`. Every other scene uses its loader's camera. The clock is pinned
    at 30.
  - **Loop:** for each chain, `g.get_pass("VolumetricReSTIR").set_properties({"frameSeed": seed})`,
    then render the chain's frames. The capture frames come from the schedule via
    `m.frameCapture.addFrames(g, all_frames)`.
  - **Output:** write the schedule JSON, set `m.clock.exitFrame = last + 60`, and print a single
    summary line.

- [ ] **Step 6: Smoke run.**
  - `VR_SCENE=plume VR_CHAINS=2 VR_PER_CHAIN=2 VR_WARM=8 VR_SPACING=3 VR_IDS=1 VR_OUT_DIR=<tmp>`.
  - Expected: 4 color and 4 identity EXRs, and a schedule JSON with 2 chains.
  - Check with numpy that the two chains' first captures differ, and that chain 0's two captures
    differ.

- [ ] **Step 7: Commit.** Message: "Add the correlation capture harness with separately seeded
  chains".

### Task 4: The `m_corr.py` metric tool

**Files:**
- Create: `outputs/decorr/m_corr.py`
- Create: `outputs/decorr/test_m_corr.py`

**Interfaces:**
- Produces (library functions):
  - `luminance(rgb) -> ndarray`
  - `robust_transform(lum, clamp) -> ndarray`
  - `box_rho(stack, radii, mask=None) -> dict r -> (rho_bar, per_frame_terms)`
  - `box_cov(stack, radii, mask=None)`
  - `autocorr2d(stack, mask, half=32)`
  - `temporal_rho(series, max_lag)`
  - `duplicate_map(ids, tile=20)`
  - `bootstrap_chains(per_frame_terms, chain_of_frame, n=1000, seed=0) -> (lo, hi)`
  - `reference_errors(stack, ref, regions)`
- Produces (CLI):
  `python outputs/decorr/m_corr.py <run_dir> [--tag T] [--baseline <run_dir>] [--ref <exr>] [--region-set bistro|none] [--clamp C] [--out <json>]`,
  which writes the JSON and PNG heatmaps and prints a summary table.

- [ ] **Step 1: Write the failing tests** in `test_m_corr.py` (unittest, synthetic data, 64×64,
  K=400):
  - `test_white_noise_has_no_correlation`: |ρ̄(r)| < 0.02 for r = 1, 4, 8.
  - `test_box_blurred_noise_matches_analytic`: blur white noise with a (2a+1)² box, a=2. The expected
    ρ̄(r) is the mean over offsets (dx,dy) ≠ 0 in the (2r+1)² box of
    `max(0,w-|dx|)*max(0,w-|dy|)/w²` with w=5; tolerance 0.03.
  - `test_constant_pixels_are_excluded`: a stack with a zero-variance half gives finite ρ̄, equal to
    the ρ̄ of the other half alone within 0.02 (Review Focus 2).
  - `test_robust_is_finite_with_fireflies`: inject 1e5 values into 0.01% of pixel-frames; raw and
    robust results are finite, and robust |ρ̄| < 0.05 on white noise (Review Focus 4).
  - `test_duplicate_map_counts`: a 40×40 id image in which one 20×20 tile has 50 pixels sharing an
    id; the map has 49 duplicates in that tile and 0 elsewhere.
  - `test_bootstrap_covers_truth`: on white noise, the 95% interval from 20 chains of 5 frames
    contains 0.
  - `test_temporal_rho_of_ar1`: an AR(1) series with coefficient 0.8 gives ρ(1) ≈ 0.8 ± 0.05.

- [ ] **Step 2: Run the tests and see them fail.**
  - Run: `python -m unittest outputs/decorr/test_m_corr.py -v`
  - Expected: ImportError.

- [ ] **Step 3: Implement `m_corr.py`.**
  - **Residuals:** Z_k(i) = (I_k(i) − μ(i)) / σ(i) with the sample mean and std over all K. The mask
    is σ > 0 and not in the robust-trimmed set.
  - **ρ̄(r):** with `cv2.boxFilter(normalize=False)`, S_k = box(Z_k·mask) − Z_k·mask (centre
    excluded) and N = box(mask) − mask. Then per-frame term t_k = Σ_i mask·Z_k·S_k/N over valid i,
    divided by the valid count, and ρ̄ = Σ t_k / (K−1).
  - **C̄(r):** the same with unnormalised residuals.
  - **Two passes over the files** (mean/variance, then accumulation), float64 accumulators, so
    memory stays at a few frames.
  - **2D autocorrelation:** the mean over frames of `irfft2(|rfft2(Z·mask)|²)` divided by the
    mask's own autocorrelation, cropped to ±`half`.
  - **Duplicates:** per 20×20 tile, `count(valid) - count(unique ids)`, averaged over frames.
  - **Reference errors:** region bias `(mean(I)-ref)/mean(ref)`; relMSE per frame
    `mean((I-R)²/(R²+1e-4))` with the worst 0.01% trimmed; RMS of the Gaussian-blurred error
    (σ = 2, 8, 32) over the mean of the reference.

- [ ] **Step 4: Run the tests and see them pass.**

- [ ] **Step 5: Commit.** Message: "Add the correlation metric tool with synthetic-data tests".

### Task 5: `run_study.sh` and `sheet.py`

**Files:**
- Create: `outputs/decorr/run_study.sh`
- Create: `outputs/decorr/sheet.py`

**Interfaces:**
- Consumes: `correlation_pose.py` (Task 3), `m_corr.py` (Task 4).
- Produces: `run_study.sh <stage>`, where stage is one of `survey | burst | deep <scene> | refs | denoise <scene> | summary`.
  It writes `outputs/decorr/<scene>/<config>/` and appends to `outputs/decorr/summary.tsv`.
- `sheet.py <scene>` writes `outputs/decorr/<scene>/sheet.png`: crops of raw frames per config, the
  ρ̄(r) curves, the 2D autocorrelation, and the duplicate heatmaps.

- [ ] **Step 1: Write `run_study.sh`.**
  - It unsets all `VR_*` and `NRD4_*`, checks and restores the runtime DLLs, and aborts if Mogwai is
    running.
  - It has a function `cap <scene> <config> <env...>` that runs `correlation_pose.py` with
    `timeout 7200`, then `m_corr.py`.
  - **survey:** every scene × {noreuse (`VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1`), shipped}.
  - **burst:** `VR_BURST=256` per survey scene, shipped config.
  - **deep:**
    - temporal only (`VR_NO_SPATIAL=1`) and spatial only (`VR_NO_TEMPORAL=1`);
    - `VR_MTHRESH` ∈ {1, 4, 10, 20, 50, 200};
    - `VR_SR_RADIUS` ∈ {3, 30};
    - `VR_SR_ROUNDS=3`;
    - `VR_SLANG_ARGS=-DVR_SR_PER_PIXEL_OFFSETS=1`.
  - **refs:** `VR_MODE=reference` per deep scene, except Bistro, which uses
    `outputs/pending_9p/forkref/cap/v9sa_ref`.
  - **denoise:** the Look config for each of `optix`, `oidn`, `nrd RelaxDiffuseSh`,
    `nrd ReblurDiffuseSh`, `rr`, at the still pose, shipped vs. no reuse. Its output is captured
    after the denoiser.

- [ ] **Step 2: Write `sheet.py`.**

- [ ] **Step 3: Dry run on plume with tiny counts.**
  - `VR_CHAINS=2 VR_PER_CHAIN=2 VR_WARM=8`.
  - Expected: `summary.tsv` has 2 rows and the sheet PNG exists.

- [ ] **Step 4: Commit.** Message: "Add the decorrelation study runner and crop sheets".

### Task 6: Run Phase A and record the findings (checkpoint)

- [ ] **Step 1: Time one config per scene** and choose the resolution. If 1080p makes the matrix
  longer than ~12 h, run the survey at 960×540 and say so in the record.
- [ ] **Step 2:** `run_study.sh survey`, then `burst`. Set `VR_SPACING` per scene from the burst's
  ρ(τ) < 0.05 lag (coprime with 16), and re-run the survey rows that used a smaller spacing.
- [ ] **Step 3:** `run_study.sh deep bistro`, `deep plume_g-0.9`, plus the top-ranked scenes; then
  `refs` and `denoise`.
- [ ] **Step 4:** Record V1…Vn in the spec's *Verification results*, and a STATE.md section. Cover:
  which scenes show reuse-induced correlation (Δρ̄ with CIs), from which stage and parameter,
  exact-sample vs. light-ID sharing, the effect of the shared offsets, and what reaches each
  denoiser. Commit ("Record the decorrelation study: …").
- [ ] **Step 5: Stop and review with the user.** The findings set the Phase B priority (light vs.
  depth moves; whether round 1.5 is needed) and its scenes.

---

## Phase B — mutations (after the checkpoint)

### Task 7: Tests of the measure assumptions

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_mutation_measures.py`

- [ ] **Step 1: Write the tests** (numpy replicas of the shader math):
  - `sample_triangle` (MathHelpers.slang:400): the finite-difference |det ∂b/∂u| equals 0.5 at 1000
    random u.
  - The inverse used in VolumeUtils.slang:332 (from `uv = bary.yz`: `su = 1 - uv.x`,
    `u = (su², uv.y/su)`) round-trips.
  - `latlong_map_to_world` / `world_to_latlong_map` (MathHelpers.slang:111,126) round-trip to within
    1e-5 away from the poles.
  - The rotation proposal (θ log-uniform in [θ1, θ2], uniform φ): over 1e6 draws from two different
    ω, the histogram of angle(ω, ω') matches, so the density depends only on the angle.
  - Symmetry of the torus step: the distribution of `frac(u+δ) - u` (wrapped) is symmetric.
- [ ] **Step 2: Run** `python -m unittest …/test_mutation_measures.py -v`. Expected: PASS. A failure
  stops Phase B.
- [ ] **Step 3: Commit.**

### Task 8: Host plumbing for the mutation pass (dispatched, doing nothing yet)

**Files:**
- Modify: `VolumetricReSTIR.h`:
  - params: `mMutationCount=0`, `mMutationStrategyMask=3`, `mMutationLightStepMin=1/1024.f`,
    `mMutationLightStepMax=1/64.f`, `mMutationDirStepMinDeg=0.1f`, `mMutationDirStepMaxDeg=5.f`,
    `mMutationDepthStepMin=0.5f`, `mMutationDepthStepMax=16.f`, `mMutationStats=false`, each in
    `serialize`;
  - a member `ref<ComputePass> mMutateSamplesPass`, a stats buffer, and `void runMutations(...)`.
- Modify: `VolumetricReSTIR.cpp`:
  - lazy creation of the pass (plain or scene pass as for the others, with `updateSceneDefines`,
    sample-generator defines and `VR_TRACKING_MASK` = spatialMask);
  - `VR_SPECIALIZE` with `VR_SAMPLING_OPTIONS` = spatialOptions, when "TR" is specialized;
  - `VR_GROUP_MU`;
  - dispatch right after `mTemporalReusePass->execute` (before the spatial-off copy), and after
    Generate Samples when temporal reuse is off;
  - UI controls;
  - a stats readback every 256 frames logged with `logInfo`.
- Modify: `Scripts/vr_graph.py`: the knobs `VR_MUTATIONS` (int), `VR_MUT_STRAT` (`light,depth`, used
  as a mask), `VR_MUT_STATS`.
- Create: `MutateSamples.cs.slang`, a first version that returns immediately.

- [ ] **Step 1: Implement.** Guards in `runMutations`: return unless `mMutationCount > 0`,
  `!mUseReference`, `mMaxBounces == 1` and `!mVertexReuse`.
- [ ] **Step 2: Build; byte-identity with the knobs off.** As in Task 1 Step 5.
- [ ] **Step 3: With `VR_MUTATIONS=1` and the empty shader,** plume and bistro captures are
  byte-identical to the knobs-off captures: the pass runs and changes nothing.
- [ ] **Step 4: Commit.**

### Task 9: The mutation kernel (light-vertex and depth strategies)

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang` (full kernel)

**Interfaces:**
- Consumes: `evaluate_P_hat` (ReSTIRHelper.slang:476), `computeRayPinholeScaled`,
  `gScene.envMap.uvToWorld/worldToUv`, `IExternalVisibilityProvider`.
- Produces: an updated `gCurReservoirs` in place, and `gMutationStats[0..5]`:
  - 0/1: light proposed / accepted;
  - 2/3: depth proposed / accepted;
  - 4: skipped as invalid;
  - 5: p̂(x₀) ≠ `p_y`.

- [ ] **Step 1: Write the kernel.**
```slang
__exported import ReSTIRHelper;
#include "HostDeviceSharedDefinitions.slangh"
import Utils.Debug.PixelDebug;
import Utils.Math.MathHelpers;
#include "Utils/Math/MathConstants.slangh"

cbuffer CB
{
    uint2 gResolution;
    int gFrameCount;
    int gNumTotalRounds;
    int gMutationCount;
    uint gStrategyMask;             // bit 0 light-vertex, bit 1 depth
    float gLightStepMin, gLightStepMax;   // torus step in u, Kelemen magnitudes
    float gDirStepMin, gDirStepMax;       // radians
    float gDepthStepMin, gDepthStepMax;   // in ray-march steps (volumeDesc.tStep * volumeWorldScaling)
    bool gCollectStats;
    SamplingOptions gSamplingOptions;
    EnvMapSampler envMapSampler;
    EmissiveLightSampler emissiveSampler;
}
#include "SpecializeOptions.slangh"
#if VR_SPECIALIZE
static const SamplingOptions kSamplingOptions = VR_SAMPLING_OPTIONS;
#define SAMPLING_OPTIONS specializeOptions(kSamplingOptions, gSamplingOptions)
#else
#define SAMPLING_OPTIONS gSamplingOptions
#endif

RWStructuredBuffer<Reservoir> gCurReservoirs;
StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
RWStructuredBuffer<uint> gMutationStats;
#ifdef SURFACE_SCENE
StructuredBuffer<VBufferItem> gVBuffer;
#endif

static const uint kLight = 0;
static const uint kDepth = 1;

/// Records the primary-ray visibility of an evaluation, so moves that keep the depth reuse it.
struct CachingVisibilityProvider : IExternalVisibilityProvider
{
    float data = -1.f;
    float getVisibility(int bounce) { return bounce == 0 ? data : -1.f; }
    [mutating] void putVisibility(int bounce, float visibility) { if (bounce == 0) data = visibility; }
    [mutating] void Initialize() { data = -1.f; }
};

void stat(uint i) { if (gCollectStats) InterlockedAdd(gMutationStats[i], 1u); }

/// Which strategies can move this sample. Depends only on the sample's TYPE, which no move changes.
uint applicable(Reservoir r)
{
    const bool selfEmission = r.lightID == kSelfEmissionLightID;
    const bool inMedium = r.depth != kRayTMax;
#ifdef SURFACE_SCENE
    const bool hasShadingPoint = true;   // kRayTMax = surface hit; an invalid hit gives p̂ = 0
#else
    const bool hasShadingPoint = inMedium; // kRayTMax = background, no light sample
#endif
    const int lightCount = (int)gScene.getLightCount();
    const bool env = r.lightID < 0 && !selfEmission;
    const bool emissiveTri = r.lightID >= lightCount;
    uint mask = 0;
    if (hasShadingPoint && !selfEmission && (env || emissiveTri)) mask |= 1u << kLight;
    if (inMedium) mask |= 1u << kDepth;
    return mask & gStrategyMask;
}

/// Kelemen 2002 magnitude with a random sign: symmetric about 0.
float kelemenStep(float lo, float hi, float2 u)
{
    const float s = hi * exp(-log(hi / lo) * u.x);
    return u.y < 0.5f ? s : -s;
}

float pHat(Reservoir r, VolRay ray, inout SampleGenerator sg, StructuredBufferArrayDataProvider dp,
           VBUFFERDECLARE inout CachingVisibilityProvider vis)
{
    const float p = evaluate_P_hat(ray, sg, envMapSampler, emissiveSampler, VBUFFERITEM dp, SAMPLING_OPTIONS, r, vis, false, true, false);
    return (isnan(p) || isinf(p)) ? 0.f : p;
}

#ifndef VR_GROUP_X
#define VR_GROUP_X 16
#endif
#ifndef VR_GROUP_Y
#define VR_GROUP_Y 16
#endif
[numthreads(VR_GROUP_X, VR_GROUP_Y, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{
    if (any(DTid.xy >= gResolution)) return;
    const int2 pixelPos = DTid.xy;
    const int pixelId = getPixelID(pixelPos, gResolution);

    Reservoir r = gCurReservoirs[pixelId];
    // Invalid reservoirs are never touched: the update below divides by p_y.
    if (!(r.runningSum > 0.f) || isinf(r.runningSum) || !(r.M > 0.f) || !(r.p_y > 0.f) || isinf(r.p_y)) { stat(4); return; }
    const uint moves = applicable(r);
    if (moves == 0) return;   // every step would be a self-transition

    // A stream no other pass uses: other passes seed with gNumTotalRounds * gFrameCount + round < 2^31.
    SampleGenerator sg = SampleGenerator(pixelPos, uint(gNumTotalRounds * gFrameCount) | 0x80000000u);
    CameraRay cameraRay = computeRayPinholeScaled(gScene.camera, pixelPos, 1, 0.5f, gResolution);
    const VolRay ray = { cameraRay.origin, cameraRay.dir, 0, kRayTMax };
#ifdef SURFACE_SCENE
    VBufferItem vItem = gVBuffer[pixelId];
#endif
    StructuredBufferArrayDataProvider dp;
    dp.data = gCurExtraBounceReservoirs;

    CachingVisibilityProvider vis0;
    vis0.Initialize();
    const float p0 = pHat(r, ray, sg, dp, VBUFFERITEM vis0);
    if (!(p0 > 0.f)) { stat(4); return; }
    if (p0 != r.p_y) stat(5);

    Reservoir x = r;
    float px = p0;
    float primaryVis = vis0.data;
    const float depthUnit = gScene.volumeDesc.tStep * gScene.volumeWorldScaling;
    const uint enabledCount = countbits(gStrategyMask);

    for (int it = 0; it < gMutationCount; it++)
    {
        // Fixed, state-independent strategy probabilities; an inapplicable pick is a self-transition.
        const uint pick = min(uint(sampleNext1D(sg) * enabledCount), enabledCount - 1);
        uint s = firstbitlow(gStrategyMask);
        for (uint k = 0; k < pick; k++) s = firstbitlow(gStrategyMask & ~((2u << s) - 1u));
        if ((moves & (1u << s)) == 0) continue;

        Reservoir z = x;
        CachingVisibilityProvider visz;
        visz.Initialize();
        if (s == kLight)
        {
            if (x.lightID < 0) // environment map: rotate on the sphere, symmetric in solid angle
            {
                const float3 w = gScene.envMap.uvToWorld(x.lightUV);
                const float theta = abs(kelemenStep(gDirStepMin, gDirStepMax, sampleNext2D(sg)));
                const float phi = M_2PI * sampleNext1D(sg);
                const float3 t = perp_stark(w);
                const float3 b = cross(w, t);
                const float3 w2 = cos(theta) * w + sin(theta) * (cos(phi) * t + sin(phi) * b);
                z.lightUV = gScene.envMap.worldToUv(normalize(w2));
            }
            else // emissive triangle: torus step in the area-uniform u, same triangle
            {
                z.lightUV = frac(x.lightUV + float2(kelemenStep(gLightStepMin, gLightStepMax, sampleNext2D(sg)),
                                                    kelemenStep(gLightStepMin, gLightStepMax, sampleNext2D(sg))));
            }
            visz.data = primaryVis;  // the depth did not move
            stat(0);
        }
        else // s == kDepth: Pauly's propagation perturbation along the camera ray
        {
            z.depth = x.depth + depthUnit * kelemenStep(gDepthStepMin, gDepthStepMax, sampleNext2D(sg));
            stat(2);
            if (!(z.depth > 0.f)) continue;   // p̂ = 0: rejected, never resampled
        }
        const float pz = pHat(z, ray, sg, dp, VBUFFERITEM visz);
        if (pz > 0.f && sampleNext1D(sg) * px < pz)
        {
            x = z;
            px = pz;
            primaryVis = visz.data;
            stat(s == kLight ? 1 : 3);
        }
    }

    // Eq. 16 in this reservoir's representation W = runningSum / (p_y M):
    // W(z) = p̂(x0)/p̂(z) W(x0)  <=>  runningSum *= p̂(x0)/p_y_old, p_y = p̂(z).
    r.runningSum *= p0 / r.p_y;
    r.depth = x.depth;
    r.lightUV = x.lightUV;
    r.p_y = px;
    gCurReservoirs[pixelId] = r;
}
```

- [ ] **Step 2: Build, then run the no-move check.** With `VR_MUTATIONS=1 VR_MUT_STRAT=` (empty mask
  → no applicable move), the output is byte-identical to off: `moves == 0` returns early.
- [ ] **Step 3: Smoke run.** Plume and bistro with `VR_MUTATIONS=1 VR_MUT_STATS=1`. Expected: the
  images render, the log lines report acceptance per strategy, and neither rate is 0 or 1.
- [ ] **Step 4: Byte-identity with the knobs off.**
- [ ] **Step 5: Commit.**

### Task 10: The unbiasedness gate

- [ ] **Step 1: Plume, one point light.** Add `"mMutationCount": int(os.environ.get("VR_MUTATIONS", "0"))`
  to `bias_test_plume.py`'s mParams. Run it with `VR_MUTATIONS=0` and `5`, compare both against
  `VR_MODE=reference` with `ImageCompare -m MSE`, and read the region means. A delta light, so only
  the depth moves apply.
- [ ] **Step 2: Bistro.** Run `reference_pose.py VR_MODE=restir` with `VR_MUTATIONS=0`, then `1` and
  `5`, and score each with `outputs/pending_9p/forkref/score.py <tag>@v9sa`.
  - Expected: the region bias is within the mutation-off error bars.
- [ ] **Step 3: Plume env and explosion.** Run `correlation_pose.py VR_MODE=reference`, then check
  the same way.
- [ ] **Step 4: Record the gate as V-B1 and commit.** A failed gate blocks Task 11.

### Task 11: Phase B evaluation and record

- [ ] **Step 1:** `run_study.sh` gains a `mutate <scene>` stage: mutations {0, 1, 5} × strategy
  {light, depth, both}; M cap {10, 50, 200} × {0, 1}; and equal time vs. `mInitialM`.
- [ ] **Step 2:** Run it on the Phase-A scenes, then `denoise` with 0 vs. 1 mutation.
- [ ] **Step 3:** Record V-B2…: the relative change in C̄(8) (raw and robust), Δρ̄, relMSE,
  acceptance, ms per pass, and the denoised effect, with sheets. Commit.
