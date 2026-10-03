# Two-Bounce Mutations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Metropolis–Hastings mutation pass at two bounces. That means bounce-aware existing
moves plus three moves on the extra bounce (direction, distance, rebounce). Validate it, then
reproduce the denoised zoomed comparisons at 2 bounces for the explosion and four more scenes.

**Architecture:**
- The new moves live in `BounceMoves.slang`, included by `MutateSamples.cs.slang` only when
  `MAX_BOUNCES > 1`, so the one-bounce shader is textually the same and its output stays
  byte-identical.
- The pass sees a proposed extra bounce through a one-entry-override `IArrayDataProvider`. It writes
  the accepted entry back to the pixel's own slot; reuse always points a pixel's reservoir at its own
  slot (`TemporalReuse.cs.slang:482`, `SpatialReuse.cs.slang:302`).
- Visibility is cached per path segment.
- Plain 2-bounce ReSTIR is validated against the legacy build and a 2-bounce reference before any
  mutation code is trusted.

**Tech Stack:**
- Slang compute shaders, Falcor 9 (C++), Mogwai Python scripts;
- numpy unittest replicas of the shader math;
- bash study drivers in `outputs/decorr/`.

**Spec:** `docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md`

## Global Constraints

- **Never build while a study render runs.** Building copies shaders into
  `build/windows-vs2022/bin/Release/shaders`, which a running study compiles from. Before any build or
  GPU step:
  - check that `tasklist | grep -i mogwai` prints nothing;
  - check that no `run_*.sh` queue is waiting to start one.
- **Never edit a bash script that is running** (`run_study.sh`, `run_*.sh`): bash reads scripts
  incrementally.
- **Stopping processes.** Stop queue parent chains with TaskStop (the children survive). Kill Mogwai
  and `run_study.sh` by exact process role, never by a substring of a script name.
- **Commits** carry no Co-Authored-By trailer or other AI attribution.
- **Capture paths.** Capture needs an ABSOLUTE `VR_OUT_DIR` (use `cygpath -am`).
- **Edits.** Use the Edit tool for source edits, not python heredocs with backslashes.
- **Byte identity.** At one bounce, with mutations off and with mutations on, outputs must be
  byte-identical before vs after this change. At 2 bounces with mutations off, the same.
- **Vertex reuse stays off.** Mutations need `!mVertexReuse` and `mMaxBounces <= 2`.
- **No JangaFX datasets** (FirePlumeVDB, DustShockwaveVDB).
- **Build command:**
  `./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR Mogwai`
  run from the repo root.
- **Shader tests** (CPU, from `Source/RenderPasses/VolumetricReSTIR/Scripts/tests`):
  `python -m unittest discover -p "test_*.py"`. The 6 GPU smoke tests and the 4 capture `setUpClass`
  errors need an idle GPU. With a study running they fail without any captures, and that does not
  count as a regression.

## Review Focus

1. **A path ending in fire emission at x2 (tag 1)** packs x2 into `lightID`/`lightUV`. The light
   moves (`light`, `select`) must never act on it. Expected: they are not applicable, and the light
   fields only ever change by the tag-1 bounce moves. Pinned by Task 5's `mcap200_mut5light` on
   `explosiondusk_b2`, where emission paths are common: a light move rotating a packed position as
   an env direction would scatter fire across the frame and fail `bias_check`.
2. **The current extra bounce after an accepted bounce move** must be what every later p̂ evaluation
   in the chain sees, including the light and depth moves. Expected: the provider's override value
   tracks `xb`. This is pinned by Task 4's identity test at 2 bounces: mutations with only the light
   moves enabled must give the same 100-frame mean as mut0, through `bias_check`.
3. **A surface x2** (cathedral room, `wi_dist.w == kRayTMax`) must never be moved by a bounce move or
   by `select`, and a rebounce that reaches a surface must be rejected. Expected: no bias on the
   cathedral at 2 bounces. Pinned by Task 6's bias gate on `bunnycathedral_d0.3_b2`.
4. **One-bounce output** must not change by a single bit, with mutations off or on. Pinned by Task 4,
   Steps 1 and 9.
5. **ω stored near the horizon** (|z| → 0) must not drift during a chain. Expected: an angle error
   below 1e-4 rad for |z| ≥ 1e-3. Pinned by Task 3's round-trip test.

---

### Task 1: Harness knobs — bounce count, `_b<n>` labels, new strategy names

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/vr_graph.py` (the `MUTATION_STRATEGIES`
  dict, around line 482; the knob loop, around line 578)
- Modify: `outputs/decorr/run_study.sh` (`scene_env`, around lines 46–59). Only edit it while no
  `run_study.sh` is running; see Step 6.
- Test: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vr_graph_study.py` (`TestKnobs`)

**Interfaces:**
- Produces:
  - `VR_MAX_BOUNCES=<n>` sets `mParams["mMaxBounces"] = int(n)`;
  - `MUTATION_STRATEGIES` gains `"direction": 16, "distance": 32, "rebounce": 64` (bits 4–6);
  - `run_study.sh` maps a label part `b<n>` to `VR_MAX_BOUNCES=<n>`.

- [ ] **Step 1: Write the failing tests**

Add to `TestKnobs` in `test_vr_graph_study.py`, after `test_mutation_knobs`:

```python
    def test_bounce_knob(self):
        self.assertNotIn("mMaxBounces", self.restir_params())
        os.environ["VR_MAX_BOUNCES"] = "2"  # the paper's explosion renders 2 bounces
        params = self.restir_params()
        self.assertEqual(params["mMaxBounces"], 2)
        self.assertIsInstance(params["mMaxBounces"], int)

    def test_two_bounce_strategy_names(self):
        os.environ["VR_MUT_STRAT"] = "direction,distance,rebounce"  # MutateSamples.cs.slang bits 4-6
        self.assertEqual(self.restir_params()["mMutationStrategyMask"], 16 | 32 | 64)
        os.environ["VR_MUT_STRAT"] = "light,depth,select,flight,direction,distance,rebounce"
        self.assertEqual(self.restir_params()["mMutationStrategyMask"], 127)
```

Add `"VR_MAX_BOUNCES"` to `STUDY_VARS` (line 18–21) so `tearDown` clears it.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd Source/RenderPasses/VolumetricReSTIR/Scripts/tests && python -m unittest test_vr_graph_study -k bounce_knob -k two_bounce_strategy`
Expected: FAIL, with `KeyError: 'mMaxBounces'` and with `ValueError: VR_MUT_STRAT: unknown strategy 'direction'`.

- [ ] **Step 3: Implement**

In `vr_graph.py`, replace the dict:

```python
MUTATION_STRATEGIES = {"light": 1, "depth": 2, "select": 4, "flight": 8,  # MutateSamples.cs.slang's strategy bits
                       # two bounces (BounceMoves.slang): rotate the extra bounce's direction, step its distance,
                       # redraw it from the phase function and free flight
                       "direction": 16, "distance": 32, "rebounce": 64}
```

In the knob loop, add an entry after `("mInitialM", "VR_INITIAL_M", int),`:

```python
                              # Bounces (the study runs 1; the paper's explosion 2). Mutations support <= 2.
                              ("mMaxBounces", "VR_MAX_BOUNCES", int),
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd Source/RenderPasses/VolumetricReSTIR/Scripts/tests && python -m unittest test_vr_graph_study`
Expected: `OK`, with 25 tests (23 before plus 2).

- [ ] **Step 5: Commit the Python part**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/vr_graph.py Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_vr_graph_study.py
git commit -m "vr_graph: VR_MAX_BOUNCES and the two-bounce strategy names (direction, distance, rebounce)"
```

- [ ] **Step 6: `run_study.sh` label suffix (only while no `run_study.sh` runs)**

Check first: `ps -ef | grep -c "[r]un_study.sh"` must print 0. Then, in `scene_env`'s `case`, add
after the `d*)` line:

