# The paper: Metropolis–Hastings mutations for Volumetric ReSTIR, seen through five denoisers

**Date:** 2026-10-20
**Status:** approved by the user 2026-10-20; amended the same day after reading the harness (see "Amendments")
**Branch:** decorrelation
**Builds on:** `2026-09-27-restir-mcmc-decorrelation-design.md` (Phase A, V1–V9; Phase B, V-B1–V-B10) and
`2026-10-03-two-bounce-mutations-design.md` (V-C0–V-C7). Every number below cites its section there.

## Intent

`DenosingVolumetricReSTIR/paper.tex` today studies denoiser strength against extra ReSTIR sampling (OIDN and OptiX,
plume and Bistro, FLIP). The user wants it replaced, not edited: a paper whose focus is the Metropolis–Hastings
mutations built on this branch, shown before and after through many denoisers, built from the experiments already
run and approved, plus the five-denoiser runs this spec adds.

### Success criteria

1. **Every number in the paper traces to a recorded result:** a V-section of the two specs, or the new runs'
   results file (E5). The plan keeps a numbers ledger (each number, its source), checked before the paper is done.
2. **The claims stay inside the data.** In particular the paper says, in the abstract and the results:
   - the large cuts (−45% to −90% after denoising) are at a 200-frame history (M cap 200);
   - at the shipped cap mutations cut the denoised error by 3–26% (V-C3), and plain ReSTIR there is already about as
     good as cap 200 with mutations on three of the five main scenes (V-C3);
   - so mutations are what makes a long history usable, and cap 200 with mutations wins outright only with many
     lights;
   - the limits: brightness lives in the shared normalization, which mutations keep; a decoupled history removes
     more at long histories; the duplication cap biases; DLSS RR darkens its input; motion.
3. **The five-denoiser comparison** covers the 19 approved setups at both histories, after the gates in E4 pass.
4. **The paper builds** with Tectonic: no errors, no undefined references or citations, every figure present, about
   ten pages plus references and an appendix.
5. **Every citation is checked** against the PDF in `Papers/` or the publisher's page before it enters the
   bibliography. A citation that cannot be checked is dropped.

## Decisions taken in chat (2026-10-20)