```bash
            b*) out="$out VR_MAX_BOUNCES=${m#b}" ;;
```

Verify:

```bash
cd /c/research/Denoising-VolumetricReSTIR
bash -c 'eval "$(sed -n "/^scene_env()/,/^}/p" outputs/decorr/run_study.sh)"; scene_env explosiondusk_b2; scene_env bunnyback_g0.8_b2; scene_env bunnycathedral_d0.3'
```

Expected:

```
VR_SCENE=explosiondusk VR_MAX_BOUNCES=2
VR_SCENE=bunnyback VR_PHASE_G=0.8 VR_MAX_BOUNCES=2
VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3
```

Commit:

```bash
git add -f outputs/decorr/run_study.sh
git commit -m "run_study.sh: a _b<n> label part sets VR_MAX_BOUNCES"
```

---

### Task 2: Step 0 — validate plain 2-bounce ReSTIR (GPU, no build)

**Files:**
- Create: `outputs/decorr/legacy_explosion.py` (the legacy build's capture of `run_LGHExplosion.py`)
- Create: `outputs/decorr/run_b2_gate.sh`
- Create: `outputs/decorr/compare_legacy.py`
- Modify: `docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md` (append a
  "Verification results" section with V-C0)

**Interfaces:**
- Consumes: Task 1's `VR_MAX_BOUNCES` and `_b2` labels.
- Produces:
  - `outputs/decorr/explosiondusk_b2/ref/` (a 2-bounce reference, 2048 frames);
  - `explosiondusk_b2/noreuse`, `explosiondusk_b2/shipped` (scored study runs);
  - `outputs/decorr/legacy_b2/legacy_t750_le1.AccumulatePass.output.0.exr`.

Precondition: the queue is paused (Global Constraints), and Task 1 Step 6 is done.

- [ ] **Step 1: Write the legacy capture script**

`outputs/decorr/legacy_explosion.py`:

```python
# The legacy (Falcor 4) build rendering legacy run_LGHExplosion.py as written, plus a capture: the ground truth
# for the port's explosiondusk. Run from legacy/Bin/x64/Release with
# FALCOR_MEDIA_FOLDERS=<repo>/VolumetricReSTIRData;<repo>/legacy/Media.
# LEG_OUT (absolute dir), LEG_FRAMES (accumulated frames), LEG_BOUNCES (the script's 2), LEG_TSCALE, LEG_LESCALE.
from falcor import *
import os
OUT = os.environ["LEG_OUT"]
TSCALE = float(os.environ.get("LEG_TSCALE", "750"))
LESCALE = float(os.environ.get("LEG_LESCALE", "1"))
FRAMES = int(os.environ.get("LEG_FRAMES", "64"))
BOUNCES = int(os.environ.get("LEG_BOUNCES", "2"))

def render_graph():
    g = RenderGraph("Volumetric ReSTIR")
    loadRenderPassLibrary("AccumulatePass.dll")
    loadRenderPassLibrary("VolumetricReSTIR.dll")
    g.addPass(createPass("VolumetricReSTIR", {"mParams": VolumetricReSTIRParams(mMaxBounces=BOUNCES)}), "VolumetricReSTIR")
    g.addPass(createPass("AccumulatePass", {"enableAccumulation": True}), "AccumulatePass")
    g.addEdge("VolumetricReSTIR.accumulated_color", "AccumulatePass.input")
    g.markOutput("AccumulatePass.output")
    return g

m.loadScene("default.obj")
m.scene.setEnvMap("skylight-dusk.exr")
m.scene.setEnvMapRotation(float3(13,136,340))
m.addGVDBVolume(sigma_a=float3(10,10,10), sigma_s=float3(10,10,10), g=0.0, dataFile="LGHExplosion/LGHExplosion.183", numMips=4, densityScale = 0.02, hasVelocity=False, hasEmission=True, LeScale=LESCALE, temperatureCutoff = 0.0, temperatureScale = TSCALE)
m.scene.camera.position = float3(-29.487331,10.408340,0.493491)
m.scene.camera.target = float3(-28.505859,10.597045,0.460278)
m.scene.camera.up = float3(-0.000909,1.000000,0.000030)
m.addGraph(render_graph())
m.resizeSwapChain(960, 540)
m.ui = False
fc.ui = False
t.pause()
t.frame = 0
fc.outputDir = OUT
for i in range(FRAMES):
    renderFrame()
fc.baseFilename = "legacy_t%d_le%g" % (TSCALE, LESCALE)
fc.capture()
exit()
```

- [ ] **Step 2: Write the gate driver**

`outputs/decorr/run_b2_gate.sh`:

```bash
#!/bin/bash
# Step 0 of the two-bounce spec: plain 2-bounce ReSTIR in the port vs the legacy build and a 2-bounce reference.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
echo "[$(date +%H:%M:%S)] b2 gate start" >> $LOG
# 1. Legacy, 2 bounces, 1024 accumulated frames at 960x540.
L="$R/$O/legacy_b2"; mkdir -p "$L"
( cd legacy/Bin/x64/Release && FALCOR_MEDIA_FOLDERS="$(cygpath -w "$R/VolumetricReSTIRData");$(cygpath -w "$R/legacy/Media")" \
  LEG_OUT="$(cygpath -w "$L")" LEG_FRAMES=1024 LEG_BOUNCES=2 timeout 1800 ./Mogwai.exe --script "$(cygpath -w "$R/$O/legacy_explosion.py")" > "$L/run.log" 2>&1 )
echo "[$(date +%H:%M:%S)] legacy b2: $(ls "$L"/*.exr 2>/dev/null | wc -l) exr" >> $LOG
# 2. The port's 2-bounce reference at the same size (study reference: 1080p, 2048 frames).
P="$R/$O/explosiondusk_b2/ref960"; mkdir -p "$P"
( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
  VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_MODE=reference VR_FRAMES=1024 VR_SPP=4 VR_DISPLAY=960x540 \
  VR_OUT_DIR="$(cygpath -am "$P")" VR_TAG=p timeout 3600 ./build/windows-vs2022/bin/Release/Mogwai.exe \
  --script 'C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py' > "$P/run.log" 2>&1 )
echo "[$(date +%H:%M:%S)] port b2 ref960: $(ls "$P"/*.exr 2>/dev/null | wc -l) exr" >> $LOG
# 3. The study's 2-bounce reference, no reuse and shipped (scored against the reference).
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048 STUDY_TIMEOUT=7200
bash $O/run_study.sh refs explosiondusk_b2 2>&1 | tee -a $LOG
bash $O/run_study.sh one explosiondusk_b2 noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1 2>&1 | tee -a $LOG
bash $O/run_study.sh one explosiondusk_b2 shipped 2>&1 | tee -a $LOG
echo "[$(date +%H:%M:%S)] b2 gate done" >> $LOG
```

- [ ] **Step 3: Write the comparison**

`outputs/decorr/compare_legacy.py`:

```python
"""The port's 2-bounce explosion against the legacy build's: sky (top-left patch) and in-medium mean, per channel.

    python compare_legacy.py <legacy exr> <port exr> [<medium mask .npy>]
Prints relative differences; exits 1 if the sky differs by more than 0.5% or the medium mean by more than 2%.
"""
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc


def main(argv):
    leg = mc.read_exr(argv[0])[..., :3][..., ::-1].astype(np.float64)
    port = mc.read_exr(argv[1])[..., :3][..., ::-1].astype(np.float64)
    sky = lambda im: im[10:40, 20:120].reshape(-1, 3).mean(0)
    lum_l, lum_p = leg @ mc.Y_RGB, port @ mc.Y_RGB
    # The medium: pixels whose luminance differs from the sky's by more than 5% in the legacy image.
    mask = np.abs(lum_l / (sky(leg) @ mc.Y_RGB) - 1) > 0.05
    ds = sky(port) / sky(leg) - 1
    dm = port[mask].mean(0) / leg[mask].mean(0) - 1
    print("sky rel diff %s; medium (%d px) rel diff %s" % (np.round(ds, 4), mask.sum(), np.round(dm, 4)))
    return 0 if np.all(np.abs(ds) < 0.005) and np.all(np.abs(dm) < 0.02) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the gate**

Run (in the background, after the queue is paused):
`bash outputs/decorr/run_b2_gate.sh > outputs/decorr/b2_gate.stdout 2>&1`
Expected in `b2.log`:
- legacy b2: 1 exr;
- port b2 ref960: 2 exr;
- `[study] explosiondusk_b2/noreuse …` and `[study] explosiondusk_b2/shipped …` lines.

- [ ] **Step 5: Compare against the legacy build**

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr
python compare_legacy.py legacy_b2/legacy_t750_le1.AccumulatePass.output.0.exr "$(ls explosiondusk_b2/ref960/p.Accum.output.*.exr | sort -t. -k4 -n | tail -1)"
```

Expected: exit 0. The legacy image is 1024 frames of ReSTIR, so its own noise sets the floor. If the
medium differs by more than 2%, it is a port bug: stop and use superpowers:systematic-debugging
before Task 4. The suspects, in order:
1. the extra-bounce encoding (`decodeWiDist`);
2. the 1/d² of an emitting x2;
3. the env evaluation at x2.

- [ ] **Step 6: Bias of plain 2-bounce reuse**

```bash
python bias_check.py . explosiondusk_b2/noreuse explosiondusk_b2/shipped
python -c "import json; print(json.load(open('explosiondusk_b2/shipped/c.corr.json'))['reference']['regions'])"
```

Expected: `shipped` against `noreuse` within 3 chain-level standard errors per channel, and the
reference region bias within ±2%. A larger value is a port bug in 2-bounce reuse; debug it before
Task 4.

- [ ] **Step 7: Record and commit**

Append to the spec:

```markdown
## Verification results

### V-C0 — plain 2-bounce ReSTIR (date)
- Legacy vs port, explosion, 2 bounces, 960x540, 1024 frames: sky <numbers>, medium <numbers>.
- explosiondusk_b2 shipped vs noreuse (bias_check): <per-channel rel diff ± s.e.>; vs the 2-bounce reference: <region bias>.
```

(Replace each `<numbers>` with the printed values; the step is not done until they are filled in.)

```bash
git add -f outputs/decorr/legacy_explosion.py outputs/decorr/run_b2_gate.sh outputs/decorr/compare_legacy.py
git add docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md
git commit -m "Two-bounce gate: plain 2-bounce ReSTIR vs the legacy build and a 2-bounce reference (V-C0)"
```

---

### Task 3: CPU replicas of the bounce-move math

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_mutation_measures.py` (append)

**Interfaces:**
- Produces (Python replicas, mirrored by Task 4's shader functions):
  - `encode_wi_dist(w, d) -> (3,)` / `decode_wi_dist(e) -> (w, d)` — `ReSTIRHelper.slang`;
  - `hg_pdf(cos, g)` / `hg_sample(wo, g, u) -> wi` — `VolumeBase.slang` (`PhaseHG`, `Sample_p`);
  - `isotropic_step(unit, lo, hi, n) -> (n,3)` — `BounceMoves.slang` `isotropicStep`;
  - `rebounce_step(state, target, sigma, R, g, u)` — `BounceMoves.slang`'s rebounce on a homogeneous
    ball.
- Already covered: `rotateDirection` is the env move's rotation line for line. Its solid-angle
  symmetry is pinned by the existing `TestEnvMap.test_rotation_proposal_density_depends_only_on_the_angle`
  and `test_rotation_proposal_azimuth_is_uniform`, so this task adds no test for it.

- [ ] **Step 1: Write the failing tests**

Append to `test_mutation_measures.py`:

```python
# ---- Two bounces (spec 2026-10-03-two-bounce-mutations-design.md) ----

def encode_wi_dist(w, d):
    """ReSTIRHelper.slang encodeWiDist: (w.x, w.y, +-d), the sign carrying w.z's (float32)."""
    w = np.asarray(w, f32)
    return np.array([w[0], w[1], -d if w[2] < 0 else d], f32)


def decode_wi_dist(e):
    """ReSTIRHelper.slang decodeWiDist(input, false): w.z = +-sqrt(1 - x^2 - y^2) (NaN -> 0), d = |input.z|."""
    e = np.asarray(e, f32)
    z = np.sqrt(f32(1) - (e[0] * e[0] + e[1] * e[1]))
    if np.isnan(z):
        z = f32(0)
    if e[2] < 0:
        z, d = -z, -e[2]
    else:
        d = e[2]
    return np.array([e[0], e[1], z], f32), d


def hg_pdf(cos, g):
    """VolumeBase.slang PhaseHG."""
    denom = 1 + g * g + 2 * g * cos
    return (1 - g * g) / (4 * np.pi * denom * np.sqrt(denom))


def coordinate_system(v1):
    """VolumeBase.slang CoordinateSystem."""
    if abs(v1[0]) > abs(v1[1]):
        v2 = np.array([-v1[2], 0, v1[0]]) / np.sqrt(v1[0] ** 2 + v1[2] ** 2)
    else:
        v2 = np.array([0, v1[2], -v1[1]]) / np.sqrt(v1[1] ** 2 + v1[2] ** 2)
    return v2, np.cross(v1, v2)


def hg_sample(wo, g, u):
    """VolumeBase.slang MediumInteraction::Sample_p: wi with density PhaseHG(dot(wo, wi), g)."""
    if abs(g) < 1e-3:
        cos = 1 - 2 * u[0]
    else:
        sq = (1 - g * g) / (1 + g - 2 * g * u[0])
        cos = -(1 + g * g - sq * sq) / (2 * g)
    sin = np.sqrt(max(0.0, 1 - cos * cos))
    phi = 2 * np.pi * u[1]
    v1, v2 = coordinate_system(wo)
    return sin * np.cos(phi) * v1 + sin * np.sin(phi) * v2 + cos * wo


def isotropic_step(unit, lo, hi, n):
    """BounceMoves.slang isotropicStep: unit * |kelemenStep(lo, hi)| times a uniform direction (sample_sphere)."""
    length = unit * np.abs(kelemen_step(lo, hi, RNG.random((n, 2))))
    u = RNG.random((n, 2))
    z = 1 - 2 * u[:, 0]
    r = np.sqrt(np.maximum(0, 1 - z * z))
    phi = 2 * np.pi * u[:, 1]
    return length[:, None] * np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=-1)


def rebounce_q(cos, d, sigma, R, g):
    """BounceMoves.slang rebounceQ on a homogeneous ball of radius R around x1: phase x sigma T, per sr per length."""
    return np.where((d > 0) & (d < R), hg_pdf(cos, g) * sigma * np.exp(-sigma * d), 0.0)


def rebounce_step(state, target, sigma, R, g, u):
    """The rebounce move on (cos, d) with wo = +z: phase-sampled direction, free-flight distance, independence
    acceptance min(1, p(z) q(x) / (p(x) q(z))); a draw past R (escape) is rejected."""
    wi = hg_sample(np.array([0.0, 0.0, 1.0]), g, RNG.random(2))
    d = -np.log(1 - RNG.random()) / sigma
    if d >= R:
        return state
    z = (wi[2], d)
    qx, qz = rebounce_q(state[0], state[1], sigma, R, g), rebounce_q(z[0], z[1], sigma, R, g)
    px, pz = target(*state), target(*z)
    return z if pz > 0 and u * px * qz < pz * qx else state


class TestTwoBounceMeasures(unittest.TestCase):
    def test_wi_dist_round_trips(self):
        for _ in range(20000):
            w = RNG.normal(size=3)
            w /= np.linalg.norm(w)
            if abs(w[2]) < 1e-3:
                continue
            d = RNG.uniform(0.01, 50.0)
            w2, d2 = decode_wi_dist(encode_wi_dist(w, d))
            self.assertLess(np.arccos(np.clip(np.dot(w, w2), -1, 1)), 1e-4)
            self.assertAlmostEqual(float(d2), d, delta=1e-5 * d)

    def test_hg_sample_follows_its_pdf(self):
        g, wo = 0.6, np.array([0.0, 0.6, 0.8])
        cos = np.array([np.dot(wo, hg_sample(wo, g, RNG.random(2))) for _ in range(100000)])
        edges = np.linspace(-1, 1, 41)
        hist, _ = np.histogram(cos, edges, density=True)
        mid = 0.5 * (edges[1:] + edges[:-1])
        np.testing.assert_allclose(hist, 2 * np.pi * hg_pdf(mid, g), rtol=0.08, atol=0.01)

    def test_isotropic_step_is_symmetric(self):
        # p(x -> z) depends on z - x only through |z - x| and a uniform direction: symmetric in volume.
        s = isotropic_step(0.1, 0.5, 8.0, 200000)
        axis = np.array([0.3, -0.5, 0.81])
        axis /= np.linalg.norm(axis)
        proj = s @ axis
        self.assertLess(ks_distance(proj, -proj), 0.01)
        self.assertLess(abs(proj.mean()), 0.01 * np.abs(proj).mean())

    def test_rebounce_density_mass_is_one_minus_escape(self):
        sigma, R, g = 0.7, 3.0, 0.5
        cos = np.linspace(-1, 1, 2001)
        d = np.linspace(0, R, 3001)
        C, D = np.meshgrid(cos, d, indexing="ij")
        mass = np.trapz(np.trapz(rebounce_q(C, D, sigma, R, g), d, axis=1), cos) * 2 * np.pi
        self.assertAlmostEqual(mass, 1 - np.exp(-sigma * R), delta=2e-3)
        # Emission at x2: q / d^2 is a density in volume with the same mass (dV = d^2 domega dd).
        n = 400000
        p = RNG.uniform(-R, R, (n, 3))
        r = np.linalg.norm(p, axis=1)
        qv = rebounce_q(p[:, 2] / np.maximum(r, 1e-12), r, sigma, R, g) / np.maximum(r, 1e-12) ** 2
        self.assertAlmostEqual(qv.mean() * (2 * R) ** 3, 1 - np.exp(-sigma * R), delta=0.03)

    def test_rebounce_keeps_the_target(self):
        sigma, R, g = 0.9, 2.5, 0.4

        def target(cos, d):  # a 2-bounce-like p_hat: forward lobe times a light falling off with depth
            return (1.2 + cos) ** 2 * np.exp(-0.4 * d) * (d < R)

        x, cs, ds = (0.5, 1.0), [], []
        for i in range(200000):
            x = rebounce_step(x, target, sigma, R, g, RNG.random())
            if i > 1000:
                cs.append(x[0])
                ds.append(x[1])
        # The target's marginal of cos (per steradian -> per unit cos: the same, the azimuth is uniform).
        grid = np.linspace(-1, 1, 801)
        w = (1.2 + grid) ** 2
        cdf = np.cumsum(w) / w.sum()
        ref = np.interp(RNG.random(50000), cdf, grid)
        self.assertLess(ks_distance(np.array(cs), ref), 0.02)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd Source/RenderPasses/VolumetricReSTIR/Scripts/tests && python -m unittest test_mutation_measures.TestTwoBounceMeasures`
Expected: ERROR, with `NameError` for the replica functions if Step 1's code is pasted without them.
Paste the class first and the functions second, so the failure is observed.

- [ ] **Step 3: Paste the replica functions (Step 1's first block) and run again**

Run: `python -m unittest test_mutation_measures -v`
Expected: all of `TestTwoBounceMeasures` pass, and every earlier test still passes. If
`test_rebounce_keeps_the_target` fails, check the acceptance ratio's q(x)/q(z) orientation against
`flight_step`.

- [ ] **Step 4: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_mutation_measures.py
git commit -m "test_mutation_measures: two-bounce replicas (wi_dist round trip, HG sampling, isotropic step, rebounce density and acceptance)"
```