| Decision | Choice |
|---|---|
| Framing | Option 1: mutations, judged through five denoisers. The correlation study and the limits support it. |
| Length | About 10 pages, ACM `sigconf` two-column (the existing template, author-year citations), plus references and an appendix. |
| Denoisers | OptiX 9.1 (temporal, volume-aware guides), OIDN 2.3.3 (CUDA), NRD 4.17 RELAX-SH, NRD 4.17 REBLUR-SH, DLSS Ray Reconstruction. `oidncpu` is OIDN's network again; `sr` is an upscaler; SVGF is not wired. |
| New runs | Three scene groups, 19 setups (below). Not every scene: the meaningful ones. |
| Histories | M cap 200 and the shipped cap: 4, except 10 on the night street, which Emerald Square's loader sets. |
| Build | Tectonic, a portable binary in the scratchpad; the user may still use Overleaf. |
| Surface-first-vertex moves | Reverted (ca34f33, user's call); left out of the paper. |
| Left out | The look-development work (teapot, dust, the glowing construct), the density study (V8) and most of the stress atlas (V-B9) — except one sentence on the construct's motion test (E7). |
| The old paper | Kept as `paper_v1_denoising_vs_sampling.tex`; its figures stay in `figures/`. |
| Git | The paper folder stays out of git, like the user's other folders. This spec, the harness change and the run/scoring scripts are committed. |

### The 19 setups

- **One bounce, the gallery (12):** cathedral god rays (`bunnycathedral_d0.3`), spotlight beam (`bunnyspot`),
  warm/cool panels (`bunnysoftbox`), lamp inside the cloud (`bunnyinside`), backlit rim (`bunnyback_g0.8`), slats
  (`bunnystripes`), self-emitting explosion (`explosion`), 48 lanterns (`bunnylanterns`), sunset cloud
  (`wdassunset_g0.85`), backlit smoke (`plumeback_g0.9`), concert beams (`plumeconcert_g0.6`), and the weak case,
  the night street (`emeraldnight_d3`).
- **Two bounces (5):** `explosiondusk_b2` (the paper's setup), `bunnycathedral_d0.3_b2`, `bunnyback_g0.8_b2`,
  `bunnysoftbox_b2`, `wdassunset_g0.85_b2`.
- **One mutation is not enough (2):** the 192-light swarm (`bunnyswarm_d3`) and the thunderstorm
  (`wdasstorm_g0.5`).

## The paper

Working title: *Decorrelating Volumetric ReSTIR with Metropolis–Hastings Mutations, Seen Through Five Denoisers*.

### Outline, with each section's claims and their evidence

**Abstract and teaser.** Reuse leaves correlated blotches that denoisers keep; volume-specific mutations remove them
without bias; the size of the effect depends on the history length (criterion 2). Teaser: the five denoisers
before and after, and the reference, on the setup whose median cut over the five denoisers at M cap 200 is largest
in E5's table (E6).

**1 Introduction.** The problem, the question (what do mutations change in what a viewer sees after a denoiser), and
four contributions:
1. a measurement of the correlation Volumetric ReSTIR's reuse creates, and what of it reaches five denoisers;
2. Metropolis–Hastings moves for volumes at one and two bounces, with an unbiasedness argument and a bias suite;
3. a before/after evaluation through five denoisers on 19 setups at two history lengths;
4. where mutations help and where they cannot, and what they cost.

**2 Background.** ReSTIR (Bitterli et al. 2020), resampled importance sampling (Talbot et al. 2005), Volumetric
ReSTIR (Lin et al. 2021), MCMC mutations for ReSTIR (Sawhney et al. 2024), Metropolis light transport in media
(Pauly et al. 2000) and Kelemen et al.'s mutation steps, decoupled histories (Zhou 2025), colour clumping (RGB
ReSTIR), and the five denoisers.

**3 Where the correlation comes from** (condensed Phase A, 1080p, 10 seeded chains × 10 captures):
- reuse correlates neighbours on all eight scenes, Δρ̄(8) 0.0053–0.0196 over the frame (V1);
- spatial reuse creates it; temporal history multiplies it 2.7–3.9× (V2);
- the M cap is the strongest lever: plume g = −0.9 Δρ̄(8) 0.016 at cap 4, 0.120 at cap 200 (V3);
- error is still 1.7–38× lower than without reuse (V1);
- what reaches the denoisers: temporal denoisers keep it — Bistro covariance at 8 px ×16 (RELAX) and ×60 (REBLUR),
  ×1.1 OptiX, ×0.7 OIDN, ×2.4 RR (V7).
Table: a condensed V1/V3. No new runs.

**4 Volumetric mutations.**
- The sample, and Eq. 16 as implemented: `runningSum ← runningSum · p̂(x₀)/p_y`, `p_y ← p̂(z)`, M kept (Phase B).
- The moves (Phase B, two-bounce spec Step 1): light (torus step of u on an emitter; env rotation), depth
  (propagation perturbation), free flight (independence, the renderer's distance sampler), light re-selection
  (independence; position-aware for point lights); at two bounces direction, distance and rebounce, for both path
  tags.
- Placement after spatial reuse (V-B9).
- Unbiasedness: V-C6's argument (invariance of p̂ suffices for Eq. 16), and the bias suite — the shipped pass on ten
  setups, 64 seed-paired chains, largest |z| 1.80, χ² 8.77 on 10 degrees of freedom, p = 0.55 (V-C6); acceptance
  rates (V-B1, V-C1).
- Practical findings worth a paragraph: the && that does not short-circuit, and Falcor's env `evalPdf`
  self-swizzle that biased re-selection by −0.44% until the move read the density itself (V-B9).

**5 Cost.** The pass before and after coherent moves and early rejection: 5 mutations add +10% to +52% of the frame
after the speed-up, the pass 2.5–4.1× faster (V-C4, V-C5); one step costs 4–11 initial candidates (V-C3); three
mutations are within 2–12% of five's error, one is 18–43% worse (V-C5 C). Equal time at M cap 200: mutations
−50% to −82%, more candidates −21% to +16% (V-C3); at Bistro's shipped cap more candidates win (V-B5).

**6 Results.**
- **6.1 Setup:** the GPU (RTX 5070 Laptop, 8 GB), resolution, the pass as shipped, the reference renderer (and the
  interior-light fix, a2a3aa8), the metric: relMSE in the medium (the no-reuse run's mask; luminance clipped at the
  reference's brightest 0.5% there), each reference's own noise beside it.
- **6.2 Five denoisers at M cap 200:** the main table (E5) and figure (E6): 19 setups × 5 denoisers, before → after.
- **6.3 The shipped history:** the same table at the shipped cap, and plain ReSTIR there against cap 200 with
  mutations (criterion 2).
- **6.4 How many mutations:** the swarm and the storm (V-C7) through OptiX and RR, the count strip (approved).
- **6.5 The galleries:** the approved 1080p OptiX and RR figures (one and two bounces).

**7 Limits.**
- The brightness of a pixel is mostly its reservoir's normalization, which Eq. 16 keeps: 97–98% of the swarm's
  brightness-error blotch variance is there (V-B7, V-C7).
- A decoupled history removes more at long histories: swarm 0.027 vs 0.050 with 10 mutations, close panels 0.009 vs
  0.034 (V-C7); plume and emerald (V-B8).
- The duplication cap biases these volumes (V-B8).
- DLSS RR darkens its input, by up to a third on some inputs (V-C7), so its relMSE partly ranks its brightness.
- Paths whose first vertex is a surface are not moved (V-C2: the cathedral walls keep their streaks).
- Motion: the construct's test with a moving camera and an animated medium at the shipped history (E7).

**8 Conclusion.** When to use mutations, when a decoupled history, and what to measure.

**Appendix.** The per-scene variety figures (one and two bounces, OptiX and RR), the bias table (V-C6), acceptance
rates, the cap-4 table if it does not fit in 6.3.

### Figures and tables

| Item | Source | New? |
|---|---|---|
| Teaser: the setup with the largest median cut, five denoisers, before/after, reference | E6 | new |
| Phase A condensed table | V1, V3, V7 | from the record |
| Moves diagram (the two path tags, which move acts where) | drawn from the two-bounce spec | new drawing |
| Bias suite table | V-C6 | from the record |
| Cost and equal-time table | V-C3, V-C4 | from the record |
| Main five-denoiser table, M cap 200 | E5, generated from the results file | new |
| Shipped-cap table and history chart | E5 | new |
| Five-denoiser strip, zoomed: cathedral (god rays), 48 lanterns (colour), the explosion at two bounces (self-emission), the swarm (one mutation is not enough) | E6 | new |
| Count strip | `figs/swarm_counts_denoisers.png` | approved |
| Galleries | `figs/gallery_mutations{,_rr}.png`, `figs/gallery_mutations_b2{,_rr}.png` | approved; lanterns and lamp-inside re-scored (E2) |
| Normalization maps | `figs/swarm_chat_maps.png` | approved |
| Per-scene figures (appendix) | `figs/variety_*.png`, `figs/variety_rr_*.png` | approved; two re-scored |

Tables of numbers are generated by a script from the results file and the recorded tables, not typed.

### Citations

From the existing `references.bib`: Bitterli et al. 2020, Lin et al. 2021, Falcor, OptiX (Chaitanya et al. 2017),
OIDN, NRD, SVGF (Schied et al. 2017), Kutz et al. 2017, Novák et al. 2014. Added, each checked first (criterion
5): Sawhney et al. 2024 and its supplement, Pauly et al. 2000, Ghost ReSTIR, RGB ReSTIR (GRIVAPP 2026), Zhou 2025
(thesis), Talbot et al. 2005, Kelemen et al. 2002, ReBLUR (Zhdan 2021), DLSS Ray Reconstruction, GVDB (Hoetzlein
2016); Lin et al. 2026 and Junkins et al. 2026 only if found online. FLIP and Zhu et al. 2023 leave with the old
paper.

## New experiments

### E1 — a four-denoiser capture (harness), and RR in its own graph

- A new module, `Scripts/denoiser_set.py`: a graph wrapper that prefixes the names of the passes a denoiser adds
  (vr_graph names them `Denoiser`, `NRDSurface`, `ModulateIllumination`, ... and NRD reads its method from
  `VR_NRD_METHOD`), and `add_denoisers(g, modes, color, ...)` -> `{mode: channel}`, wiring each denoiser exactly as
  `vr_graph.add_denoiser` wires it alone. `vr_graph.py` is not changed. Each denoiser keeps its own G-buffer and
  guides, as in its single runs (sharing them would be an optimisation gate 2 could no longer vouch for).
- OptiX, OIDN, NRD RELAX-SH and NRD REBLUR-SH share one graph (`correlation_pose.py VR_DENOISERS=optix,oidn,relax,reblur`),
  which also captures the raw ReSTIR output; the schedule lists the channels.
- **DLSS RR runs in its own graph, with the same seeds** (`VR_DENOISER=rr`, as its approved runs did): its G-buffer
  turns on the camera's Halton jitter, and the estimator's camera rays follow the camera jitter
  (`VolumeBase.slang`, `computeNonNormalizedRayDirPinholeOffset`), so in a shared graph it would change the frames
  the other four see. `add_denoisers` refuses `rr`.
- Tests (`tests/test_denoiser_set.py`): unique, prefixed pass names; shared passes keep their names; one channel per
  mode; each NRD instance runs its own method; an empty prefix wires exactly as `add_denoiser`; every G-buffer in the
  shared graph is unjittered.

### E2 — new references for the 17 gallery setups

All 17 gallery references predate the reference renderer's fix (a2a3aa8, 2026-10-10; they were rendered 28 September
to 3 October), not only the two with lights inside the medium. Each is re-rendered at 1080p with its own frames and
samples (2048 x 16 spp; the explosion 4096), the old one kept by renaming it to `ref_residual`. Each one's change
against the old reference is recorded (in-medium mean ratio and relMSE between them, and its own noise). The swarm's
and the storm's references were rendered after the fix and stay. The approved figures are re-scored against the new
references.

### E3 — the runs

- 19 setups × {M cap 200, shipped cap} × {plain, 5 mutations} = 76 configurations, each captured twice (the
  four-denoiser graph and RR's): 152 runs.
- The pass as shipped: all moves (four at one bounce, seven at two), after spatial reuse, coherent move choice,
  early rejection.
- 2 seeded chains x 1 capture per run, seeds from 100000 (the approved runs' chains 0 and 1, the ones their
  figures scored), plain and mutated sharing them; warm-up max(256, 4 x M cap) frames; scored on both captures, as
  V-C2. No transient captures, so nothing is pruned.
- Disk: the kept frames come to about 29 GB at 1080p. The queue starts only with at least 35 GB free; the user frees
  space if needed.
- The 17 gallery setups at 1080p (their references); the swarm and the storm at 960×540 (theirs).
- A resumable queue that keeps finished runs (the bias suite's rule).

### E4 — gates, in order

1. **Byte-identity:** mutations off, `mask_check.sh raw none` 300/300 after E1; a single-denoiser capture before vs
   after E1, bit-identical.
2. **The shared graph changes nothing:** on one scene with surfaces and a medium, each channel of the four-denoiser
   capture (and its raw frame) matches the single-denoiser capture with the same seeds: bit for bit where a second
   single capture reproduces the first bit for bit, otherwise within that run-to-run difference.
3. **Memory:** a smoke run at 1080p on the heaviest setup (`bunnycathedral_d0.3_b2`) of the four-denoiser graph
   peaks below 8 GB. If not: two two-denoiser graphs with the same seeds, each checked by gate 2.
4. **New references (E2)** checked before any run is scored against them.

### E5 — scoring

Per setup × history × config × denoiser: relMSE in the medium (`paper_figure.prepare`'s measure), the mean over the
kept frames; the reference's own relMSE (its two accumulations); the denoised mean brightness over the reference's
in the medium. (The raw ρ̄(8) needs tens of captures per run; the paper quotes the recorded runs for it.) One
results file
(`outputs/decorr/five_denoisers/results.json`) is the source for every new number in the paper.

### E6 — figures

The teaser, the five-denoiser strip and the history chart, from E3's captures (`paper_figure.prepare` for crops and
exposure, so they match the approved figures).

### E7 — the motion sentence, made true of the pass as shipped

The construct's motion tests ran with the four first-vertex moves only, though the scene renders two bounces. The
moving-camera test is rerun with all seven moves at the shipped cap, through OptiX, RR and raw (6 runs). The
animated-medium test is left out (user's choice: its frames 146-149 were deleted), and so is it from the sentence.
`cam_pose.py` moves from the scratchpad into `Scripts/`.

**Time:** about 13 hours of GPU time for E2, E3 and E7, run overnight; one Mogwai at a time, no build while it runs.

### Amendments (2026-10-20, after reading the harness)

- RR in its own graph (E1): the camera-jitter finding above. Twice the runs.
- All 17 gallery references re-rendered (E2), not two: all predate the fix.
- 2 chains x 1 capture, no pruning, a free-space check (E3); no raw ρ̄(8) in the new scoring (E5).
- The motion rerun covers the moving camera only (E7, user's choice).
- 1080p kept for the gallery setups (user's choice over 960x540).

## Writing and checking the paper

1. Copy `paper.tex` to `paper_v1_denoising_vs_sampling.tex`; write the new `paper.tex` to the outline.
2. Figures as PNG at print resolution in `figures/`, under new names.
3. Tables generated from the results file and the recorded tables.
4. Build with Tectonic; fix every error and undefined reference; check the page count and that each figure is
   legible at column width.
5. The numbers ledger: every number in the text against its source.
6. Hand the PDF and the source to the user.

## Risks

| Risk | Mitigation |
|---|---|
| Five denoisers at 1080p do not fit in 8 GB | Gate 3; two graphs with the same seeds. |
| RR's brightness swings between kept frames (0.72–1.00×, V-C7) | Report its mean brightness next to its relMSE; say what it does not rank. |
| A reference's own noise is a large part of a score (neon street: over half, V-C7) | Report each reference's own relMSE; do not rank within it. |
| New runs disagree with the approved gallery numbers (different runs; coherent moves since) | The text quotes the new table; each approved figure keeps its own numbers, re-scored where E2 changed the reference. |
| Overnight queue cut off | Resumable queue; finished runs kept. |
| A citation cannot be checked | Dropped (criterion 5). |

## Out of scope

- New moves, the surface-first-vertex moves, a decoupled-history default.
- New Phase A runs; the look-development scenes.
- Denoisers beyond the five.
- Submitting the paper anywhere.