---

### Task 4: The bounce moves in the mutation pass

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/BounceMoves.slang`
- Modify: `Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang`
- Modify: `Source/RenderPasses/VolumetricReSTIR/VolumetricReSTIR.cpp`:
  - `kMutationStatNames`, around line 64;
  - `mutationsActive`, around line 568;
  - the stats log, around line 645;
  - the `MAX_BOUNCES` update block, around line 833;
  - the strategy UI, around line 2157.
- Modify: `Source/RenderPasses/VolumetricReSTIR/VolumetricReSTIR.h` (the `mutationsActive` doc and
  the `mMutationStrategyMask` comment)
- Modify: `Source/RenderPasses/VolumetricReSTIR/CMakeLists.txt` (add `BounceMoves.slang` to the
  shader list, next to `MutateSamples.cs.slang`)
- Create: `outputs/decorr/identity_capture.sh`

**Interfaces:**
- Consumes: Task 1's strategy bits (16/32/64) and Task 3's replicas, which the shader functions
  mirror one to one.
- Produces:
  - strategy bits 4/5/6 honoured by the pass;
  - stats 49–58 (names below);
  - `mutationsActive()` true for `mMaxBounces <= 2`.

- [ ] **Step 1: Baselines with the current binary (before any build)**

`outputs/decorr/identity_capture.sh`:

```bash
#!/bin/bash
# Byte-identity captures for the two-bounce change: outputs/decorr/identity/<tag>/<config>/*.exr.
# Small and deterministic: 640x360, 1 chain x 2 frames, 32 warm-up frames.
set -u
tag=$1
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
if tasklist 2>/dev/null | grep -qi mogwai; then echo "Mogwai is running; abort"; exit 1; fi
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight VR_MUT_STATS=0 VR_MUT_AFTER_SPATIAL=1"
cap() {  # name, env...
    local d="$R/outputs/decorr/identity/$tag/$1"; shift
    mkdir -p "$d"
    ( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
      export VR_DISPLAY=640x360 VR_CHAINS=1 VR_PER_CHAIN=2 VR_WARM=32 VR_SPACING=1 VR_IDS=0 "$@"
      VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe \
        --script 'C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py' > "$d/run.log" 2>&1 )
    echo "$tag/$(basename "$d"): $(ls "$d"/*.exr 2>/dev/null | wc -l) exr"
}
# shellcheck disable=SC2086
cap b1_mut0_explosion VR_SCENE=explosiondusk VR_MTHRESH=200
# shellcheck disable=SC2086
cap b1_mut5_explosion VR_SCENE=explosiondusk VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
cap b1_mut5_softbox VR_SCENE=bunnysoftbox VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
cap b1_mut5_cathedral VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_MTHRESH=200 $MUT
# shellcheck disable=SC2086
cap b2_mut0_explosion VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_MTHRESH=200
# shellcheck disable=SC2086
cap b2_mut0_cathedral VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_MAX_BOUNCES=2 VR_MTHRESH=200
```

Run: `bash outputs/decorr/identity_capture.sh before`
Expected: six lines, each `before/<name>: 2 exr`.

- [ ] **Step 2: Create `BounceMoves.slang`**

```slang
/** Two-bounce moves for MutateSamples.cs.slang (docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md),
    included only when MAX_BOUNCES > 1, so the one-bounce pass is textually unchanged.

    A 2-bounce sample is x1 at `depth` on the camera ray plus one extra bounce:
      - path tag 0: the pixel's ExtraBounceReservoir holds (omega, d) from x1 (encodeWiDist), the light connects at
        x2 = x1 + d omega, and p_hat is a density in dt1 domega dd (light measure); d == kRayTMax marks a surface x2;
      - path tag 1: x2 emits; its world position is packed into lightID / lightUV (encodeEmissivePosition) and p_hat
        carries 1/d^2: a density in dt1 dV(x2). There is no light sample.
    Moves (fixed strategy probabilities, an inapplicable pick a self-transition, as in the pass):
      - kDirection: rotate omega by a Kelemen angle about itself (symmetric in solid angle; the env move's math) --
        tag 1: an isotropic Kelemen step of x2 (symmetric in volume);
      - kDistance: d + a Kelemen step (symmetric in dd), tag 0 only;
      - kRebounce: an independence proposal, omega from the phase function at x1 and d by free flight along it
        (q = phase sigma_t T, / d^2 for tag 1), accepted with min(1, p_hat(z) q(x) / (p_hat(x) q(z))); a draw that
        escapes or reaches a surface is rejected. q is evaluated at STORED states (encoded then decoded), so the
        ratio sees what p_hat sees.
    Surface x2 vertices are never moved and never proposed: the kernel restricted to medium x2 keeps p_hat.
    Replicas: Scripts/tests/test_mutation_measures.py, TestTwoBounceMeasures. */

static const uint kDirection = 4;
static const uint kDistance = 5;
static const uint kRebounce = 6;

/// This pixel's extra-bounce entry as the chain's current state (or a proposal); every other entry from the buffer.
struct OverrideArrayDataProvider : IArrayDataProvider
{
    RWStructuredBuffer<ExtraBounceReservoir> data;
    int index;
    ExtraBounceReservoir value;
    ExtraBounceReservoir getData(int i) { return i == index ? value : data[i]; }
};

/// The extra bounce as the moves see it.
struct Bounce
{
    bool present;  // one extra bounce
    bool emissive; // path tag 1: x2 is a stored position
    bool surface;  // tag 0 with x2 on a surface
    float3 x2;     // tag 1: the stored position
    float3 dir;    // omega (tag 0) or normalize(x2 - x1) (tag 1)
    float dist;    // d (tag 0) or |x2 - x1| (tag 1)
};

Bounce readBounce(Reservoir r, ExtraBounceReservoir b, float3 x1)
{
    Bounce o;
    o.present = decodeMaxIndirectBounces(r.sampledPixel) == 1;
    o.emissive = o.present && decodePathTag(r.sampledPixel) == 1;
    o.surface = false;
    o.x2 = x1;
    o.dir = float3(0.f, 0.f, 1.f);
    o.dist = 0.f;
    if (!o.present) return o;
    if (o.emissive)
    {
        o.x2 = decodeEmissivePosition(r.lightID, r.lightUV);
        const float3 v = o.x2 - x1;
        o.dist = length(v);
        o.dir = v / o.dist;
        return o;
    }
    const float4 wd = decodeWiDist(b.wi_dist, false);
    o.surface = wd.w == kRayTMax;
    o.dir = wd.xyz;
    o.dist = wd.w;
    o.x2 = x1 + o.dist * o.dir;
    return o;
}

/// The bounce moves that can act on this sample (masked by the caller with gStrategyMask).
uint bounceMoves(Reservoir r, ExtraBounceReservoir b)
{
    if (decodeMaxIndirectBounces(r.sampledPixel) != 1) return 0u;
    if (decodePathTag(r.sampledPixel) == 1) return (1u << kDirection) | (1u << kRebounce);
    if (decodeWiDist(b.wi_dist, false).w == kRayTMax) return 0u; // x2 on a surface: not moved
    return (1u << kDirection) | (1u << kDistance) | (1u << kRebounce);
}

/// The ray of the extra bounce from x1 along dir, up to the first surface (the extra bounce's distance sampler
/// in ComputeInitialSample.slang stops there too).
VolRay bounceRay(float3 x1, float3 dir)
{
#ifdef SURFACE_SCENE
    const float tMax = FindSurfaceHit(x1, dir, 0, kRayTMax).rayT;
#else
    const float tMax = kRayTMax;
#endif
    return { x1, dir, 0, tMax };
}

/// The env move's rotation (MutateSamples.cs.slang, kLight), here for omega: symmetric in solid angle.
float3 rotateDirection(float3 w, inout SampleGenerator sg)
{
    const float theta = abs(kelemenStep(gDirStepMin, gDirStepMax, sampleNext2D(sg)));
    const float phi = M_2PI * sampleNext1D(sg);
    const float3 t = perp_stark(w);
    const float3 b = cross(w, t);
    return normalize(cos(theta) * w + sin(theta) * (cos(phi) * t + sin(phi) * b));
}

/// A Kelemen length (in ray-march steps) in a uniform direction: symmetric in volume.
float3 isotropicStep(float unit, inout SampleGenerator sg)
{
    const float len = unit * abs(kelemenStep(gDepthStepMin, gDepthStepMax, sampleNext2D(sg)));
    return len * sample_sphere(sampleNext2D(sg));
}

/// q of the rebounce move at a stored extra bounce: phase(wo, dir) times the free-flight density at dist along the
/// bounce ray (per steradian per length); tag 1 divides by dist^2, p_hat being a density in volume there.
float rebounceQ(float3 x1, float3 wo, float3 dir, float dist, bool emissive, inout SampleGenerator sg)
{
    MediumInteraction mi = { x1, wo, gScene.volumeDesc.PhaseFunctionConstantG, true };
    FreeFlightPdfAdapterGVDB e;
    const float q = mi.phaseFunction(wo, dir) * flightPdf(bounceRay(x1, dir), dist, sg, e);
    return emissive ? q / (dist * dist) : q;
}

/// The rebounce draw: omega from the phase function, d from the free-flight sampler along it. False on an escape
/// or a surface: no medium vertex, a rejected proposal.
bool proposeRebounce(float3 x1, float3 wo, inout SampleGenerator sg, out float3 dir, out float dist)
{
    MediumInteraction mi = { x1, wo, gScene.volumeDesc.PhaseFunctionConstantG, true };
    dir = float3(0.f, 0.f, 1.f);
    mi.Sample_p(wo, dir, sampleNext2D(sg));
    const VolRay r = bounceRay(x1, dir);
    float hit[MaxInitialSampleCount];
    float qs[MaxInitialSampleCount];
    float trs[MaxInitialSampleCount];
    SampleMediumAnalyticGeneric(r, sg, false, hit, gFlightMipLevel, qs, trs, 1);
    dist = hit[0];
    return hit[0] > 0.f && hit[0] < r.tMax && hit[0] < kRayTMax;
}
```

- [ ] **Step 3: Wire it into `MutateSamples.cs.slang`**

Make these edits, each with the Edit tool. Every one-bounce line stays textually as it is; new lines
go inside `#if MAX_BOUNCES > 1`.

(a) Header doc: append before the closing `*/`:

```
    Two bounces (spec 2026-10-03-two-bounce-mutations-design.md): with MAX_BOUNCES > 1 the light moves act at the
    vertex the light connects from (x2 after an extra bounce), and BounceMoves.slang adds direction, distance and
    rebounce moves on the extra bounce; the pass writes the accepted extra bounce back to the pixel's own entry.
```

(b) Replace `StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;` with:

```slang
#if MAX_BOUNCES > 1
RWStructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs; // the bounce moves write the pixel's entry back
#else
StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
#endif
```

(c) Replace the `CachingVisibilityProvider` body with one that adds segment 1:

```slang
struct CachingVisibilityProvider : IExternalVisibilityProvider
{
    float data = -1.f;  // segment 0: camera -> x1
    float data1 = -1.f; // segment 1: x1 -> x2 (two bounces)
    float getVisibility(int bounce) { return bounce == 0 ? data : (bounce == 1 ? data1 : -1.f); }
    [mutating] void putVisibility(int bounce, float visibility) { if (bounce == 0) data = visibility; else if (bounce == 1) data1 = visibility; }
    [mutating] void Initialize() { data = -1.f; data1 = -1.f; }
};
```

(d) After `kelemenStep`'s definition, include the bounce moves and define the provider type:

```slang
#if MAX_BOUNCES > 1
#include "BounceMoves.slang"
typedef OverrideArrayDataProvider MutationDataProvider;
#else
typedef StructuredBufferArrayDataProvider MutationDataProvider;
#endif
```

Move `applicable()` below this include. Its new body depends on `bounceMoves`.

(e) Change `applicable` to take the entry, and extend it under `#if`:

```slang
uint applicable(Reservoir r, ExtraBounceReservoir b)
{
    const bool selfEmission = r.lightID == kSelfEmissionLightID;
    const bool inMedium = r.depth != kRayTMax;
#ifdef SURFACE_SCENE
    const bool hasShadingPoint = true;     // kRayTMax = surface hit; an invalid hit gives p_hat = 0
#else
    const bool hasShadingPoint = inMedium; // kRayTMax = background, no light sample
#endif
    const int lightCount = (int)gScene.getLightCount();
    const bool env = r.lightID < 0 && !selfEmission; // -1; delta (analytic) lights are never moved
    const bool emissiveTri = r.lightID >= lightCount;
    uint mask = 0;
    if (hasShadingPoint && !selfEmission && (env || emissiveTri)) mask |= 1u << kLight;
    if (inMedium) mask |= (1u << kDepth) | (1u << kFlight);
    // Any light sample in the medium (a point light too), but not an emission path: its p_hat is the medium's
    // own emission, a kind the proposal never draws.
    const bool lightSample = r.lightID == -1 || r.lightID >= 0;
    if (inMedium && lightSample && decodePathTag(r.sampledPixel) != 1) mask |= 1u << kSelect;
#if MAX_BOUNCES > 1
    if (decodeMaxIndirectBounces(r.sampledPixel) == 1)
    {
        // Tag 1: lightID / lightUV hold x2's position, not a light. A surface x2: the re-selection needs a medium vertex.
        if (decodePathTag(r.sampledPixel) == 1) mask &= ~((1u << kLight) | (1u << kSelect));
        else if (decodeWiDist(b.wi_dist, false).w == kRayTMax) mask &= ~(1u << kSelect);
        if (inMedium) mask |= bounceMoves(r, b);
    }
#endif
    return mask & gStrategyMask;
}
```

(f) `pHat`: change the provider parameter type from `StructuredBufferArrayDataProvider dp` to
`MutationDataProvider dp`.

(g) In `main`, replace

```slang
    const uint moves = applicable(r);
```

with

```slang
#if MAX_BOUNCES > 1
    ExtraBounceReservoir xb = gCurExtraBounceReservoirs[r.extraBounceStartId]; // the chain's extra bounce
#else
    ExtraBounceReservoir xb = {}; // no extra bounce at one bounce
#endif
    const uint moves = applicable(r, xb);
```

and replace

```slang
    StructuredBufferArrayDataProvider dp;
    dp.data = gCurExtraBounceReservoirs;
```

with

```slang
    MutationDataProvider dp;
    dp.data = gCurExtraBounceReservoirs;
#if MAX_BOUNCES > 1
    dp.index = r.extraBounceStartId; // every p_hat in the chain sees x's extra bounce, not the buffer's
    dp.value = xb;
#endif
```

After `float primaryVis = vis0.data;`, add:

```slang
#if MAX_BOUNCES > 1
    float bounceVis = vis0.data1; // segment 1 of x
#endif
```

(h) In the loop, replace `if ((applicable(x) & (1u << s)) == 0) continue;` with:

```slang
        if ((applicable(x, xb) & (1u << s)) == 0)
        {
        #if MAX_BOUNCES > 1
            if (s >= kDirection) stat(57); // a bounce move with nothing to move
        #endif
            continue;
        }
```

(i) Right after `visz.Initialize();`, the bounce moves block:

```slang
    #if MAX_BOUNCES > 1
        if (s >= kDirection)
        {
            const float3 x1 = ray.origin + x.depth * ray.dir;
            const Bounce bx = readBounce(x, xb, x1);
            const uint k = s - kDirection; // 0 direction, 1 distance, 2 rebounce
            stat(49 + 2 * k);
            ExtraBounceReservoir zb = xb;
            float qx = 1.f, qz = 1.f;
            float3 zDir = bx.dir;
            float zDist = bx.dist;
            float3 zX2 = bx.x2;
            if (s == kRebounce)
            {
                if (!proposeRebounce(x1, -ray.dir, sg, zDir, zDist)) { stat(55); continue; }
                zX2 = x1 + zDist * zDir;
                qx = rebounceQ(x1, -ray.dir, bx.dir, bx.dist, bx.emissive, sg);
                if (!(qx > 0.f) || isinf(qx)) { stat(56); continue; }
            }
            else if (s == kDirection)
            {
                if (bx.emissive) zX2 = bx.x2 + isotropicStep(depthUnit, sg);
                else zDir = rotateDirection(bx.dir, sg);
            }
            else // kDistance
            {
                zDist = bx.dist + depthUnit * kelemenStep(gDepthStepMin, gDepthStepMax, sampleNext2D(sg));
                if (!(zDist > 0.f)) { stat(58); continue; } // p_hat = 0: rejected, never resampled
            }
            if (bx.emissive) encodeEmissivePosition(zX2, z.lightID, z.lightUV);
            else zb.wi_dist = encodeWiDist(float4(zDir, zDist));
            if (s == kRebounce)
            {
                const Bounce bz = readBounce(z, zb, x1); // the stored state: what p_hat sees
                qz = rebounceQ(x1, -ray.dir, bz.dir, bz.dist, bz.emissive, sg);
                if (!(qz > 0.f) || isinf(qz)) { stat(56); continue; }
            }
            MutationDataProvider dpz = dp;
            dpz.value = zb;
            visz.data = primaryVis; // x1 did not move
            const float pz = pHat(z, ray, sg, dpz, VBUFFERITEM visz);
            if (pz > 0.f && sampleNext1D(sg) * px * qz < pz * qx)
            {
                x = z;
                xb = zb;
                dp.value = xb;
                px = pz;
                bounceVis = visz.data1;
                stat(50 + 2 * k);
            }
            continue;
        }
    #endif
```

(j) In the `kSelect` block, replace

```slang
            const float3 p = ray.origin + x.depth * ray.dir;
```

with

```slang
        #if MAX_BOUNCES > 1
            // The light connects at the last vertex: x2 after an extra bounce, seen along -omega.
            const Bounce bs = readBounce(x, xb, ray.origin + x.depth * ray.dir);
            const float3 p = bs.x2;
            const float3 wo = bs.present ? -bs.dir : -ray.dir;
        #else
            const float3 p = ray.origin + x.depth * ray.dir;
            const float3 wo = -ray.dir;
        #endif
```

and in the same block change `analyticProposal(p, -ray.dir, kinds.analytic)` to
`analyticProposal(p, wo, kinds.analytic)`. After `visz.data = primaryVis; // the depth did not move`,
in the `kSelect` block and in the `kLight` branch, add:

```slang
        #if MAX_BOUNCES > 1
            visz.data1 = bounceVis; // nor did the extra bounce
        #endif
```

(k) In the shared acceptance block at the end of the loop, after `primaryVis = visz.data;`, add:

```slang
        #if MAX_BOUNCES > 1
            bounceVis = visz.data1;
        #endif
```

Add the same after `primaryVis = visz.data;` in the `kFlight` acceptance.

(l) After `gCurReservoirs[pixelId] = r;`, add:

```slang
#if MAX_BOUNCES > 1
    gCurExtraBounceReservoirs[r.extraBounceStartId] = xb; // the extra bounce the chain ended on
#endif
```

- [ ] **Step 4: Host changes**

In `VolumetricReSTIR.cpp`:

- Append to `kMutationStatNames`, after its last entry `"capture reason"` (index 48). The new
  entries are indices 49–58, in the order the shader uses them:

  ```cpp
                                          "capture voxel entry", "capture voxel exit", "capture reason",
                                          "direction proposed", "direction accepted", "distance proposed", "distance accepted",
                                          "rebounce proposed", "rebounce accepted", "rebounce escaped or hit a surface",
                                          "rebounce q = 0", "bounce move not applicable", "distance <= 0"};
  ```

- In `mutationsActive()`, replace `mParams.mMaxBounces == 1 && !mParams.mVertexReuse` with
  `mParams.mMaxBounces <= 2 && !mParams.mVertexReuse`. Update the header comment in
  `VolumetricReSTIR.h` to: "single or two-bounce scattering without vertex reuse (BounceMoves.slang
  moves the extra bounce)".

- In the `MAX_BOUNCES` update block (after `mpTraceRaysPass->getProgram()->addDefine(...)`), add:

  ```cpp
          if (mMutateSamplesPass) mMutateSamplesPass->getProgram()->addDefine("MAX_BOUNCES", std::to_string(mParams.mMaxBounces));
  ```

- In the stats log, before `pRenderContext->clearUAV(...)`, add:

  ```cpp
          if (s[49] + s[51] + s[53] > 0)
              logInfo("VolumetricReSTIR bounce moves: direction {}/{} accepted ({:.3f}), distance {}/{} ({:.3f}), "
                      "rebounce {}/{} ({:.3f}); {} {}, {} {}, {} {}, {} {}", s[50], s[49], rate(s[50], s[49]), s[52], s[51],
                      rate(s[52], s[51]), s[54], s[53], rate(s[54], s[53]), s[55], kMutationStatNames[55], s[56],
                      kMutationStatNames[56], s[57], kMutationStatNames[57], s[58], kMutationStatNames[58]);
  ```

- In the strategy UI (around lines 2155–2166), replace the block from the tooltip to the mask
  assignment with:

  ```cpp
              widget.tooltip("Metropolis-Hastings steps on each pixel's reservoir sample after temporal reuse "
                             "(Sawhney et al. 2024). 0 = off. Runs for one or two bounces without vertex reuse "
                             "and with ray-marching or analytic spatial trackers (p_hat must be deterministic).", true);
              bool light = mParams.mMutationStrategyMask & 1u, depth = mParams.mMutationStrategyMask & 2u;
              bool select = mParams.mMutationStrategyMask & 4u, flight = mParams.mMutationStrategyMask & 8u;
              bool direction = mParams.mMutationStrategyMask & 16u, distance = mParams.mMutationStrategyMask & 32u;
              bool rebounce = mParams.mMutationStrategyMask & 64u;
              bool strategies = widget.checkbox("Light-vertex moves", light);
              strategies |= widget.checkbox("Scatter-depth moves", depth);
              strategies |= widget.checkbox("Light re-selection (medium samples)", select);
              strategies |= widget.checkbox("Free-flight depth (medium samples)", flight);
              strategies |= widget.checkbox("Extra bounce: direction (2 bounces)", direction);
              strategies |= widget.checkbox("Extra bounce: distance (2 bounces)", distance);
              strategies |= widget.checkbox("Extra bounce: rebounce (2 bounces)", rebounce);
              if (strategies)
              {
                  mParams.mMutationStrategyMask = (light ? 1u : 0u) | (depth ? 2u : 0u) | (select ? 4u : 0u) | (flight ? 8u : 0u) |
                                                  (direction ? 16u : 0u) | (distance ? 32u : 0u) | (rebounce ? 64u : 0u);
                  dirty = true;
              }
  ```

- Update the comment on `mMutationStrategyMask` in `VolumetricReSTIR.h` to list bits 4–6.

In `CMakeLists.txt`, add `BounceMoves.slang` next to `MutateSamples.cs.slang`.

- [ ] **Step 5: Run the CPU tests (nothing GPU yet)**

Run: `cd Source/RenderPasses/VolumetricReSTIR/Scripts/tests && python -m unittest test_mutation_measures test_vr_graph_study`
Expected: OK.

- [ ] **Step 6: Build (queue paused, no Mogwai running)**

Run: `cd /c/research/Denoising-VolumetricReSTIR && ./tools/.packman/cmake/bin/cmake.exe --build build/windows-vs2022 --config Release --target VolumetricReSTIR Mogwai 2>&1 | tail -5`
Expected: no errors. Shaders compile at run time, so the next step checks those.

- [ ] **Step 7: One-bounce and 2-bounce mut0 identity**

Run: `bash outputs/decorr/identity_capture.sh after`. Then compare:

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr/identity
for c in $(ls before); do echo "$c $(cd before/$c && md5sum *.exr | sort) " > /tmp/b; echo "$c $(cd after/$c && md5sum *.exr | sort) " > /tmp/a; cmp -s /tmp/a /tmp/b && echo "$c identical" || echo "$c DIFFERS"; done
grep -l "(Error)" after/*/run.log
```

Expected:
- all six configs `identical`;
- no `run.log` containing `(Error)`.

A difference in a `b1_*` config means a one-bounce line changed: diff the shader against
`git show HEAD~1:...` and restore it. A difference in `b2_mut0_*` means the provider or the buffer
binding changed something without mutations: check that `mutationsActive()` is false with
`mMutationCount = 0`.

- [ ] **Step 8: The repo's locked identity checks**

Run: `bash outputs/mask_check.sh raw` and `bash outputs/pending_9p/spec/verify.sh quick`
Expected: `raw: frames compared N, byte-identical N`, and verify.sh reporting all identical.

- [ ] **Step 9: Two-bounce smoke run with stats**

```bash
cd /c/research/Denoising-VolumetricReSTIR
d="$(cygpath -am outputs/decorr/identity/smoke_b2)"; mkdir -p "$d"
( for v in $(env | grep -o "^\(VR_\|NRD4_\)[A-Z0-9_]*"); do unset "$v"; done
  VR_SCENE=explosiondusk VR_MAX_BOUNCES=2 VR_MTHRESH=200 VR_MUTATIONS=5 \
  VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1 \
  VR_DISPLAY=960x540 VR_CHAINS=1 VR_PER_CHAIN=2 VR_WARM=600 VR_SPACING=1 VR_OUT_DIR="$d" VR_TAG=c \
  timeout 900 ./build/windows-vs2022/bin/Release/Mogwai.exe --script 'C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\correlation_pose.py' > "$d/run.log" 2>&1 )
grep "bounce moves\|mutations, last" "$d/run.log" | tail -2
```

Expected:
- a `bounce moves:` line with direction, distance and rebounce each accepted at a rate strictly
  between 0.0 and 1.0;
- `bounce move not applicable` > 0 (tag-0-only distance picks on emission paths, and 0-bounce
  samples);
- no `(Error)` in `run.log`.

A rate of exactly 0 or 1 for a move is a defect. Debug it with superpowers:systematic-debugging;
the suspects are the q orientation, the provider override, and the stored-state decode.

- [ ] **Step 10: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/BounceMoves.slang Source/RenderPasses/VolumetricReSTIR/MutateSamples.cs.slang Source/RenderPasses/VolumetricReSTIR/VolumetricReSTIR.cpp Source/RenderPasses/VolumetricReSTIR/VolumetricReSTIR.h Source/RenderPasses/VolumetricReSTIR/CMakeLists.txt
git add -f outputs/decorr/identity_capture.sh
git commit -m "Mutations at two bounces: bounce-aware light moves, direction/distance/rebounce on the extra bounce (BounceMoves.slang)"
```

---

### Task 5: Bias gate at two bounces

**Files:**
- Create: `outputs/decorr/run_b2_bias.sh`
- Modify: the spec's Verification results (V-C1)

**Interfaces:**
- Consumes: Task 4's binary, and Task 2's `explosiondusk_b2/{ref,noreuse,shipped}`.
- Produces: per scene, `<label>_b2/{ref,noreuse,mcap200,mcap200_mut5b2,mcap200_mut5light}` (scored).

- [ ] **Step 1: Write the driver**

```bash
#!/bin/bash
# The two-bounce bias gate (spec): per first-round scene, reference, no reuse, M cap 200 plain, M cap 200 + 5 moves
# of every kind, and M cap 200 + 5 light-only moves (Review Focus 2: the extra bounce every p_hat sees). Log: b2.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
ALL="light,depth,select,flight,direction,distance,rebounce"
export STUDY_SPACING=5 STUDY_REF_FRAMES=2048
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] b2 bias start" >> $LOG
for L in explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    case $L in wdassunset*|explosion*) export STUDY_TIMEOUT=10800 ;; *) export STUDY_TIMEOUT=7200 ;; esac
    bash $O/run_study.sh refs $L 2>&1 | tee -a $LOG
    run $L noreuse VR_NO_TEMPORAL=1 VR_NO_SPATIAL=1
    run $L mcap200 VR_MTHRESH=200
    run $L mcap200_mut5b2 VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STRAT=$ALL VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
    run $L mcap200_mut5light VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_STRAT=light,select VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1
done
echo "[$(date +%H:%M:%S)] b2 bias done" >> $LOG
```

- [ ] **Step 2: Run it** (background, queue paused): `bash outputs/decorr/run_b2_bias.sh > outputs/decorr/b2_bias.stdout 2>&1`

Expected: 4 `[study]` lines per scene plus a reference each; no `FAILED`.

- [ ] **Step 3: Check the gate**

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr
for L in explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
  echo "== $L"; python bias_check.py . $L/mcap200 $L/mcap200_mut5b2 $L/mcap200_mut5light
done
```

Expected: every channel within 3 standard errors for both mutated configs, on every scene. A failure
on `mcap200_mut5light` alone points at the extra bounce every p̂ sees (Review Focus 2). A failure on
the cathedral alone points at surface x2 handling (Review Focus 3). Stop and debug either before
Task 6.

- [ ] **Step 4: Record and commit**

Append V-C1 to the spec: one line per scene with the bias_check values and each move's acceptance
rate (from the configs' `run.log` `bounce moves:` lines).

```bash
git add -f outputs/decorr/run_b2_bias.sh
git add docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md
git commit -m "Two-bounce bias gate: mutations at 2 bounces match plain reuse on the five first-round scenes (V-C1)"
```

---

### Task 6: Denoised comparisons and figures at two bounces

**Files:**
- Create: `outputs/decorr/run_two_bounce.sh`
- Modify: `outputs/decorr/variety_figures.py` (`TITLES`, `EXPOSURE`, `PAPER_DISPLAY`)
- Modify: `outputs/decorr/gallery_figure.py` (a `--two-bounce` scene order)

**Interfaces:**
- Consumes: `variety_figures.pair(denoiser)`, `PAPER_DISPLAY`, and `gallery_figure --denoiser`.
- Produces: `figs/variety_<label>.png` and `figs/variety_rr_<label>.png` for the `_b2` labels, and
  `figs/gallery_mutations_b2.png` / `figs/gallery_mutations_b2_rr.png`.

- [ ] **Step 1: The driver**

```bash
#!/bin/bash
# The variety comparison at two bounces: per first-round scene, plain ReSTIR vs 5 moves of every kind (M cap 200,
# no decoupled history), through OptiX and DLSS Ray Reconstruction. References come from run_b2_bias.sh. Log: b2.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/b2.log
LOOK="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
MUT="VR_MUTATIONS=5 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_MUT_STATS=1 VR_MUT_AFTER_SPATIAL=1"
export STUDY_SPACING=5
run() { bash $O/run_study.sh one "$@" 2>&1 | tee -a $LOG; }
echo "[$(date +%H:%M:%S)] b2 denoised start" >> $LOG
for L in explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2; do
    case $L in wdassunset*|explosion*) export STUDY_TIMEOUT=10800 ;; *) export STUDY_TIMEOUT=7200 ;; esac
    for den in optix rr; do
        # shellcheck disable=SC2086
        run $L den_${den}_mut0cap200 VR_DENOISER=$den $LOOK VR_MTHRESH=200
        # shellcheck disable=SC2086
        run $L den_${den}_mut5cap200 VR_DENOISER=$den $LOOK VR_MTHRESH=200 $MUT
    done
done
echo "[$(date +%H:%M:%S)] b2 denoised done" >> $LOG
```

- [ ] **Step 2: Titles and display**

In `variety_figures.py`:
- add to `TITLES`:

  ```python
      "explosiondusk_b2": "Explosion as in the paper, 2 bounces: the fire lights the smoke",
      "bunnycathedral_d0.3_b2": "Cathedral god rays, 2 bounces: light scattered off the beams fills the room",
      "bunnyback_g0.8_b2": "Cloud backlit by one light, 2 bounces: the rim and the light inside it",
      "bunnysoftbox_b2": "Warm and cool panel lights beside a cloud, 2 bounces",
      "wdassunset_g0.85_b2": "Disney cloud at sunset, 2 bounces",
  ```

- set `PAPER_DISPLAY = {"explosiondusk", "explosiondusk_b2"}`.

In `gallery_figure.py`, add the order and option:

```python
ORDER_B2 = ["explosiondusk_b2", "bunnycathedral_d0.3_b2", "bunnyback_g0.8_b2", "bunnysoftbox_b2", "wdassunset_g0.85_b2"]
```

Add `ap.add_argument("--two-bounce", action="store_true")`. When set, `labels` come from `ORDER_B2`,
the suptitle says "two bounces", and the default output is `gallery_mutations_b2{_rr}.png`.

- [ ] **Step 3: Check the figure scripts on the 1-bounce data (no regressions)**

Run: `cd outputs/decorr && python -m unittest discover -p "test_*.py" && python gallery_figure.py . --out "$TEMP/g.png"`
Expected: OK, then a path printed.

- [ ] **Step 4: Run the driver** (background, after Task 5's gate passed):
`bash outputs/decorr/run_two_bounce.sh > outputs/decorr/b2_denoised.stdout 2>&1`
Expected: 4 `[study]` lines per scene; no `FAILED`.

- [ ] **Step 5: Figures**

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr
python variety_figures.py . && python variety_figures.py . --denoiser rr
python gallery_figure.py . --two-bounce && python gallery_figure.py . --two-bounce --denoiser rr
```

Expected: five `variety_*_b2.png`, five `variety_rr_*_b2.png`, and two galleries, each with the
printed relMSE change. Look at every figure before sending, and check the error maps the same way
as at one bounce.

- [ ] **Step 6: Record and commit**

Append V-C2 to the spec: a per-scene table of the in-medium relMSE change (2-chain averages, as
`settings_chart.py` computes them), OptiX and RR, next to the one-bounce numbers.

```bash
git add -f outputs/decorr/run_two_bounce.sh outputs/decorr/variety_figures.py outputs/decorr/gallery_figure.py
git add docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md
git commit -m "Two-bounce variety: denoised comparisons through OptiX and RR on the five first-round scenes (V-C2)"
```

---

### Task 7: Resume the older queue

- [ ] **Step 1:** Relaunch the older items in one background chain: rest of the scene matrix,
  free-flight study, post, den2.

```bash
cd /c/research/Denoising-VolumetricReSTIR; export STUDY_SKIP_DEC=1; bash outputs/decorr/run_scenes3.sh rest > outputs/decorr/scenes3_rest.stdout 2>&1; FLIGHT_NOWAIT=1 FLIGHT_STUDY_ONLY=1 bash outputs/decorr/run_flight.sh > outputs/decorr/flight.stdout 2>&1; bash outputs/decorr/run_post.sh > outputs/decorr/post.stdout 2>&1 && bash outputs/decorr/run_den2.sh > outputs/decorr/den2.stdout 2>&1
```

Expected: the scene matrix skips finished configs and continues from `bunnyone_d5`.
