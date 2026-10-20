# The mutation paper, seen through five denoisers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `DenosingVolumetricReSTIR/paper.tex` as a paper on Metropolis–Hastings mutations for Volumetric ReSTIR, shown before and after through OptiX, OIDN, NRD RELAX, NRD REBLUR and DLSS RR, from the recorded experiments plus new five-denoiser runs on 19 setups.

**Architecture:** A small graph wrapper (`denoiser_set.py`) lets four denoisers share one render graph so they denoise the same ReSTIR frames; DLSS RR runs in its own graph with the same seeds because its G-buffer jitters the camera. A resumable queue renders 152 captures; scorers write one results file; generated tables and figures go into the paper, which is built with Tectonic. No renderer code changes.

**Tech Stack:** Falcor 9 (Mogwai, Python render-graph scripts), Python 3 (numpy, OpenCV EXR, matplotlib), bash (Git Bash), LaTeX (acmart `sigconf`) built by Tectonic 0.17.0.

**Spec:** `docs/superpowers/specs/2026-10-20-mutation-paper-design.md` (amended in 0413946). It cites the recorded results in `docs/superpowers/specs/2026-09-27-restir-mcmc-decorrelation-design.md` (V1–V9, V-B1–V-B10) and `docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md` (V-C0–V-C7).

## Global Constraints

- Every number in the paper traces to a recorded result: a V-section of the two specs, or `outputs/decorr/five_denoisers/{results,ref_change,motion}.json`. The numbers ledger (Task 14) lists each one with its source.
- The claims stay inside the data. The abstract and results say: the large cuts (−45% to −90% after denoising) are at a 200-frame history (M cap 200); at the shipped cap mutations cut the denoised error by 3–26% (V-C3), and plain ReSTIR there is already about as good as cap 200 with mutations on three of the five main scenes (V-C3); so mutations are what makes a long history usable, and cap 200 with mutations wins outright only with many lights; the limits: brightness lives in the shared normalization, which mutations keep; a decoupled history removes more at long histories; the duplication cap biases; DLSS RR darkens its input; motion.
- Denoisers: OptiX 9.1 (temporal, volume-aware guides), OIDN 2.3.3 (CUDA), NRD 4.17 RELAX-SH, NRD 4.17 REBLUR-SH, DLSS Ray Reconstruction; every denoised run uses the study's LOOK settings (`VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient`).
- The 19 setups: `bunnycathedral_d0.3 bunnyspot bunnysoftbox bunnyinside bunnyback_g0.8 bunnystripes explosion bunnylanterns wdassunset_g0.85 plumeback_g0.9 plumeconcert_g0.6 emeraldnight_d3` (one bounce), `explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2` (two), `bunnyswarm_d3 wdasstorm_g0.5`.
- Histories: M cap 200 and the shipped cap (4; 10 on the night street, which Emerald Square's loader sets). Mutated runs: `VR_MUTATIONS=5 VR_MUT_AFTER_SPATIAL=1`, strategies `light,depth,select,flight` (+ `,direction,distance,rebounce` at two bounces); coherent moves and early rejection as shipped (leave `VR_MUT_COHERENT` and `VR_MUT_EARLY_REJECT` unset).
- 1920×1080 for the 17 gallery setups, 960×540 for `bunnyswarm_d3` and `wdasstorm_g0.5`; 2 chains × 1 capture, seeds from 100000.
- One Mogwai at a time. No build is needed by this plan; never build while a Mogwai runs.
- Kill processes only by exact PID.
- Never delete data: old references are renamed to `ref_residual`, half-written runs renamed aside. The new queue prunes nothing.
- The paper folder `DenosingVolumetricReSTIR/` and the user's other untracked folders are never committed. Commit messages carry no AI attribution (the user's rule overrides any trailer instruction).
- Tectonic 0.17.0 lives in the scratchpad: `S=C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad`.
- Citations are checked against `Papers/` or the publisher's page before entering the bibliography; one that cannot be checked is dropped.
- The E3 queue starts only with at least 35 GB free on C:.
- Left out of the paper: the look-development scenes (teapot, dust, construct art), the surface-first-vertex moves (reverted), the animated-medium test.

## Review Focus

1. **A denoiser in the shared graph seeing different frames than when alone** (a jittering G-buffer, a property another denoiser sets on the estimator) — the four channels must match their single runs. Pinned by `test_every_gbuffer_in_the_shared_graph_is_unjittered` and `test_rr_is_refused` (Task 2) and gate 2 (Task 4).
2. **A cut-off or failed run taken as finished** (partial EXRs, a Falcor error in the log) — the queue must re-render it. Pinned by `TestComplete` (Task 6).
3. **A re-rendered reference that wrote nothing or half** (no final accumulation) — must stop the refs script and never be scored. Pinned by `test_accumulations_need_two_files` (Task 5) and the refs script's final-file check.
4. **A frame, reference or mask of another size** (960×540 against 1080p) — must raise, not broadcast. Pinned by `test_size_mismatch_raises` (Task 5).
5. **A number in the paper with no source** — must fail the final check. Pinned by `TestCheckNumbers` (Task 14).

---

### Task 1: Tectonic, and the old paper kept

**Files:**
- Create: `$S/tools/tectonic/tectonic.exe` (download, scratchpad)
- Create: `DenosingVolumetricReSTIR/paper_v1_denoising_vs_sampling.tex` (copy; not committed)

**Interfaces:**
- Produces: `$S/tools/tectonic/tectonic.exe` (version 0.17.0), used by Tasks 12–14.

- [ ] **Step 1: Download and unpack Tectonic** (the user approved this download: 21 MB from the official release)

```bash
S="C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
mkdir -p "$S/tools/tectonic"
curl -L -m 600 -o "$S/tools/tectonic/tectonic.zip" "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-pc-windows-msvc.zip"
ls -l "$S/tools/tectonic/tectonic.zip"
powershell -NoProfile -Command "Expand-Archive -Force '$S/tools/tectonic/tectonic.zip' '$S/tools/tectonic'"
"$S/tools/tectonic/tectonic.exe" --version
```
Expected: the zip is 21060223 bytes; `Tectonic 0.17.0`.

- [ ] **Step 2: Build the old paper in a scratch copy** (proves the toolchain on this template; the first run downloads the TeX bundle)

```bash
S="C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
B="$S/paperbuild/v1"; mkdir -p "$B"
cp -r /c/research/Denoising-VolumetricReSTIR/DenosingVolumetricReSTIR/. "$B/"
cd "$B" && "$S/tools/tectonic/tectonic.exe" -X compile paper.tex > build.log 2>&1; echo "exit $?"; tail -n 15 build.log; ls -l paper.pdf
```
Expected: exit 0 and `paper.pdf` present. If acmart fails under Tectonic's XeTeX engine, read `build.log`, fix the cause in the scratch copy (font or package), and carry the fix into Task 12's preamble.

- [ ] **Step 3: Keep the old paper beside the new one**

```bash
P=/c/research/Denoising-VolumetricReSTIR/DenosingVolumetricReSTIR
cp -n "$P/paper.tex" "$P/paper_v1_denoising_vs_sampling.tex" && cmp "$P/paper.tex" "$P/paper_v1_denoising_vs_sampling.tex" && echo kept
```
Expected: `kept`. No commit (the paper folder stays out of git).

---

### Task 2: `denoiser_set.py` — four denoisers in one graph

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/denoiser_set.py`
- Test: `Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_denoiser_set.py`

**Interfaces:**
- Consumes: `vr_graph.add_denoiser(g, mode, color, scene, render, display, ..., restir="VolumetricReSTIR", gbuffer=None, guides=True, sdk_variant="Current")`, `vr_graph.add_gbuffer(g, render, jitter=...)`.
- Produces: `denoiser_set.MODES = ("optix", "oidn", "relax", "reblur")`; `denoiser_set.NRD_METHODS = {"relax": "RelaxDiffuseSh", "reblur": "ReblurDiffuseSh"}`; `denoiser_set.PrefixedGraph(graph, prefix)` with `.resolve(ref: str) -> str`, `.addPass`, `.addEdge`, `.markOutput`, `.get_pass`; `denoiser_set.env_override(values: dict)` (context manager); `denoiser_set.add_denoisers(g, modes, color, scene, render, restir="VolumetricReSTIR", preset="E", sdk_variant="Current") -> dict[str, str]` returning e.g. `{"optix": "D_optix_Denoiser.output", "oidn": "D_oidn_Denoiser.dst", "relax": "D_relax_ModulateIllumination.output", "reblur": "D_reblur_ModulateIllumination.output"}`.

- [ ] **Step 1: Write the failing tests**

`Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_denoiser_set.py`:
```python
"""denoiser_set.py: several denoisers on the same frames in one render graph (paper spec E1).

vr_graph imports `falcor`, which exists only inside Mogwai. This stubs it with a graph that keeps passes by name
(refusing a duplicate name, as Falcor does), their properties, the edges and the marked outputs.

    cd Source/RenderPasses/VolumetricReSTIR/Scripts && python -m unittest tests.test_denoiser_set -v
"""
import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

# run_study.sh's LOOK: the configuration every denoised run of the study uses.
LOOK = {"VR_NRD_SPLIT": "1", "VR_NRD_SH": "1", "VR_NRD_TAA": "1", "VR_TAA_LDR": "1", "VR_NRD_EMISSION": "1",
        "VR_NRD_VOLMASK": "1", "VR_VOL_NORMAL": "gradient"}
SCENE = {"scatterAlbedo": (0.9, 0.9, 0.9)}
RENDER = (64, 32)
COLOR = "VolumetricReSTIR.accumulated_color"


class FakePass:
    def __init__(self, kind, props):
        self.kind = kind
        self.properties = dict(props or {})

    def set_properties(self, props):
        self.properties.update(props)


class FakeGraph:
    def __init__(self):
        self.passes, self.edges, self.outputs = {}, [], []

    def addPass(self, render_pass, name):
        if name in self.passes:
            raise ValueError("duplicate pass name " + name)
        kind, props = render_pass
        self.passes[name] = FakePass(kind, props)

    def addEdge(self, src, dst):
        self.edges.append((src, dst))

    def markOutput(self, channel):
        self.outputs.append(channel)

    def get_pass(self, name):
        return self.passes[name]

    def wiring(self):
        return {n: (p.kind, p.properties) for n, p in self.passes.items()}, list(self.edges)


def modules():
    falcor = types.ModuleType("falcor")
    falcor.float3 = lambda *a: tuple(a)
    falcor.float2 = lambda *a: tuple(a)
    falcor.createPass = lambda name, props=None: (name, props)
    sys.modules["falcor"] = falcor
    import vr_graph
    import denoiser_set
    return importlib.reload(vr_graph), importlib.reload(denoiser_set)


def estimator_graph():
    g = FakeGraph()
    g.addPass(("VolumetricReSTIR", {"mMotionVecMode": "Deterministic", "mOutputDepth": True}), "VolumetricReSTIR")
    return g


class TestAddDenoisers(unittest.TestCase):
    def setUp(self):
        self.vr, self.ds = modules()
        patcher = mock.patch.dict(os.environ, LOOK)
        patcher.start()
        self.addCleanup(patcher.stop)

    def four(self):
        g = estimator_graph()
        return g, self.ds.add_denoisers(g, list(self.ds.MODES), COLOR, SCENE, RENDER)

    def test_each_denoiser_gets_its_own_prefixed_passes(self):
        g, _ = self.four()
        for name in g.passes:
            if name != "VolumetricReSTIR":
                self.assertTrue(any(name.startswith("D_%s_" % m) for m in self.ds.MODES), name)

    def test_returns_each_denoisers_output(self):
        _, channels = self.four()
        self.assertEqual(channels, {"optix": "D_optix_Denoiser.output", "oidn": "D_oidn_Denoiser.dst",
                                    "relax": "D_relax_ModulateIllumination.output",
                                    "reblur": "D_reblur_ModulateIllumination.output"})

    def test_every_edge_joins_passes_that_exist_and_the_estimator_keeps_its_name(self):
        g, _ = self.four()
        for src, dst in g.edges:
            for end in (src, dst):
                self.assertIn(end.partition(".")[0], g.passes, end)
        self.assertIn((COLOR, "D_oidn_Denoiser.src"), g.edges)

    def test_each_nrd_instance_runs_its_own_method(self):
        with mock.patch.dict(os.environ, {"VR_NRD_METHOD": "ReblurDiffuse"}):
            g, _ = self.four()
            self.assertEqual(os.environ["VR_NRD_METHOD"], "ReblurDiffuse")  # restored after each call
        for half in ("NRDSurface", "NRDVolume"):
            self.assertEqual(g.passes["D_relax_" + half].properties["method"], "RelaxDiffuseSh")
            self.assertEqual(g.passes["D_reblur_" + half].properties["method"], "ReblurDiffuseSh")
        # REBLUR packs SH0 as YCoCg and RELAX as linear RGB (vr_graph.add_nrd_split): each adapter follows its own.
        self.assertFalse(g.passes["D_relax_NRDAdapterSurface"].properties["shYCoCg"])
        self.assertTrue(g.passes["D_reblur_NRDAdapterSurface"].properties["shYCoCg"])

    def test_every_gbuffer_in_the_shared_graph_is_unjittered(self):
        # A jittering G-buffer moves the camera for every pass, the estimator included (Review Focus 1).
        g, _ = self.four()
        gbuffers = [p for p in g.passes.values() if p.kind == "GBufferRaster"]
        self.assertGreaterEqual(len(gbuffers), 4)
        for p in gbuffers:
            self.assertEqual(p.properties["samplePattern"], "Center")

    def test_an_empty_prefix_wires_exactly_as_add_denoiser(self):
        for kind, method in (("optix", None), ("nrd", "RelaxDiffuseSh"), ("nrd", "ReblurDiffuseSh")):
            values = {"VR_NRD_METHOD": method} if method else {}
            with mock.patch.dict(os.environ, values):
                direct = estimator_graph()
                self.vr.add_denoiser(direct, kind, COLOR, SCENE, RENDER, RENDER, gbuffer=None, guides=True)
            wrapped = estimator_graph()
            with self.ds.env_override(values):
                self.vr.add_denoiser(self.ds.PrefixedGraph(wrapped, ""), kind, COLOR, SCENE, RENDER, RENDER,
                                     gbuffer=None, guides=True)
            self.assertEqual(wrapped.wiring(), direct.wiring(), (kind, method))

    def test_rr_is_refused(self):
        with self.assertRaisesRegex(ValueError, "jitter"):
            self.ds.add_denoisers(estimator_graph(), ["rr"], COLOR, SCENE, RENDER)

    def test_unknown_or_repeated_denoisers_are_refused(self):
        with self.assertRaises(ValueError):
            self.ds.add_denoisers(estimator_graph(), ["svgf"], COLOR, SCENE, RENDER)
        with self.assertRaises(ValueError):
            self.ds.add_denoisers(estimator_graph(), ["optix", "optix"], COLOR, SCENE, RENDER)


class TestEnvOverride(unittest.TestCase):
    def test_restores_the_environment_when_the_block_raises(self):
        _, ds = modules()
        with mock.patch.dict(os.environ, {"VR_A": "1"}):
            os.environ.pop("VR_B", None)
            with self.assertRaises(RuntimeError):
                with ds.env_override({"VR_A": "2", "VR_B": "3"}):
                    self.assertEqual((os.environ["VR_A"], os.environ["VR_B"]), ("2", "3"))
                    raise RuntimeError
            self.assertEqual(os.environ["VR_A"], "1")
            self.assertNotIn("VR_B", os.environ)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/Source/RenderPasses/VolumetricReSTIR/Scripts && python -m unittest tests.test_denoiser_set -v 2>&1 | tail -n 5`
Expected: errors, `ModuleNotFoundError: No module named 'denoiser_set'`.

- [ ] **Step 3: Write `denoiser_set.py`**

`Source/RenderPasses/VolumetricReSTIR/Scripts/denoiser_set.py`:
```python
"""Several denoisers on the same Volumetric ReSTIR frames in one render graph (docs/superpowers/specs/
2026-10-20-mutation-paper-design.md, E1).

vr_graph.add_denoiser names the passes it adds (Denoiser, NRDSurface, ModulateIllumination, ...) and NRD reads its
method from VR_NRD_METHOD, so two denoisers of a kind cannot share a graph as they are. Here each denoiser's passes
are added through a PrefixedGraph, which names them prefix + name and renames the edges and lookups that refer to
them, and NRD's method is set for its own call only. Every denoiser is wired exactly as add_denoiser wires it alone
(tests/test_denoiser_set.py checks it against add_denoiser itself), with its own G-buffer and guides.

Not DLSS Ray Reconstruction: its G-buffer turns on the camera's Halton jitter, and the estimator's camera rays follow
the camera jitter (VolumeBase.slang computeNonNormalizedRayDirPinholeOffset), so in a shared graph it would change
the frames every other denoiser sees. RR runs in its own graph with the same seeds (correlation_pose.py
VR_DENOISER=rr).
"""
import os
from contextlib import contextmanager

import vr_graph as vr

NRD_METHODS = {"relax": "RelaxDiffuseSh", "reblur": "ReblurDiffuseSh"}
MODES = ("optix", "oidn", "relax", "reblur")


class PrefixedGraph:
    """A RenderGraph that names the passes added through it prefix + name. An edge, output or lookup naming one of
    those passes is renamed to match; any other pass (the estimator, a G-buffer made outside) keeps its name."""

    def __init__(self, graph, prefix):
        self.graph = graph
        self.prefix = prefix
        self.own = set()

    def resolve(self, ref):
        """'pass.port' or 'pass', its pass renamed if it was added through this graph."""
        name, dot, port = ref.partition(".")
        return (self.prefix + name if name in self.own else name) + dot + port

    def addPass(self, render_pass, name):
        self.own.add(name)
        return self.graph.addPass(render_pass, self.prefix + name)

    def addEdge(self, src, dst):
        return self.graph.addEdge(self.resolve(src), self.resolve(dst))

    def markOutput(self, channel):
        return self.graph.markOutput(self.resolve(channel))

    def get_pass(self, name):
        return self.graph.get_pass(self.resolve(name))


@contextmanager
def env_override(values):
    """os.environ with `values` set inside the block and exactly as before after it, also when it raises
    (vr_graph reads its knobs when one of its functions is called)."""
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def add_denoisers(g, modes, color, scene, render, restir="VolumetricReSTIR", preset="E", sdk_variant="Current"):
    """Wire `color` through each denoiser of `modes` (MODES) in graph `g`, as correlation_pose.py wires one alone.
    Returns {mode: output channel}."""
    channels = {}
    for mode in modes:
        if mode == "rr":
            raise ValueError("DLSS RR turns on camera jitter, which changes the frames the other denoisers see: "
                             "capture it in its own graph (VR_DENOISER=rr)")
        if mode not in MODES:
            raise ValueError("unknown denoiser %r (have: %s)" % (mode, ", ".join(MODES)))
        if mode in channels:
            raise ValueError("denoiser %r given twice" % mode)
        pg = PrefixedGraph(g, "D_%s_" % mode)
        # correlation_pose.py hands OIDN an unjittered G-buffer of its own (OIDN itself wires colour only).
        gbuffer = vr.add_gbuffer(pg, render, jitter=False) if mode == "oidn" else None
        method = {"VR_NRD_METHOD": NRD_METHODS[mode]} if mode in NRD_METHODS else {}
        with env_override(method):
            channel = vr.add_denoiser(pg, "nrd" if mode in NRD_METHODS else mode, color, scene, render, render,
                                      restir=restir, gbuffer=gbuffer, guides=True, preset=preset,
                                      sdk_variant=sdk_variant)
        channels[mode] = pg.resolve(channel)
    return channels
```

- [ ] **Step 4: Run the tests to see them pass, and the Scripts suite**

Run: `cd /c/research/Denoising-VolumetricReSTIR/Source/RenderPasses/VolumetricReSTIR/Scripts && python -m unittest tests.test_denoiser_set -v 2>&1 | tail -n 3 && python -m unittest discover -s tests 2>&1 | tail -n 3`
Expected: `Ran 9 tests ... OK`, then the whole Scripts suite `OK`.

- [ ] **Step 5: Commit**

```bash
cd /c/research/Denoising-VolumetricReSTIR
git add Source/RenderPasses/VolumetricReSTIR/Scripts/denoiser_set.py Source/RenderPasses/VolumetricReSTIR/Scripts/tests/test_denoiser_set.py
git commit -m "denoiser_set.py: OptiX, OIDN, NRD RELAX-SH and NRD REBLUR-SH in one render graph, each wired exactly as add_denoiser wires it alone (its passes prefixed, NRD's method set for its own call); DLSS RR refused, its G-buffer jitters the camera the estimator's rays follow"
```

---

### Task 3: the capture script takes a denoiser set; `five_capture.sh`; gate 1

**Files:**
- Modify: `Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py` (header lines 16–18; lines 66–86; the schedule dump at lines 131–134)
- Create: `outputs/decorr/five_capture.sh`

**Interfaces:**
- Consumes: `denoiser_set.add_denoisers(...) -> {mode: channel}` (Task 2).
- Produces: `correlation_pose.py` with `VR_DENOISERS=optix,oidn,relax,reblur`: marks every channel plus `VolumetricReSTIR.accumulated_color`; its schedule's `channel` stays the raw one and a new key `channels` = `{mode: channel, "raw": "VolumetricReSTIR.accumulated_color"}`; `denoiser` = `"set:optix,oidn,relax,reblur"`. `outputs/decorr/five_capture.sh <run dir> [VAR=value ...]` (env `FIVE_SCRIPT` picks another Mogwai script, default `correlation_pose.py`; `FIVE_TIMEOUT` seconds, default 3600).

- [ ] **Step 1: Gate 1, the "before" capture** (the committed script, a single OptiX run; nothing edited yet)

Write `outputs/decorr/five_capture.sh` first (it does not touch correlation_pose.py):
```bash
#!/bin/bash
# One Mogwai capture for the paper's runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md):
#   five_capture.sh <run dir> [VAR=value ...]
# runs FIVE_SCRIPT (default correlation_pose.py, in the Scripts directory) into <run dir> (tag c, run.log beside
# it) with the VR_/NRD4_/LANTERN_ environment cleared and the given assignments set, and Mogwai's stdin closed (a
# caller's `while read` loop keeps its input). Waits up to a minute for an earlier Mogwai to exit (one at a time):
# exit 3 if one is still running, else Mogwai's status (124 = FIVE_TIMEOUT seconds, default 3600).
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
d=$1
shift
for _ in $(seq 1 60); do tasklist 2>/dev/null | grep -qi mogwai || break; sleep 1; done
if tasklist 2>/dev/null | grep -qi mogwai; then echo "five_capture: a Mogwai is running; not starting" >&2; exit 3; fi
mkdir -p "$d"
script='C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\'"${FIVE_SCRIPT:-correlation_pose.py}"
(
    for v in $(env | grep -o "^\(VR_\|NRD4_\|LANTERN_\)[A-Z0-9_]*"); do unset "$v"; done
    export MSYS_NO_PATHCONV=1 "$@"
    VR_OUT_DIR="$(cygpath -am "$d")" VR_TAG=c timeout "${FIVE_TIMEOUT:-3600}" ./build/windows-vs2022/bin/Release/Mogwai.exe \
        --script "$script" > "$d/run.log" 2>&1 < /dev/null
)
```
Then the capture:
```bash
cd /c/research/Denoising-VolumetricReSTIR
G=outputs/decorr/five_denoisers/gate1
GATE1="VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=5 VR_WARM=48 VR_IDS=0 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient VR_DENOISER=optix"
# shellcheck disable=SC2086
bash outputs/decorr/five_capture.sh $G/before $GATE1; echo "exit $?"; ls $G/before/*.exr; grep -c "(Error)" $G/before/run.log
```
Expected: exit 0, one `c.Denoiser.output.<f>.exr`, `0` errors.

- [ ] **Step 2: Edit `correlation_pose.py`**

Header, after the `VR_DENOISER=...` lines (16–18), add:
```python
#   VR_DENOISERS=optix,oidn,relax,reblur   several denoisers on the same frames (denoiser_set.py), every channel
#                              captured with the raw frame, the schedule's `channels` naming them. Not with
#                              VR_DENOISER, and not rr (its G-buffer jitters the camera: VR_DENOISER=rr alone).
```
Replace
```python
DENOISER = vr.env("VR_DENOISER", "none").lower()
g = RenderGraph("correlation_pose")
```
with
```python
DENOISER = vr.env("VR_DENOISER", "none").lower()
DENOISER_SET = [d for d in vr.env("VR_DENOISERS", "").lower().split(",") if d]
if DENOISER_SET and DENOISER != "none":
    raise ValueError("VR_DENOISERS and VR_DENOISER are exclusive")
CHANNELS = {}
g = RenderGraph("correlation_pose")
```
Replace
```python
elif DENOISER != "none":
    # capture_orbit.py's pipeline up to the denoiser (its Look config comes from the same VR_NRD_* /
```
with
```python
elif DENOISER_SET:
    # Several denoisers on the same frames (paper spec E1), each wired as the branch below wires it alone. The raw
    # frame is captured too and stays the schedule's `channel` (what m_corr.py and prune.py read).
    import denoiser_set
    restir = vr.add_restir(g, scene, render=(W, H), guides=True, mOutputDepth=True,
                           mMotionVecMode="Deterministic", mParams=params)
    CHANNELS = denoiser_set.add_denoisers(g, DENOISER_SET, restir + ".accumulated_color", scene, (W, H),
                                          restir=restir, preset=vr.env("VR_PRESET", "E"),
                                          sdk_variant=vr.env("VR_SDK", "Current"))
    for ch in CHANNELS.values():
        g.markOutput(ch)
    g.markOutput(restir + ".accumulated_color")
    CHANNELS["raw"] = restir + ".accumulated_color"
    DENOISER = "set:" + ",".join(DENOISER_SET)
elif DENOISER != "none":
    # capture_orbit.py's pipeline up to the denoiser (its Look config comes from the same VR_NRD_* /
```
Replace
```python
                       spacing=vr.env_int("VR_SPACING", 33), channel=channel, denoiser=DENOISER, env=env),
                  fh, indent=1)
```
with
```python
                       spacing=vr.env_int("VR_SPACING", 33), channel=channel, denoiser=DENOISER, env=env,
                       **({"channels": CHANNELS} if CHANNELS else {})),
                  fh, indent=1)
```

- [ ] **Step 3: Gate 1, the "after" capture: the single-denoiser path is unchanged**

```bash
cd /c/research/Denoising-VolumetricReSTIR
G=outputs/decorr/five_denoisers/gate1
GATE1="VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=5 VR_WARM=48 VR_IDS=0 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient VR_DENOISER=optix"
# shellcheck disable=SC2086
bash outputs/decorr/five_capture.sh $G/after $GATE1
for f in $G/before/c.*.exr; do cmp "$f" "$G/after/$(basename "$f")" && echo "identical $(basename "$f")"; done
```
Expected: `identical c.Denoiser.output.<f>.exr`. If they differ, stop: the edit changed the single path (systematic-debugging).

- [ ] **Step 4: Smoke the new branch** (480×270, one capture)

```bash
cd /c/research/Denoising-VolumetricReSTIR
G=outputs/decorr/five_denoisers/gate1
GATE1="VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_DISPLAY=480x270 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=5 VR_WARM=48 VR_IDS=0 VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient VR_DENOISER=optix"
# shellcheck disable=SC2086
bash outputs/decorr/five_capture.sh $G/set ${GATE1% VR_DENOISER=optix} VR_DENOISERS=optix,oidn,relax,reblur
ls $G/set/*.exr | wc -l; grep -c "(Error)" $G/set/run.log
python -c "import json; print(json.load(open('$G/set/c.schedule.json'))['channels'])"
```
Expected: `5` EXRs, `0` errors, and `{'optix': 'D_optix_Denoiser.output', 'oidn': 'D_oidn_Denoiser.dst', 'relax': 'D_relax_ModulateIllumination.output', 'reblur': 'D_reblur_ModulateIllumination.output', 'raw': 'VolumetricReSTIR.accumulated_color'}`.

- [ ] **Step 5: Commit**

```bash
git add Source/RenderPasses/VolumetricReSTIR/Scripts/correlation_pose.py
git add -f outputs/decorr/five_capture.sh
git commit -m "correlation_pose.py: VR_DENOISERS captures several denoisers on the same frames with the raw one (the schedule's channels name them; the single-denoiser path is bit-identical, gate 1); five_capture.sh runs one capture with a clean environment, one Mogwai at a time"
```

---

### Task 4: gates 2 and 3 — the shared graph changes nothing, and it fits

**Files:**
- Create: `outputs/decorr/five_gate.py`
- Create: `outputs/decorr/five_gate2.py`
- Test: `outputs/decorr/test_five_gate.py`

**Interfaces:**
- Consumes: `five_capture.sh` (Task 3).
- Produces: `five_gate.compare(dir_a, ch_a, dir_b, ch_b) -> {"frames": int, "identical": int, "max_abs": float, "mean_abs": float}` (raises `ValueError` when the runs captured different frames or sizes); `five_gate.captures(run_dir) -> list[int]`.

- [ ] **Step 1: Write the failing tests**

`outputs/decorr/test_five_gate.py`:
```python
"""five_gate.py: one run's channel against another's, frame by frame.

    cd outputs/decorr && python -m unittest test_five_gate -v
"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_gate


def run(root, name, channel, images, frames=(3, 8)):
    d = os.path.join(root, name)
    os.makedirs(d)
    with open(os.path.join(d, "c.schedule.json"), "w") as fh:
        json.dump({"chains": [{"frames": [f]} for f in frames]}, fh)
    for f, img in zip(frames, images):
        cv2.imwrite(os.path.join(d, "c.%s.%d.exr" % (channel, f)), img.astype(np.float32))
    return d


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.img = np.random.default_rng(1).random((6, 5, 3))

    def test_identical_frames(self):
        a = run(self.root, "a", "X.out", [self.img, self.img])
        b = run(self.root, "b", "Y.out", [self.img, self.img])
        self.assertEqual(five_gate.compare(a, "X.out", b, "Y.out"),
                         {"frames": 2, "identical": 2, "max_abs": 0.0, "mean_abs": 0.0})

    def test_a_changed_pixel(self):
        other = self.img.copy()
        other[2, 2, 1] += 0.5
        a = run(self.root, "a", "X.out", [self.img, self.img])
        b = run(self.root, "b", "X.out", [self.img, other])
        r = five_gate.compare(a, "X.out", b, "X.out")
        self.assertEqual(r["identical"], 1)
        self.assertAlmostEqual(r["max_abs"], 0.5, places=5)

    def test_different_frames_or_sizes_raise(self):
        a = run(self.root, "a", "X.out", [self.img, self.img])
        b = run(self.root, "b", "X.out", [self.img, self.img], frames=(3, 9))
        with self.assertRaises(ValueError):
            five_gate.compare(a, "X.out", b, "X.out")
        c = run(self.root, "c", "X.out", [self.img[:4], self.img[:4]])
        with self.assertRaises(ValueError):
            five_gate.compare(a, "X.out", c, "X.out")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_five_gate -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'five_gate'`.

- [ ] **Step 3: Write `five_gate.py`**

`outputs/decorr/five_gate.py`:
```python
"""Gate 2 of the paper's runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E4): one channel of one
run against one channel of another, frame by frame over the first run's captures.

    python five_gate.py <run A> <channel A> <run B> <channel B>

prints {"frames", "identical", "max_abs", "mean_abs"} as JSON (RGB, as captured).
"""
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc  # noqa: E402


def captures(run_dir):
    with open(os.path.join(run_dir, "c.schedule.json")) as fh:
        s = json.load(fh)
    return [f for c in s["chains"] for f in c["frames"]]


def compare(dir_a, ch_a, dir_b, ch_b):
    frames = captures(dir_a)
    if captures(dir_b) != frames:
        raise ValueError("the runs captured different frames: %s vs %s" % (frames, captures(dir_b)))
    identical, max_abs, total, n = 0, 0.0, 0.0, 0
    for f in frames:
        a = mc.read_exr(os.path.join(dir_a, "c.%s.%d.exr" % (ch_a, f)))[..., :3].astype(np.float64)
        b = mc.read_exr(os.path.join(dir_b, "c.%s.%d.exr" % (ch_b, f)))[..., :3].astype(np.float64)
        if a.shape != b.shape:
            raise ValueError("frame %d: %s vs %s" % (f, a.shape, b.shape))
        d = np.abs(a - b)
        identical += int(not d.any())
        max_abs = max(max_abs, float(d.max()))
        total += float(d.sum())
        n += d.size
    return {"frames": len(frames), "identical": identical, "max_abs": max_abs, "mean_abs": total / n}


if __name__ == "__main__":
    print(json.dumps(compare(*sys.argv[1:5])))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m unittest test_five_gate -v 2>&1 | tail -n 3`
Expected: `Ran 3 tests ... OK`.

- [ ] **Step 5: Gate 2's captures** (cathedral at one bounce: surfaces and a medium, so both NRD halves, the OptiX guides and OIDN all act; M cap 200 and 5 mutations, as the main runs)

```bash
cd /c/research/Denoising-VolumetricReSTIR
G=outputs/decorr/five_denoisers/gate2
BASE="VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_DISPLAY=960x540 VR_CHAINS=1 VR_PER_CHAIN=2 VR_SPACING=5 VR_WARM=48 VR_IDS=0 VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=light,depth,select,flight VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
# shellcheck disable=SC2086
bash outputs/decorr/five_capture.sh $G/multi $BASE VR_DENOISERS=optix,oidn,relax,reblur
for k in 1 2; do
  # shellcheck disable=SC2086
  bash outputs/decorr/five_capture.sh $G/optix$k $BASE VR_DENOISER=optix
  # shellcheck disable=SC2086
  bash outputs/decorr/five_capture.sh $G/oidn$k $BASE VR_DENOISER=oidn
  # shellcheck disable=SC2086
  bash outputs/decorr/five_capture.sh $G/relax$k $BASE VR_DENOISER=nrd VR_NRD_METHOD=RelaxDiffuseSh
  # shellcheck disable=SC2086
  bash outputs/decorr/five_capture.sh $G/reblur$k $BASE VR_DENOISER=nrd VR_NRD_METHOD=ReblurDiffuseSh
done
# shellcheck disable=SC2086
bash outputs/decorr/five_capture.sh $G/raw $BASE
grep -c "(Error)" $G/*/run.log
```
Expected: every run.log `0` errors (10 runs, about 10 minutes).

- [ ] **Step 6: Gate 2's verdict**

`outputs/decorr/five_gate2.py`:
```python
"""Gate 2's verdict (paper spec E4): each denoiser's channel in the four-denoiser capture against its single capture
with the same seeds -- bit for bit where two single captures agree bit for bit, otherwise within twice their mean
difference -- and, for information, the shared graph's raw frame against a run with no denoiser.

    python five_gate2.py outputs/decorr/five_denoisers/gate2
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_gate as fg  # noqa: E402

SINGLE = {"optix": "Denoiser.output", "oidn": "Denoiser.dst", "relax": "ModulateIllumination.output",
          "reblur": "ModulateIllumination.output"}


def verdict(g):
    with open(os.path.join(g, "multi", "c.schedule.json")) as fh:
        multi = json.load(fh)["channels"]
    ok = True
    for d, ch in SINGLE.items():
        own = fg.compare(os.path.join(g, d + "1"), ch, os.path.join(g, d + "2"), ch)
        shared = fg.compare(os.path.join(g, "multi"), multi[d], os.path.join(g, d + "1"), ch)
        if own["identical"] == own["frames"]:
            passed = shared["identical"] == shared["frames"]
        else:
            passed = shared["mean_abs"] <= 2 * own["mean_abs"]
        ok = ok and passed
        print("%-7s alone twice %s | shared vs alone %s  %s" % (d, own, shared, "PASS" if passed else "FAIL"))
    raw = fg.compare(os.path.join(g, "multi"), multi["raw"], os.path.join(g, "raw"), "VolumetricReSTIR.accumulated_color")
    print("raw (information only): shared graph vs no denoiser %s" % raw)
    print("GATE 2 " + ("PASSED" if ok else "FAILED"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if verdict(sys.argv[1]) else 1)
```
Run: `cd /c/research/Denoising-VolumetricReSTIR && python outputs/decorr/five_gate2.py outputs/decorr/five_denoisers/gate2`
Expected: four `PASS` lines and `GATE 2 PASSED`. A `FAIL` stops the plan: find which input differs (systematic-debugging) before any E3 run.

- [ ] **Step 7: Gate 3: memory at 1080p on the heaviest setup**

```bash
cd /c/research/Denoising-VolumetricReSTIR
G3=outputs/decorr/five_denoisers/gate3; mkdir -p $G3
( while true; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits; sleep 1; done ) > $G3/mem.txt &
MP=$!
bash outputs/decorr/five_capture.sh $G3/multi VR_SCENE=bunnycathedral VR_DENSITY_MULT=0.3 VR_MAX_BOUNCES=2 VR_DISPLAY=1920x1080 VR_CHAINS=1 VR_PER_CHAIN=1 VR_SPACING=5 VR_WARM=32 VR_IDS=0 VR_MTHRESH=200 VR_MUTATIONS=5 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient VR_DENOISERS=optix,oidn,relax,reblur
kill $MP
echo "peak MiB: $(sort -n $G3/mem.txt | tail -1)"; ls $G3/multi/c.*.exr | wc -l; grep -c "(Error)" $G3/multi/run.log
```
Expected: peak below 7900 MiB, `5` EXRs, `0` errors. If the peak reaches 7900 MiB or the run errors out of memory: the queue runs with `FIVE_SETS="optix,oidn relax,reblur"` (two graphs), and Steps 5–6 are repeated for each set (`VR_DENOISERS=optix,oidn` and `VR_DENOISERS=relax,reblur`, comparing only their channels).

- [ ] **Step 8: Commit**

```bash
git add -f outputs/decorr/five_gate.py outputs/decorr/five_gate2.py outputs/decorr/test_five_gate.py
git commit -m "five_gate.py / five_gate2.py: gate 2 of the paper's runs (each denoiser in the shared graph against its single capture with the same seeds) -- <paste the four PASS lines' verdicts>; gate 3: four denoisers at 1080p on the two-bounce cathedral peak at <peak> MiB"
```
(Fill the two `<...>` with the measured values before committing.)

---

### Task 5: in-medium metrics, and the 17 references re-rendered (E2)

**Files:**
- Create: `outputs/decorr/medium_metrics.py`
- Create: `outputs/decorr/ref_change.py`
- Create: `outputs/decorr/run_five_refs.sh`
- Test: `outputs/decorr/test_medium_metrics.py`

**Interfaces:**
- Consumes: `paper_figure.prepare` (for the test only), `m_corr.Y_RGB`, `m_corr.read_exr`.
- Produces: `medium_metrics.relmse(img, ref, mask) -> float` (paper_figure.prepare's measure); `medium_metrics.brightness(img, ref, mask) -> float`; `medium_metrics.accumulations(ref_dir) -> list[np.ndarray]` (raises `FileNotFoundError` below two); `medium_metrics.own_relmse(ref_dir, mask) -> float`; `ref_change.change(root, label) -> dict(mean_ratio, relmse_old_vs_new, own_relmse_new, own_relmse_old)`; `outputs/decorr/five_denoisers/ref_change.json`.

- [ ] **Step 1: Write the failing tests**

`outputs/decorr/test_medium_metrics.py`:
```python
"""medium_metrics.py and ref_change.py on synthetic runs.

    cd outputs/decorr && python -m unittest test_medium_metrics -v
"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medium_metrics as mm
import paper_figure as pf
import ref_change

RNG = np.random.default_rng(5)
H, W = 160, 200


def write_rgb(path, rgb):
    cv2.imwrite(path, rgb[..., ::-1].astype(np.float32))


def read_rgb(path):
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)[..., :3][..., ::-1].astype(np.float64)


def label_tree(root, scale_new=1.0):
    lab = os.path.join(root, "lab")
    for sub in ("ref", "ref_residual", "noreuse", "a", "b"):
        os.makedirs(os.path.join(lab, sub))
    ref = 0.4 + 0.2 * RNG.random((H, W, 3))
    for sub, s in (("ref", scale_new), ("ref_residual", 1.0)):
        write_rgb(os.path.join(lab, sub, "c.Accum.output.1023.exr"), s * ref * 1.02)
        write_rgb(os.path.join(lab, sub, "c.Accum.output.2047.exr"), s * ref)
    mask = np.zeros((H, W), bool)
    mask[30:130, 40:160] = True
    np.save(os.path.join(lab, "noreuse", "c.medium.npy"), mask)
    for cfg, noise in (("a", 0.3), ("b", 0.05)):
        with open(os.path.join(lab, cfg, "c.schedule.json"), "w") as fh:
            json.dump({"chains": [{"frames": [7]}], "channel": "VolumetricReSTIR.accumulated_color"}, fh)
        write_rgb(os.path.join(lab, cfg, "c.VolumetricReSTIR.accumulated_color.7.exr"),
                  scale_new * ref * (1 + noise * RNG.standard_normal((H, W, 1))))
    return lab, mask


class TestRelmse(unittest.TestCase):
    def test_matches_paper_figure(self):
        with tempfile.TemporaryDirectory() as root:
            lab, mask = label_tree(root)
            p = pf.prepare(root, "lab", "a", "b")
            ref = read_rgb(os.path.join(lab, "ref", "c.Accum.output.2047.exr"))
            for cfg, cropped in zip(("a", "b"), p.imgs):
                full = read_rgb(os.path.join(lab, cfg, "c.VolumetricReSTIR.accumulated_color.7.exr"))
                self.assertAlmostEqual(mm.relmse(full, ref, mask), p.relmse(cropped), places=9)

    def test_size_mismatch_raises(self):
        mask = np.ones((10, 12), bool)
        with self.assertRaises(ValueError):
            mm.relmse(np.ones((10, 10, 3)), np.ones((10, 12, 3)), mask)
        with self.assertRaises(ValueError):
            mm.relmse(np.ones((10, 12, 3)), np.ones((10, 12, 3)), np.ones((10, 10), bool))

    def test_brightness(self):
        ref = 0.5 + RNG.random((8, 9, 3))
        mask = np.ones((8, 9), bool)
        self.assertAlmostEqual(mm.brightness(1.1 * ref, ref, mask), 1.1, places=9)

    def test_accumulations_need_two_files(self):
        with tempfile.TemporaryDirectory() as root:
            write_rgb(os.path.join(root, "c.Accum.output.2047.exr"), np.ones((4, 4, 3)))
            with self.assertRaises(FileNotFoundError):
                mm.accumulations(root)


class TestRefChange(unittest.TestCase):
    def test_a_brighter_new_reference(self):
        with tempfile.TemporaryDirectory() as root:
            label_tree(root, scale_new=1.05)
            c = ref_change.change(root, "lab")
            self.assertAlmostEqual(c["mean_ratio"], 1.05, places=4)
            self.assertGreater(c["relmse_old_vs_new"], 0.0)
            self.assertAlmostEqual(c["own_relmse_new"], c["own_relmse_old"], places=6)

    def test_a_missing_old_reference_raises(self):
        with tempfile.TemporaryDirectory() as root:
            lab, _ = label_tree(root)
            for f in os.listdir(os.path.join(lab, "ref_residual")):
                os.rename(os.path.join(lab, "ref_residual", f), os.path.join(lab, f))
            with self.assertRaises(FileNotFoundError):
                ref_change.change(root, "lab")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_medium_metrics -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'medium_metrics'`.

- [ ] **Step 3: Write `medium_metrics.py` and `ref_change.py`**

`outputs/decorr/medium_metrics.py`:
```python
"""In-medium image metrics for the paper's runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md):
paper_figure.prepare's relMSE (the noreuse run's medium mask; luminance clipped at the reference's brightest 0.5%
there), the mean brightness against the reference's, and a reference's own relMSE. Frame, reference and mask must
have one size: a mismatch raises instead of broadcasting.
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc  # noqa: E402


def _check(img, ref, mask):
    if img.shape[:2] != ref.shape[:2] or mask.shape != ref.shape[:2]:
        raise ValueError("sizes differ: frame %s, reference %s, mask %s" % (img.shape[:2], ref.shape[:2], mask.shape))
    if not mask.any():
        raise ValueError("empty medium mask")


def relmse(img, ref, mask):
    _check(img, ref, mask)
    lref = ref @ mc.Y_RGB
    cl = np.percentile(lref[mask], 99.5)
    d = (np.minimum(img @ mc.Y_RGB, cl) - np.minimum(lref, cl))[mask]
    return float(np.mean(d ** 2) / max(np.mean(np.minimum(lref, cl)[mask] ** 2), 1e-20))


def brightness(img, ref, mask):
    _check(img, ref, mask)
    return float((img @ mc.Y_RGB)[mask].mean() / max((ref @ mc.Y_RGB)[mask].mean(), 1e-20))


def accumulations(ref_dir):
    """A reference run's accumulations, fewest frames first (correlation_pose.py writes FRAMES/2 and FRAMES)."""
    paths = sorted(glob.glob(os.path.join(ref_dir, "c.Accum.output.*.exr")), key=lambda p: int(p.split(".")[-2]))
    if len(paths) < 2:
        raise FileNotFoundError("%s holds %d accumulations, not 2" % (ref_dir, len(paths)))
    return [mc.read_exr(p)[..., :3][..., ::-1].astype(np.float64) for p in paths]


def own_relmse(ref_dir, mask):
    """The reference's own error: its half accumulation against its full one (their difference has the full one's
    variance: V-C7's measure)."""
    half, full = accumulations(ref_dir)[-2:]
    return relmse(half, full, mask)
```

`outputs/decorr/ref_change.py`:
```python
"""How far each re-rendered reference moved (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E2):
<label>/ref (rendered after a2a3aa8) against <label>/ref_residual (before it), in the label's medium
(noreuse/c.medium.npy).

    python ref_change.py <root> <label> [<label> ...] [--out F]

Per label: the new reference's mean luminance over the old one's, the relMSE of the old against the new, and each
one's own relMSE (two independent references differ by about the sum of their own errors when nothing changed).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medium_metrics as mm  # noqa: E402


def change(root, label):
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    new = mm.accumulations(os.path.join(root, label, "ref"))
    old = mm.accumulations(os.path.join(root, label, "ref_residual"))
    return {"mean_ratio": mm.brightness(new[-1], old[-1], mask),
            "relmse_old_vs_new": mm.relmse(old[-1], new[-1], mask),
            "own_relmse_new": mm.relmse(new[-2], new[-1], mask),
            "own_relmse_old": mm.relmse(old[-2], old[-1], mask)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("labels", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = {label: change(a.root, label) for label in a.labels}
    for label, c in out.items():
        print("%-24s new/old mean %.4f  relMSE old vs new %.5f  own: new %.5f old %.5f"
              % (label, c["mean_ratio"], c["relmse_old_vs_new"], c["own_relmse_new"], c["own_relmse_old"]))
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w") as fh:
            json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m unittest test_medium_metrics -v 2>&1 | tail -n 3`
Expected: `Ran 6 tests ... OK`.

- [ ] **Step 5: Write `run_five_refs.sh`**

`outputs/decorr/run_five_refs.sh`:
```bash
#!/bin/bash
# The 17 gallery references re-rendered by the fixed reference renderer (a2a3aa8; paper spec E2): each label's pre-fix
# reference renamed to ref_residual (kept), the new one rendered by run_study.sh refs at 1080p with the old one's
# frames and samples, then ref_change.py. Resumable: a label whose new reference holds its last accumulation is
# skipped; a half-written one is renamed aside (ref_partial_<time>), never deleted. Log: five_refs.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/five_refs.log
LABELS="bunnycathedral_d0.3 bunnyspot bunnysoftbox bunnyinside bunnyback_g0.8 bunnystripes explosion bunnylanterns wdassunset_g0.85 plumeback_g0.9 plumeconcert_g0.6 emeraldnight_d3 explosiondusk_b2 bunnycathedral_d0.3_b2 bunnyback_g0.8_b2 bunnysoftbox_b2 wdassunset_g0.85_b2"
field() { python -c "import json, sys; s = json.load(open(sys.argv[1] + '/c.schedule.json')); print($2)" "$1"; }
finished() { [ -f "$1/c.schedule.json" ] && [ -f "$1/c.Accum.output.$(field "$1" "s['reference_frames'][-1]").exr" ]; }
echo "[$(date +%H:%M:%S)] refs start" >> "$LOG"
for L in $LABELS; do
    d=$O/$L/ref
    old=$O/$L/ref_residual
    if [ ! -d "$old" ]; then
        [ -d "$d" ] || { echo "[$(date +%H:%M:%S)] $L: no reference to keep; abort" >> "$LOG"; exit 1; }
        mv "$d" "$old"
    fi
    if finished "$d"; then echo "[$(date +%H:%M:%S)] $L: kept" >> "$LOG"; continue; fi
    [ -d "$d" ] && mv "$d" "$O/$L/ref_partial_$(date +%Y%m%d%H%M%S)"
    n=$(field "$old" "s['accumulated'][-1]")
    spp=$(field "$old" "s['env'].get('VR_SPP', '16')")
    STUDY_DISPLAY=1920x1080 STUDY_REF_FRAMES="$n" STUDY_REF_SPP="$spp" bash "$O/run_study.sh" refs "$L" >> "$LOG" 2>&1
    finished "$d" || { echo "[$(date +%H:%M:%S)] $L: FAILED, no final accumulation (see $d/run.log)" >> "$LOG"; exit 1; }
done
# shellcheck disable=SC2086
python "$O/ref_change.py" "$O" $LABELS --out "$O/five_denoisers/ref_change.json" >> "$LOG" 2>&1
echo "[$(date +%H:%M:%S)] refs done" >> "$LOG"
```

- [ ] **Step 6: Commit, then render the references** (1–2 hours; one Mogwai at a time)

```bash
cd /c/research/Denoising-VolumetricReSTIR
git add -f outputs/decorr/medium_metrics.py outputs/decorr/ref_change.py outputs/decorr/run_five_refs.sh outputs/decorr/test_medium_metrics.py
git commit -m "medium_metrics.py (paper_figure's in-medium relMSE, brightness, a reference's own relMSE; sizes must agree), ref_change.py and run_five_refs.sh: the 17 gallery references re-rendered by the fixed reference renderer, the old ones kept as ref_residual"
nohup bash outputs/decorr/run_five_refs.sh > outputs/decorr/five_refs.stdout 2>&1 & disown
```
Watch `outputs/decorr/five_refs.log` (Monitor, `refs done|FAILED|abort`).
Expected: `refs done`; `five_denoisers/ref_change.json` with 17 labels. Lights outside the medium: `mean_ratio` within about 1% of 1 and `relmse_old_vs_new` about `own_relmse_new + own_relmse_old`. `bunnylanterns` and `bunnyinside` (lights inside) may move more. Record anything beyond that in the ledger notes; a scene whose new reference is darker or brighter than its old by more than 2% gets a sentence in §6.1.

---

### Task 6: the 152 runs (E3)

**Files:**
- Create: `outputs/decorr/five_runs.py`
- Create: `outputs/decorr/run_five.sh`
- Test: `outputs/decorr/test_five_runs.py`

**Interfaces:**
- Consumes: `five_capture.sh` (Task 3), gates passed (Task 4), new references (Task 5).
- Produces: `five_runs.SETUPS` (19 labels), `five_runs.HISTORIES = ("c200", "ship")`, `five_runs.runs(sets=("optix,oidn,relax,reblur",)) -> list[dict(label, config, captures, env)]`, `five_runs.complete(run_dir, captures) -> bool`, `five_runs.scene_env(label) -> list[str]`; run directories `outputs/decorr/<label>/fd_{c200,ship}_m{0,5}` (four denoisers + raw) and `fr_{c200,ship}_m{0,5}` (RR).

- [ ] **Step 1: Write the failing tests**

`outputs/decorr/test_five_runs.py`:
```python
"""five_runs.py: the paper's planned captures, and the finished-run check.

    cd outputs/decorr && python -m unittest test_five_runs -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_runs as fr


def env_of(r):
    return dict(kv.split("=", 1) for kv in r["env"])


class TestPlan(unittest.TestCase):
    def test_scene_env_follows_run_study(self):
        self.assertEqual(fr.scene_env("bunnycathedral_d0.3_b2"),
                         ["VR_SCENE=bunnycathedral", "VR_DENSITY_MULT=0.3", "VR_MAX_BOUNCES=2"])
        self.assertEqual(fr.scene_env("wdasstorm_g0.5"), ["VR_SCENE=wdasstorm", "VR_PHASE_G=0.5"])
        self.assertEqual(fr.scene_env("explosion"), ["VR_SCENE=explosion"])

    def test_152_captures_the_long_history_first(self):
        runs = fr.runs()
        self.assertEqual(len(runs), 19 * 2 * 2 * 2)
        self.assertEqual(len({(r["label"], r["config"]) for r in runs}), len(runs))
        hist = [r["config"].split("_")[1] for r in runs]
        self.assertEqual(hist, ["c200"] * (len(runs) // 2) + ["ship"] * (len(runs) // 2))

    def test_a_two_bounce_mutated_long_history_capture(self):
        r = next(r for r in fr.runs() if r["label"] == "bunnysoftbox_b2" and r["config"] == "fd_c200_m5")
        env = env_of(r)
        self.assertEqual(env["VR_MTHRESH"], "200")
        self.assertEqual(env["VR_MUT_STRAT"], "light,depth,select,flight,direction,distance,rebounce")
        self.assertEqual((env["VR_MUTATIONS"], env["VR_MUT_AFTER_SPATIAL"]), ("5", "1"))
        self.assertEqual(env["VR_DENOISERS"], "optix,oidn,relax,reblur")
        self.assertEqual((env["VR_DISPLAY"], env["VR_CHAINS"], env["VR_PER_CHAIN"]), ("1920x1080", "2", "1"))
        self.assertEqual(env["VR_NRD_SPLIT"], "1")
        self.assertEqual(r["captures"], 10)  # 2 frames x (4 denoisers + raw)

    def test_the_shipped_rr_capture_of_a_small_setup(self):
        r = next(r for r in fr.runs() if r["label"] == "bunnyswarm_d3" and r["config"] == "fr_ship_m0")
        env = env_of(r)
        self.assertNotIn("VR_MTHRESH", env)
        self.assertNotIn("VR_MUTATIONS", env)
        self.assertEqual((env["VR_DENOISER"], env["VR_DISPLAY"], r["captures"]), ("rr", "960x540", 2))

    def test_one_bounce_setups_get_the_four_first_vertex_moves(self):
        r = next(r for r in fr.runs() if r["label"] == "bunnylanterns" and r["config"] == "fr_c200_m5")
        self.assertEqual(env_of(r)["VR_MUT_STRAT"], "light,depth,select,flight")

    def test_split_sets(self):
        runs = fr.runs(("optix,oidn", "relax,reblur"))
        names = {r["config"] for r in runs if r["label"] == "explosion"}
        self.assertTrue({"fd1_c200_m0", "fd2_ship_m5", "fr_ship_m5"} <= names)
        self.assertEqual(len(runs), 19 * 2 * 2 * 3)
        self.assertEqual(next(r for r in runs if r["config"] == "fd1_c200_m0")["captures"], 6)


class TestComplete(unittest.TestCase):
    def make(self, root, n, log="frames rendered"):
        with open(os.path.join(root, "c.schedule.json"), "w") as fh:
            fh.write("{}")
        with open(os.path.join(root, "run.log"), "w") as fh:
            fh.write(log)
        for i in range(n):
            with open(os.path.join(root, "c.X.output.%d.exr" % i), "w") as fh:
                fh.write("x")

    def test_finished(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 10)
            self.assertTrue(fr.complete(root, 10))

    def test_too_few_or_too_many_captures(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 9)
            self.assertFalse(fr.complete(root, 10))
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 11)
            self.assertFalse(fr.complete(root, 10))

    def test_a_falcor_error(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 10, log="(Error) shader compilation failed")
            self.assertFalse(fr.complete(root, 10))

    def test_nothing_there(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(fr.complete(root, 10))
            self.assertFalse(fr.complete(os.path.join(root, "missing"), 10))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_five_runs -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'five_runs'`.

- [ ] **Step 3: Write `five_runs.py`**

`outputs/decorr/five_runs.py`:
```python
"""The paper's five-denoiser runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E3): the planned
captures in order (M cap 200 first), and whether one has finished.

    python five_runs.py --list [--sets "optix,oidn,relax,reblur"]   one capture a line: label config captures VAR=value...
    python five_runs.py --complete <run dir> <captures>             exit 0 if the run finished, 1 if not
"""
import argparse
import os
import sys

GALLERY_1 = ["bunnycathedral_d0.3", "bunnyspot", "bunnysoftbox", "bunnyinside", "bunnyback_g0.8", "bunnystripes",
             "explosion", "bunnylanterns", "wdassunset_g0.85", "plumeback_g0.9", "plumeconcert_g0.6", "emeraldnight_d3"]
GALLERY_2 = ["explosiondusk_b2", "bunnycathedral_d0.3_b2", "bunnyback_g0.8_b2", "bunnysoftbox_b2", "wdassunset_g0.85_b2"]
SMALL = ["bunnyswarm_d3", "wdasstorm_g0.5"]  # their references are 960x540
SETUPS = GALLERY_1 + GALLERY_2 + SMALL
HISTORIES = ("c200", "ship")
FOUR = "optix,oidn,relax,reblur"
ONE_BOUNCE = "light,depth,select,flight"
TWO_BOUNCE = ONE_BOUNCE + ",direction,distance,rebounce"
LOOK = ["VR_NRD_SPLIT=1", "VR_NRD_SH=1", "VR_NRD_TAA=1", "VR_TAA_LDR=1", "VR_NRD_EMISSION=1", "VR_NRD_VOLMASK=1",
        "VR_VOL_NORMAL=gradient"]  # run_study.sh's LOOK


def scene_env(label):
    """run_study.sh's scene_env: VR_SCENE, then VR_PHASE_G for _g<g>, VR_DENSITY_MULT for _d<m>, VR_MAX_BOUNCES for _b<n>."""
    scene, *mods = label.split("_")
    out = ["VR_SCENE=" + scene]
    for m in mods:
        key = {"g": "VR_PHASE_G", "d": "VR_DENSITY_MULT", "b": "VR_MAX_BOUNCES"}.get(m[:1])
        if key:
            out.append("%s=%s" % (key, m[1:]))
    return out


def runs(sets=(FOUR,)):
    """Every planned capture, in order: dicts with label, config, captures (EXR files when finished) and env."""
    out = []
    for hist in HISTORIES:
        for label in SETUPS:
            base = (scene_env(label) + LOOK
                    + ["VR_DISPLAY=" + ("960x540" if label in SMALL else "1920x1080"), "VR_CHAINS=2", "VR_PER_CHAIN=1",
                       "VR_SPACING=5", "VR_IDS=0"]
                    + (["VR_MTHRESH=200"] if hist == "c200" else []))
            for m in (0, 5):
                env = base + ([] if m == 0 else [
                    "VR_MUTATIONS=5", "VR_MUT_AFTER_SPATIAL=1",
                    "VR_MUT_STRAT=" + (TWO_BOUNCE if label.endswith("_b2") else ONE_BOUNCE)])
                for i, s in enumerate(sets):
                    name = "fd" if len(sets) == 1 else "fd%d" % (i + 1)
                    out.append({"label": label, "config": "%s_%s_m%d" % (name, hist, m),
                                "captures": 2 * (len(s.split(",")) + 1), "env": env + ["VR_DENOISERS=" + s]})
                out.append({"label": label, "config": "fr_%s_m%d" % (hist, m), "captures": 2,
                            "env": env + ["VR_DENOISER=rr"]})
    return out


def complete(run_dir, captures):
    """Finished: a schedule, a run log with no Falcor error, and exactly `captures` EXRs."""
    log = os.path.join(run_dir, "run.log")
    if not (os.path.isfile(os.path.join(run_dir, "c.schedule.json")) and os.path.isfile(log)):
        return False
    with open(log, errors="replace") as fh:
        if "(Error)" in fh.read():
            return False
    return len([f for f in os.listdir(run_dir) if f.startswith("c.") and f.endswith(".exr")]) == captures


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--sets", default=FOUR, help="denoiser sets, space-separated, one graph each")
    ap.add_argument("--complete", nargs=2, metavar=("RUN_DIR", "CAPTURES"))
    a = ap.parse_args(argv)
    if a.complete:
        return 0 if complete(a.complete[0], int(a.complete[1])) else 1
    for r in runs(tuple(a.sets.split())):
        print(r["label"], r["config"], r["captures"], " ".join(r["env"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m unittest test_five_runs -v 2>&1 | tail -n 3`
Expected: `Ran 10 tests ... OK`.

- [ ] **Step 5: Write `run_five.sh`**

`outputs/decorr/run_five.sh`:
```bash
#!/bin/bash
# The paper's five-denoiser runs (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E3): five_runs.py's
# list in order (M cap 200 first), each captured by five_capture.sh into outputs/decorr/<label>/<config>. A run that
# finished (five_runs.py --complete) is kept, so a cut-off queue resumes; a failed one is logged and the queue goes
# on. Starts only with FIVE_MIN_FREE_GB (35) free on C:. FIVE_SETS splits the shared graph (gate 3).
# Log: outputs/decorr/five.log.
set -u
R=/c/research/Denoising-VolumetricReSTIR
cd "$R" || exit 1
O=outputs/decorr
LOG=$O/five.log
mkdir -p "$O/five_denoisers"
free=$(df -BG --output=avail /c | tail -1 | tr -dc 0-9)
if [ "$free" -lt "${FIVE_MIN_FREE_GB:-35}" ]; then
    echo "[$(date +%H:%M:%S)] five: only ${free} GB free on C:, need ${FIVE_MIN_FREE_GB:-35}" | tee -a "$LOG"
    exit 1
fi
echo "[$(date +%H:%M:%S)] five start, ${free} GB free" >> "$LOG"
python "$O/five_runs.py" --list --sets "${FIVE_SETS:-optix,oidn,relax,reblur}" > "$O/five_denoisers/planned.txt" || exit 1
while read -r label cfg n env; do
    d=$O/$label/$cfg
    if python "$O/five_runs.py" --complete "$d" "$n"; then echo "[$(date +%H:%M:%S)] $label/$cfg kept" >> "$LOG"; continue; fi
    t0=$SECONDS
    # shellcheck disable=SC2086
    bash "$O/five_capture.sh" "$d" $env
    if python "$O/five_runs.py" --complete "$d" "$n"; then
        echo "[$(date +%H:%M:%S)] $label/$cfg done $((SECONDS - t0))s" >> "$LOG"
    else
        echo "[$(date +%H:%M:%S)] $label/$cfg FAILED: $(ls "$d"/c.*.exr 2>/dev/null | wc -l) of $n captures (see $d/run.log)" >> "$LOG"
    fi
done < "$O/five_denoisers/planned.txt"
echo "[$(date +%H:%M:%S)] five done, $(df -BG --output=avail /c | tail -1 | tr -dc 0-9) GB free" >> "$LOG"
```

- [ ] **Step 6: Check the space, commit, launch**

```bash
cd /c/research/Denoising-VolumetricReSTIR
df -BG --output=avail /c | tail -1
git add -f outputs/decorr/five_runs.py outputs/decorr/run_five.sh outputs/decorr/test_five_runs.py
git commit -m "five_runs.py and run_five.sh: the paper's 152 captures (19 setups x M cap 200 / shipped x plain / 5 mutations, the four-denoiser graph and RR's), resumable, starting only with 35 GB free"
nohup bash outputs/decorr/run_five.sh > outputs/decorr/five.stdout 2>&1 & disown
```
Expected: at least 35 GB free (if not: list the largest finished-run folders the user may remove, e.g. `outputs/decorr/speed_ab` 9.8 GB and `outputs/decorr/gate` 4.9 GB, as a path list and a PowerShell command for the user, and launch after they free it). Then Monitor `outputs/decorr/five.log` (`done|FAILED|five done|only`), re-arming every 30 minutes; about 11 hours. A session restart kills a nohup'd queue: relaunch the same command; finished runs are kept. Any `FAILED` line: read its `run.log`, fix the cause, relaunch.

---

### Task 7: scoring (E5)

**Files:**
- Create: `outputs/decorr/five_scores.py`
- Test: `outputs/decorr/test_five_scores.py`

**Interfaces:**
- Consumes: `medium_metrics.relmse/brightness/own_relmse` (Task 5), `five_runs.SETUPS/HISTORIES` (Task 6), `artifacts.reference(root, label)`.
- Produces: `five_scores.channels(run_dir) -> {name: channel}`, `five_scores.frames(run_dir, channel) -> list[np.ndarray]`, `five_scores.score(root, label) -> dict`, and `outputs/decorr/five_denoisers/results.json` shaped `{label: {"ref_own_relmse": float, "histories": {"c200"|"ship": {"m0"|"m5": {"optix"|"oidn"|"relax"|"reblur"|"raw"|"rr": {"relmse": [float, float], "mean": float, "brightness": [float, float], "run": "label/config"}}}}}}`.

- [ ] **Step 1: Write the failing tests**

`outputs/decorr/test_five_scores.py`:
```python
"""five_scores.py on a synthetic run tree.

    cd outputs/decorr && python -m unittest test_five_scores -v
"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_scores as fs
import medium_metrics as mm

RNG = np.random.default_rng(3)
H, W = 40, 60
SHARED = {"optix": "D_optix_Denoiser.output", "raw": "VolumetricReSTIR.accumulated_color"}


def write_rgb(path, rgb):
    cv2.imwrite(path, rgb[..., ::-1].astype(np.float32))


def as32(x):
    return x.astype(np.float32).astype(np.float64)


def tree(root):
    lab = os.path.join(root, "bunnyspot")
    os.makedirs(os.path.join(lab, "ref"))
    os.makedirs(os.path.join(lab, "noreuse"))
    ref = 0.5 + 0.1 * RNG.random((H, W, 3))
    write_rgb(os.path.join(lab, "ref", "c.Accum.output.1.exr"), ref * 1.01)
    write_rgb(os.path.join(lab, "ref", "c.Accum.output.3.exr"), ref)
    mask = np.zeros((H, W), bool)
    mask[5:35, 10:50] = True
    np.save(os.path.join(lab, "noreuse", "c.medium.npy"), mask)
    imgs = {}
    for cfg in ("fd_c200_m0", "fd_c200_m5", "fr_c200_m0", "fr_c200_m5"):
        d = os.path.join(lab, cfg)
        os.makedirs(d)
        chans = SHARED if cfg.startswith("fd") else {"rr": "DLSSDPass.output"}
        sched = {"chains": [{"frames": [10]}, {"frames": [20]}],
                 "channel": "VolumetricReSTIR.accumulated_color" if cfg.startswith("fd") else "DLSSDPass.output"}
        if cfg.startswith("fd"):
            sched["channels"] = SHARED
        with open(os.path.join(d, "c.schedule.json"), "w") as fh:
            json.dump(sched, fh)
        for name, ch in chans.items():
            for f in (10, 20):
                img = ref * (1 + (0.2 if cfg.endswith("m0") else 0.05) * RNG.standard_normal((H, W, 1)))
                write_rgb(os.path.join(d, "c.%s.%d.exr" % (ch, f)), img)
                imgs[(cfg, name, f)] = img
    return lab, as32(ref), mask, imgs


class TestScore(unittest.TestCase):
    def test_every_channel_scored_on_both_kept_frames(self):
        with tempfile.TemporaryDirectory() as root:
            _, ref, mask, imgs = tree(root)
            c = fs.score(root, "bunnyspot")["histories"]["c200"]
            self.assertEqual(set(c["m0"]), {"optix", "raw", "rr"})
            want = np.mean([mm.relmse(as32(imgs[("fd_c200_m5", "optix", f)]), ref, mask) for f in (10, 20)])
            self.assertAlmostEqual(c["m5"]["optix"]["mean"], want, places=9)
            self.assertLess(c["m5"]["rr"]["mean"], c["m0"]["rr"]["mean"])
            self.assertEqual(c["m0"]["rr"]["run"], "bunnyspot/fr_c200_m0")
            self.assertEqual(len(c["m5"]["raw"]["brightness"]), 2)

    def test_a_missing_frame_raises(self):
        with tempfile.TemporaryDirectory() as root:
            lab, _, _, _ = tree(root)
            os.rename(os.path.join(lab, "fr_c200_m5", "c.DLSSDPass.output.20.exr"), os.path.join(lab, "moved.exr"))
            with self.assertRaises(FileNotFoundError):
                fs.score(root, "bunnyspot")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_five_scores -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'five_scores'`.

- [ ] **Step 3: Write `five_scores.py`**

`outputs/decorr/five_scores.py`:
```python
"""The paper's five-denoiser table (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E5), from
run_five.sh's runs: for every setup, history (c200: M cap 200; ship: the shipped cap), config (m0 plain, m5 five
mutations) and channel (optix, oidn, relax, reblur and raw from the shared graph; rr from its own), the in-medium
relMSE of each kept frame (medium_metrics.relmse) and their mean, and the mean brightness over the reference's; per
setup, the reference's own relMSE.

    python five_scores.py <root> [--out <root>/five_denoisers/results.json]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_runs  # noqa: E402
import m_corr as mc  # noqa: E402
import medium_metrics as mm  # noqa: E402


def schedule(run_dir):
    with open(os.path.join(run_dir, "c.schedule.json")) as fh:
        return json.load(fh)


def channels(run_dir):
    """{name: capture channel}: the shared graph's `channels` (raw included), else RR's single channel."""
    s = schedule(run_dir)
    return dict(s["channels"]) if s.get("channels") else {"rr": s["channel"]}


def frames(run_dir, channel):
    """The first capture of every chain, RGB; a missing one raises."""
    out = []
    for c in schedule(run_dir)["chains"]:
        path = os.path.join(run_dir, "c.%s.%d.exr" % (channel, c["frames"][0]))
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        out.append(mc.read_exr(path)[..., :3][..., ::-1].astype(np.float64))
    return out


def run_dirs(root, label, hist, m):
    """One configuration's captures: the shared graph(s) fd*_<hist>_m<m> and RR's fr_<hist>_m<m>."""
    d = os.path.join(root, label)
    names = sorted(n for n in os.listdir(d) if n.startswith("fd") and n.endswith("_%s_m%d" % (hist, m)))
    names.append("fr_%s_m%d" % (hist, m))
    return [os.path.join(d, n) for n in names if os.path.isdir(os.path.join(d, n))]


def score(root, label):
    ref = art.reference(root, label)
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    out = {"ref_own_relmse": mm.own_relmse(os.path.join(root, label, "ref"), mask), "histories": {}}
    for hist in five_runs.HISTORIES:
        for m in (0, 5):
            for run_dir in run_dirs(root, label, hist, m):
                for name, ch in channels(run_dir).items():
                    imgs = frames(run_dir, ch)
                    rel = [mm.relmse(i, ref, mask) for i in imgs]
                    out["histories"].setdefault(hist, {}).setdefault("m%d" % m, {})[name] = {
                        "relmse": rel, "mean": float(np.mean(rel)),
                        "brightness": [mm.brightness(i, ref, mask) for i in imgs],
                        "run": os.path.relpath(run_dir, root).replace(os.sep, "/")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    results = {}
    for label in five_runs.SETUPS:
        d = os.path.join(a.root, label)
        if os.path.isdir(d) and any(n.startswith(("fd", "fr")) for n in os.listdir(d)):
            results[label] = score(a.root, label)
    out = a.out or os.path.join(a.root, "five_denoisers", "results.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(results, fh, indent=1)
    for label, r in results.items():
        for hist, cfgs in r["histories"].items():
            if "m0" in cfgs and "m5" in cfgs:
                cuts = ["%s %+.0f%%" % (n, 100 * (cfgs["m5"][n]["mean"] / cfgs["m0"][n]["mean"] - 1))
                        for n in cfgs["m0"] if n in cfgs["m5"]]
                print("%-24s %-4s %s" % (label, hist, "  ".join(cuts)))
    print(out)
    return results


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m unittest test_five_scores -v 2>&1 | tail -n 3`
Expected: `Ran 2 tests ... OK`.

- [ ] **Step 5: Commit, and score when the queue is done**

```bash
cd /c/research/Denoising-VolumetricReSTIR
git add -f outputs/decorr/five_scores.py outputs/decorr/test_five_scores.py
git commit -m "five_scores.py: the paper's five-denoiser table from run_five.sh's runs (in-medium relMSE of both kept frames per channel, brightness over the reference, the reference's own relMSE)"
```
After `five done` in `five.log` with no `FAILED` left: `cd outputs/decorr && python five_scores.py .`
Expected: `five_denoisers/results.json` with 19 labels × 2 histories × 2 configs × 6 channels, and one printed line per label and history with six changes.

---

### Task 8: the new figures, and the approved ones re-scored (E6)

**Files:**
- Create: `outputs/decorr/five_figures.py`
- Test: `outputs/decorr/test_five_figures.py`
- Re-render (keeping copies): `outputs/decorr/figs/variety_*.png`, `figs/variety_rr_*.png`, `figs/gallery_mutations{,_rr,_b2,_b2_rr}.png`

**Interfaces:**
- Consumes: `results.json` (Task 7), `five_scores.channels/frames`, `paper_figure.pick_boxes(a, ref, size, n, mask)`, `artifacts.tonemap(img, k)`, `artifacts.srgb_display`, `variety_figures.EXPOSURE/PAPER_DISPLAY`.
- Produces: `five_figures.cut(results, label, hist, den) -> float`, `five_figures.teaser_setup(results) -> str`, files `figs/teaser_five.png`, `figs/five_strip.png`, `figs/history_chart.pdf`.

- [ ] **Step 1: Load the dataviz skill** (Skill tool, `dataviz`) and read its marks and anti-patterns before Step 4's chart; the chart uses its categorical slots 1 (blue `#2a78d6`) and 2 (orange `#eb6834`), which validate all-pairs.

- [ ] **Step 2: Write the failing tests**

`outputs/decorr/test_five_figures.py`:
```python
"""five_figures.py: the teaser's setup and the chart, on synthetic results.

    cd outputs/decorr && python -m unittest test_five_figures -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_figures as ff


def results(cuts):
    """{label: cut per denoiser at M cap 200}, plain relMSE 0.1 everywhere, the shipped cap halving the cut."""
    out = {}
    for label, c in cuts.items():
        h = {}
        for hist, k in (("c200", 1.0), ("ship", 0.5)):
            h[hist] = {"m0": {d: {"mean": 0.1} for d in ff.DENOISERS},
                       "m5": {d: {"mean": 0.1 * (1 - k * c[i])} for i, d in enumerate(ff.DENOISERS)}}
        out[label] = {"histories": h, "ref_own_relmse": 0.001}
    return out


class TestTeaser(unittest.TestCase):
    def test_the_largest_median_cut(self):
        r = results({"a": [0.9, 0.1, 0.1, 0.1, 0.9], "b": [0.5, 0.5, 0.5, 0.5, 0.5], "c": [0.6, 0.6, 0.2, 0.2, 0.6]})
        self.assertAlmostEqual(ff.cut(r, "b", "c200", "oidn"), 0.5)
        self.assertEqual(ff.teaser_setup(r), "c")  # medians: a 0.1, b 0.5, c 0.6

    def test_a_setup_missing_a_denoiser_is_not_chosen(self):
        r = results({"a": [0.9] * 5, "b": [0.5] * 5})
        del r["a"]["histories"]["c200"]["m5"]["rr"]
        self.assertEqual(ff.teaser_setup(r), "b")


class TestChart(unittest.TestCase):
    def test_writes_the_chart(self):
        r = results({"a": [0.8] * 5, "b": [0.4] * 5})
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "history_chart.pdf")
            ff.history_chart(r, out)
            self.assertGreater(os.path.getsize(out), 1000)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_five_figures -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'five_figures'`.

- [ ] **Step 4: Write `five_figures.py`**

`outputs/decorr/five_figures.py`:
```python
"""The paper's new figures (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E6) from run_five.sh's runs
and five_scores.py's results:
- the teaser: the setup whose median cut over the five denoisers at M cap 200 is largest -- each denoiser before and
  after 5 mutations, and the reference, in the box where plain ReSTIR + OptiX errs most;
- the strip: STRIP's setups, the same layout one row each;
- the history chart: per denoiser, each setup's denoised relMSE with mutations over without, at the shipped cap and
  at M cap 200; and M cap 200 with mutations over plain ReSTIR at the shipped cap.

    python five_figures.py <root> [--results <root>/five_denoisers/results.json]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_scores  # noqa: E402
import m_corr as mc  # noqa: E402
import paper_figure  # noqa: E402
import paper_tables  # noqa: E402
from variety_figures import EXPOSURE, PAPER_DISPLAY  # noqa: E402

DENOISERS = ("optix", "oidn", "relax", "reblur", "rr")
NAMES = {"optix": "OptiX", "oidn": "OIDN", "relax": "NRD RELAX", "reblur": "NRD REBLUR", "rr": "DLSS RR"}
STRIP = ["bunnycathedral_d0.3", "bunnylanterns", "explosiondusk_b2", "bunnyswarm_d3"]
# dataviz reference palette, light mode: categorical slots 1 and 2 (validated all-pairs), text and recessive ink.
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#d9d8d4"


def cut(results, label, hist, den):
    c = results[label]["histories"][hist]
    return 1.0 - c["m5"][den]["mean"] / c["m0"][den]["mean"]


def complete(results, label, hist="c200"):
    c = results[label]["histories"].get(hist, {})
    return all(den in c.get(m, {}) for m in ("m0", "m5") for den in DENOISERS)


def teaser_setup(results):
    ok = [label for label in results if complete(results, label)]
    return max(ok, key=lambda label: float(np.median([cut(results, label, "c200", d) for d in DENOISERS])))


def _frame(root, results, label, hist, m, den):
    run = os.path.join(root, results[label]["histories"][hist]["m%d" % m][den]["run"])
    return five_scores.frames(run, five_scores.channels(run)[den])[0]  # chain 0's capture


def panel(root, results, label, hist="c200"):
    """Before/after per denoiser (chain 0), the reference, the zoom box and the display function."""
    ref = art.reference(root, label)
    mask = np.load(os.path.join(root, label, "noreuse", "c.medium.npy"))
    imgs = {d: (_frame(root, results, label, hist, 0, d), _frame(root, results, label, hist, 5, d)) for d in DENOISERS}
    size = max(64, min(ref.shape[:2]) // 5)
    (y, x), = paper_figure.pick_boxes(imgs["optix"][0], ref, size, n=1, mask=mask)
    if label in PAPER_DISPLAY:
        show = art.srgb_display
    else:
        k = np.percentile((ref @ mc.Y_RGB)[mask], EXPOSURE.get(label, 99.0)) + 1e-9
        show = lambda img: art.tonemap(img, k)  # noqa: E731
    return imgs, ref, show, (y, x, size)


def _row(axes, root, results, label, hist, titles):
    imgs, ref, show, (y, x, s) = panel(root, results, label, hist)
    c = results[label]["histories"][hist]
    cells = []
    for d in DENOISERS:
        cells.append((imgs[d][0], "%s\n%.4f" % (NAMES[d], c["m0"][d]["mean"])))
        cells.append((imgs[d][1], "+ 5 mutations\n%.4f (%+.0f%%)" % (c["m5"][d]["mean"], -100 * cut(results, label, hist, d))))
    cells.append((ref, "reference"))
    for ax, (img, title) in zip(axes, cells):
        ax.imshow(show(img[y:y + s, x:x + s]), interpolation="nearest")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_edgecolor(GRID)
        ax.set_title(title, fontsize=6, color=INK if titles else MUTED)
    axes[0].set_ylabel(paper_tables.SETUP_NAMES.get(label, label), fontsize=6, color=INK)


def strip(root, results, labels, out, hist="c200"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(labels), 11, figsize=(7.1, 0.82 * len(labels) + 0.35), squeeze=False,
                             gridspec_kw={"wspace": 0.03, "hspace": 0.32})
    for i, label in enumerate(labels):
        _row(axes[i], root, results, label, hist, titles=True)
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def history_chart(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.4), gridspec_kw={"wspace": 0.28})
    labels = [l for l in results if complete(results, l) and complete(results, l, "ship")]
    for i, d in enumerate(DENOISERS):
        for hist, colour, dx in (("ship", BLUE, -0.12), ("c200", ORANGE, 0.12)):
            r = [results[l]["histories"][hist]["m5"][d]["mean"] / results[l]["histories"][hist]["m0"][d]["mean"]
                 for l in labels]
            a.scatter(np.full(len(r), i + dx), r, s=22, color=colour, edgecolors="white", linewidths=0.8, zorder=3,
                      label=("shipped cap" if hist == "ship" else "M cap 200") if i == 0 else None)
            a.plot([i + dx - 0.09, i + dx + 0.09], [np.median(r)] * 2, color=INK, lw=1.2, zorder=4)
        r = [results[l]["histories"]["c200"]["m5"][d]["mean"] / results[l]["histories"]["ship"]["m0"][d]["mean"]
             for l in labels]
        b.scatter(np.full(len(r), i), r, s=22, color=ORANGE, edgecolors="white", linewidths=0.8, zorder=3)
        b.plot([i - 0.09, i + 0.09], [np.median(r)] * 2, color=INK, lw=1.2, zorder=4)
    for ax, ylabel in ((a, "relMSE, 5 mutations / plain"), (b, "M cap 200 + 5 mutations /\nplain at the shipped cap")):
        ax.set_yscale("log")
        ax.axhline(1.0, color=MUTED, lw=0.8, zorder=1)
        ax.set_xticks(range(len(DENOISERS)))
        ax.set_xticklabels([NAMES[d] for d in DENOISERS], fontsize=7, color=INK)
        ax.set_ylabel(ylabel, fontsize=7, color=INK)
        ax.tick_params(axis="y", labelsize=7, colors=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.5, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    a.legend(fontsize=7, frameon=False, loc="lower left")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    with open(a.results or os.path.join(a.root, "five_denoisers", "results.json")) as fh:
        results = json.load(fh)
    figs = os.path.join(a.root, "figs")
    t = teaser_setup(results)
    print("teaser:", t)
    strip(a.root, results, [t], os.path.join(figs, "teaser_five.png"))
    strip(a.root, results, STRIP, os.path.join(figs, "five_strip.png"))
    history_chart(results, os.path.join(figs, "history_chart.pdf"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `python -m unittest test_five_figures -v 2>&1 | tail -n 3`
Expected: `Ran 3 tests ... OK`.

- [ ] **Step 6: Make the figures and look at them**

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python five_figures.py .
```
Expected: prints the teaser's setup; writes `figs/teaser_five.png`, `figs/five_strip.png`, `figs/history_chart.pdf`. Read each one (the Read tool shows PNG and PDF). Check: labels legible at full-width print (7 in), no overlapping titles, each zoom box inside the medium, both histories' markers distinguishable. Fix sizes in the code if not, re-run the tests, re-make.

- [ ] **Step 7: Re-score the approved figures against the new references** (copies of the current ones kept first)

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr
mkdir -p figs/pre_fix_references && cp -n figs/variety_*.png figs/gallery_mutations*.png figs/pre_fix_references/
python variety_figures.py . --force
python variety_figures.py . --denoiser rr --force
python gallery_figure.py . --out figs/gallery_mutations.png
python gallery_figure.py . --denoiser rr --out figs/gallery_mutations_rr.png
python gallery_figure.py . --two-bounce --out figs/gallery_mutations_b2.png
python gallery_figure.py . --two-bounce --denoiser rr --out figs/gallery_mutations_b2_rr.png
```
Expected: each scene's printed `relMSE in the medium a -> b (x%)`. Compare with the copies: the images are the same renders, only the reference panel and the numbers can change. Note every number that moved by more than its reference's own relMSE, for §6.5.

- [ ] **Step 8: Commit**

```bash
cd /c/research/Denoising-VolumetricReSTIR
git add -f outputs/decorr/five_figures.py outputs/decorr/test_five_figures.py
git commit -m "five_figures.py: the teaser (largest median cut over the five denoisers at M cap 200), the five-denoiser strip and the history chart; the approved galleries re-scored against the new references"
```

---

### Task 9: the moving camera with all seven moves (E7)

**Files:**
- Create: `Source/RenderPasses/VolumetricReSTIR/Scripts/cam_pose.py` (from the scratchpad's `cam_pose.py`, header updated)
- Create: `outputs/decorr/motion_score.py`

**Interfaces:**
- Consumes: `five_capture.sh` with `FIVE_SCRIPT=cam_pose.py` (Task 3), `medium_metrics.relmse/brightness` (Task 5), `five_scores.frames/schedule` (Task 7).
- Produces: runs `outputs/decorr/previews/glowcam/lanternglow_b2/cam7_{optix,rr,raw}_m{0,5}`, and `outputs/decorr/five_denoisers/motion.json` = `{output: {"m0": relMSE, "m5": relMSE, "change": float, "brightness_m0": float, "brightness_m5": float}}`.

- [ ] **Step 1: Move the script into the repository**

```bash
cd /c/research/Denoising-VolumetricReSTIR
S="C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
cp "$S/cam_pose.py" Source/RenderPasses/VolumetricReSTIR/Scripts/cam_pose.py
```
Then replace its first comment line with
```python
# The glowing construct (still volume) under a MOVING camera, through a denoiser (paper spec 2026-10-20, E7): the camera
```
and keep the rest as it is.

- [ ] **Step 2: The six runs** (960×540, as the earlier test; about 30 minutes; after the E3 queue, one Mogwai at a time)

```bash
cd /c/research/Denoising-VolumetricReSTIR
C=outputs/decorr/previews/glowcam/lanternglow_b2
LOOKENV="VR_NRD_SPLIT=1 VR_NRD_SH=1 VR_NRD_TAA=1 VR_TAA_LDR=1 VR_NRD_EMISSION=1 VR_NRD_VOLMASK=1 VR_VOL_NORMAL=gradient"
for den in optix rr none; do
  name=$den; [ $den = none ] && name=raw
  for m in 0 5; do
    MUT=""; [ $m = 5 ] && MUT="VR_MUTATIONS=5 VR_MUT_AFTER_SPATIAL=1 VR_MUT_STRAT=light,depth,select,flight,direction,distance,rebounce"
    # shellcheck disable=SC2086
    TEAPOT_FRAME=150 FIVE_SCRIPT=cam_pose.py bash outputs/decorr/five_capture.sh $C/cam7_${name}_m$m VR_SCENE=lanternglow VR_MAX_BOUNCES=2 VR_DISPLAY=960x540 VR_WARM=300 VR_CAM_DEG=0.1 VR_DENOISER=$den $LOOKENV $MUT
  done
done
grep -c "(Error)" $C/cam7_*/run.log; ls $C/cam7_*/c.*.exr | wc -l
```
Expected: `0` errors in each, 6 EXRs.

- [ ] **Step 3: Write `motion_score.py` and score**

`outputs/decorr/motion_score.py`:
```python
"""The moving-camera test with all seven moves (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, E7):
cam_pose.py's captures of the construct, scored against the still shot's reference in its medium, plain vs 5
mutations per output (OptiX, RR, raw).

    python motion_score.py [<run root>] [--out five_denoisers/motion.json]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import five_scores  # noqa: E402
import medium_metrics as mm  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews", "glowcam")
LABEL = "lanternglow_b2"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=ROOT)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "five_denoisers", "motion.json"))
    a = ap.parse_args(argv)
    ref = art.reference(a.root, LABEL)
    mask = np.load(os.path.join(a.root, LABEL, "noreuse", "c.medium.npy"))
    out = {}
    for name in ("optix", "rr", "raw"):
        vals = {}
        for m in (0, 5):
            run = os.path.join(a.root, LABEL, "cam7_%s_m%d" % (name, m))
            img = five_scores.frames(run, five_scores.schedule(run)["channel"])[0]
            vals["m%d" % m] = mm.relmse(img, ref, mask)
            vals["brightness_m%d" % m] = mm.brightness(img, ref, mask)
        vals["change"] = vals["m5"] / vals["m0"] - 1
        out[name] = vals
        print("%-5s relMSE %.5f -> %.5f (%+.0f%%), brightness %.3f / %.3f"
              % (name, vals["m0"], vals["m5"], 100 * vals["change"], vals["brightness_m0"], vals["brightness_m5"]))
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    main()
```
Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python motion_score.py`
Expected: three lines and `five_denoisers/motion.json`. The motion sentence in §7 quotes these three changes whatever they are.

- [ ] **Step 4: Commit**

```bash
cd /c/research/Denoising-VolumetricReSTIR
git add Source/RenderPasses/VolumetricReSTIR/Scripts/cam_pose.py
git add -f outputs/decorr/motion_score.py
git commit -m "cam_pose.py into the repository and motion_score.py: the construct under a moving camera at the shipped cap with all seven moves -- <paste motion_score's three lines>"
```

---

### Task 10: the recorded tables, and the table generator

**Files:**
- Create: `outputs/decorr/paper_record.json`
- Create: `outputs/decorr/paper_tables.py`
- Test: `outputs/decorr/test_paper_tables.py`
- Writes (not committed): `DenosingVolumetricReSTIR/tables/*.tex`

**Interfaces:**
- Consumes: the two result specs; `results.json` (Task 7) for the five-denoiser tables.
- Produces: `paper_tables.spec_section(path, sid) -> str`, `paper_tables.latex(cell: str) -> str`, `paper_tables.tabular(header, rows, spec) -> str`, `paper_tables.five_rows(results, hist) -> list[list[str]]`, `paper_tables.write_all(record, results, out_dir)` writing `phase_a.tex mcap.tex reuse_denoisers.tex bias.tex speed.tex equal_time.tex counts.tex acceptance.tex five_c200.tex five_ship.tex five_values.tex`.

- [ ] **Step 1: Write the record** (every cell copied verbatim from the cited section; the test checks it)

`outputs/decorr/paper_record.json`:
```json
{
 "phase_a": {"source": "2026-09-27-restir-mcmc-decorrelation-design.md#V1",
  "header": ["Scene", "frame", "medium", "relMSE, reuse / none"],
  "rows": [["emerald (fog + surfaces)", "0.0196", "0.0223", "0.00046 / 0.0177"],
           ["bistro (smoke + surfaces)", "0.0142", "0.0251", "0.00087 / 0.0228"],
           ["plume g = −0.9", "0.0141", "0.0164", "0.097 / 2.26"],
           ["bunny g = 0.8", "0.0075", "0.0082", "0.034 / 0.458"],
           ["bunny", "0.0065", "0.0074", "0.035 / 0.477"],
           ["plume", "0.0063", "0.0072", "0.031 / 0.436"],
           ["wdas 1×", "0.0053", "0.0059", "0.053 / 0.476"],
           ["explosion", "0.0053", "0.0035", "0.071 / 0.125"]]},
 "mcap": {"source": "2026-09-27-restir-mcmc-decorrelation-design.md#V3",
  "header": ["Scene", "cap 1", "shipped", "10", "20", "50", "200"],
  "rows": [["plume g = −0.9 (shipped cap 4)", "0.009", "0.016", "0.021", "0.025", "0.044", "0.120"],
           ["bistro whole (cap 10)", "0.0071", "0.0142", "—", "0.0170", "0.0275", "0.078"],
           ["emerald fog (cap 10)", "0.010", "0.022", "—", "0.023", "0.026", "0.056"]]},
 "reuse_denoisers": {"source": "2026-09-27-restir-mcmc-decorrelation-design.md#V7",
  "header": ["Denoiser", "Δρ̄(8), plume g = −0.9", "covariance at 8 px, bistro"],
  "rows": [["OptiX", "+0.024", "×1.1"], ["OIDN", "−0.053", "×0.7"], ["NRD RELAX-SH", "+0.194", "×16"],
           ["NRD REBLUR-SH", "+0.124", "×60"], ["DLSS RR", "+0.024", "×2.4"]]},
 "bias": {"source": "2026-10-03-two-bounce-mutations-design.md#V-C6",
  "header": ["Setup", "1 bounce", "z", "2 bounces", "z"],
  "rows": [["explosiondusk", "-0.06% +- 0.44%", "-0.15", "+0.33% +- 0.60%", "+0.55"],
           ["bunnycathedral_d0.3", "-0.10% +- 0.61%", "-0.17", "+0.04% +- 0.45%", "+0.08"],
           ["bunnyback_g0.8", "-0.72% +- 1.25%", "-0.57", "-0.66% +- 1.97%", "-0.33"],
           ["bunnysoftbox", "-0.02% +- 0.02%", "-1.35", "+0.04% +- 0.03%", "+1.56"],
           ["wdassunset_g0.85", "-0.19% +- 0.11%", "-1.80", "-0.09% +- 0.13%", "-0.69"]],
  "notes": ["8.77", "p = 0.55", "1.80"]},
 "speed": {"source": "2026-10-03-two-bounce-mutations-design.md#V-C4",
  "header": ["Scene, 1 / 2 bounces", "before", "Stage 1", "Stage 2 (coherent)"],
  "rows": [["explosion", "48.6 / 76.4 (+95 / +111%)", "43.9 / 55.2", "18.5 / 18.7 (+36 / +29%)"],
           ["cathedral", "59.9 / 184 (+87 / +33%)", "48.9 / 146", "18.3 / 55.0 (+25 / +10%)"],
           ["backlit rim", "72.7 / 177 (+120 / +166%)", "65.5 / 135", "20.4 / 43.1 (+34 / +40%)"],
           ["panel lights", "112 / 178 (+146 / +134%)", "96.0 / 145", "41.4 / 55.5 (+52 / +41%)"],
           ["sunset cloud", "118 / 170 (+125 / +133%)", "109 / 140", "48.1 / 54.9 (+51 / +37%)"]]},
 "equal_time": {"source": "2026-10-03-two-bounce-mutations-design.md#V-C3",
  "header": ["Scene, 1 / 2 bounces", "plain", "+ 5 mutations", "plain, equal time"],
  "rows": [["explosion", "0.0418 / 0.0612", "−76 / −76%", "−16 / +4% (21 / 32 candidates)"],
           ["cathedral", "0.0141 / 0.0165", "−81 / −82%", "−21 / +4% (19 / 13)"],
           ["backlit rim", "0.0668 / 0.0870", "−75 / −64%", "−6 / +4% (61 / 74)"],
           ["panel lights", "0.0472 / 0.0546", "−81 / −81%", "+1 / −10% (35 / 28)"],
           ["sunset cloud", "0.0503 / 0.0639", "−50 / −62%", "+16 / +6% (35 / 29)"]]},
 "counts": {"source": "2026-10-03-two-bounce-mutations-design.md#V-C7",
  "header": ["Scene", "no reuse", "0", "1", "3", "10", "one vs ten"],
  "rows": [["large close panels, 2 bounces", "0.023", "0.127", "0.062", "0.048", "0.034", "+82%"],
           ["hidden backlight, 2 bounces", "0.079", "0.196", "0.094", "0.084", "0.071", "+32%"],
           ["192 coloured lights, dense (fixed reference)", "0.331", "0.216", "0.071", "0.055", "0.050", "+41%"],
           ["hidden backlight", "0.027", "0.101", "0.040", "0.041", "0.031", "+28%"],
           ["thunderstorm", "0.104", "0.108", "0.037", "0.030", "0.025", "+48%"]]},
 "acceptance": {"source": "2026-10-03-two-bounce-mutations-design.md#V-C1",
  "header": ["Scene", "direction", "distance", "rebounce"],
  "rows": [["explosion", "0.40", "0.41", "0.13"], ["cathedral", "0.81", "0.66", "0.08"],
           ["backlit rim", "0.70", "0.56", "0.03"], ["panel lights", "0.81", "0.55", "0.12"],
           ["sunset", "0.93", "0.50", "0.24"]]}
}
```

- [ ] **Step 2: Write the failing tests**

`outputs/decorr/test_paper_tables.py`:
```python
"""paper_tables.py: the recorded cells match their spec sections; the generated LaTeX.

    cd outputs/decorr && python -m unittest test_paper_tables -v
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paper_tables as pt

SPECS = os.path.join(HERE, "..", "..", "docs", "superpowers", "specs")


class TestRecord(unittest.TestCase):
    def test_every_recorded_cell_is_in_its_section(self):
        with open(os.path.join(HERE, "paper_record.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        for key, table in record.items():
            spec, sid = table["source"].split("#")
            text = pt.spec_section(os.path.join(SPECS, spec), sid)
            for row in table["rows"]:
                for cell in row:
                    if cell != "—":
                        self.assertIn(cell, text, "%s: %r not in %s" % (key, cell, sid))
            for note in table.get("notes", []):
                self.assertIn(note, text, "%s: %r not in %s" % (key, note, sid))

    def test_a_section_ends_at_the_next_heading(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("### V-C1 — a\nkeep 1\n### V-C1b — b\ndrop 2\n")
            self.assertEqual(pt.spec_section(p, "V-C1").strip(), "### V-C1 — a\nkeep 1")
            with self.assertRaises(KeyError):
                pt.spec_section(p, "V-C9")


class TestLatex(unittest.TestCase):
    def test_signs_percent_and_symbols(self):
        self.assertEqual(pt.latex("−0.56%"), "$-$0.56\\%")
        self.assertEqual(pt.latex("×60"), "$\\times$60")
        self.assertEqual(pt.latex("Δρ̄(8)"), "$\\Delta\\bar{\\rho}$(8)")
        self.assertEqual(pt.latex("bunnyback_g0.8"), "bunnyback\\_g0.8")
        self.assertEqual(pt.latex("-0.06% +- 0.44%"), "$-$0.06\\% $\\pm$ 0.44\\%")

    def test_five_rows(self):
        dens = ("optix", "oidn", "relax", "reblur", "rr", "raw")
        res = {"bunnyspot": {"ref_own_relmse": 0.0012, "histories": {"c200": {
            "m0": {d: {"mean": 0.0336} for d in dens}, "m5": {d: {"mean": 0.0060} for d in dens}}}}}
        rows = pt.five_rows(res, "c200")
        self.assertEqual(rows[0][0], "Spotlight beam")
        self.assertEqual(rows[0][1:7], ["$-$82\\%"] * 6)
        self.assertEqual(rows[0][7], "0.0012")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_paper_tables -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'paper_tables'`.

- [ ] **Step 4: Write `paper_tables.py`**

`outputs/decorr/paper_tables.py`:
```python
"""The paper's tables (docs/superpowers/specs/2026-10-20-mutation-paper-design.md): the recorded ones from
paper_record.json (each cell copied from its spec section; test_paper_tables.py checks every cell is there) and the
five-denoiser ones from five_denoisers/results.json, as LaTeX tabulars (booktabs) for \\input.

    python paper_tables.py <paper dir>/tables [--results five_denoisers/results.json]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SETUP_NAMES = {
    "bunnycathedral_d0.3": "Cathedral god rays", "bunnyspot": "Spotlight beam", "bunnysoftbox": "Warm and cool panels",
    "bunnyinside": "Lamp inside the cloud", "bunnyback_g0.8": "Backlit rim", "bunnystripes": "Light through slats",
    "explosion": "Self-emitting explosion", "bunnylanterns": "48 coloured lanterns", "wdassunset_g0.85": "Cloud at sunset",
    "plumeback_g0.9": "Backlit smoke", "plumeconcert_g0.6": "Concert beams", "emeraldnight_d3": "Night street in fog",
    "explosiondusk_b2": "Explosion (paper setup), 2b", "bunnycathedral_d0.3_b2": "Cathedral god rays, 2b",
    "bunnyback_g0.8_b2": "Backlit rim, 2b", "bunnysoftbox_b2": "Warm and cool panels, 2b",
    "wdassunset_g0.85_b2": "Cloud at sunset, 2b", "bunnyswarm_d3": "192 coloured lights", "wdasstorm_g0.5": "Thunderstorm"}
COLUMNS = ("optix", "oidn", "relax", "reblur", "rr", "raw")


def spec_section(path, sid):
    """The text of section `sid` ("### <sid> ..." up to the next "### ")."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("### %s " % sid)), None)
    if start is None:
        raise KeyError(sid)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")), len(lines))
    return "\n".join(lines[start:end])


def latex(cell):
    s = cell.replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")
    s = s.replace("+-", "$\\pm$").replace("%", "\\%")
    s = s.replace("Δρ̄", "$\\Delta\\bar{\\rho}$").replace("ρ̄", "$\\bar{\\rho}$").replace("×", "$\\times$")
    s = re.sub(r"(?<![\w$])[−-](?=\d)", "$-$", s)
    return s.replace("−", "$-$").replace("—", "---")


def tabular(header, rows, spec):
    out = ["\\begin{tabular}{%s}" % spec, "\\toprule", " & ".join(latex(h) for h in header) + " \\\\", "\\midrule"]
    out += [" & ".join(latex(c) for c in row) + " \\\\" for row in rows]
    return "\n".join(out + ["\\bottomrule", "\\end{tabular}", ""])


def change(cfgs, d):
    return "%+.0f%%" % (100 * (cfgs["m5"][d]["mean"] / cfgs["m0"][d]["mean"] - 1)) if d in cfgs["m0"] and d in cfgs["m5"] else "—"


def five_rows(results, hist):
    rows = []
    for label, name in SETUP_NAMES.items():
        if label not in results or hist not in results[label]["histories"]:
            continue
        cfgs = results[label]["histories"][hist]
        rows.append([name] + [latex(change(cfgs, d)) for d in COLUMNS] + ["%.4f" % results[label]["ref_own_relmse"]])
    return rows


def five_table(results, hist):
    head = ["Setup", "OptiX", "OIDN", "RELAX", "REBLUR", "DLSS RR", "raw", "ref."]
    body = ["\\begin{tabular}{lrrrrrrr}", "\\toprule", " & ".join(head) + " \\\\", "\\midrule"]
    body += [" & ".join(r) + " \\\\" for r in five_rows(results, hist)]
    return "\n".join(body + ["\\bottomrule", "\\end{tabular}", ""])


def five_values(results):
    head = ["Setup", "history"] + ["OptiX", "OIDN", "RELAX", "REBLUR", "DLSS RR", "raw"]
    body = ["\\begin{tabular}{llrrrrrr}", "\\toprule", " & ".join(head) + " \\\\", "\\midrule"]
    for label, name in SETUP_NAMES.items():
        for hist in ("c200", "ship"):
            cfgs = results.get(label, {}).get("histories", {}).get(hist)
            if not cfgs:
                continue
            cells = ["%.4f$\\to$%.4f" % (cfgs["m0"][d]["mean"], cfgs["m5"][d]["mean"]) if d in cfgs["m0"] and d in cfgs["m5"]
                     else "---" for d in COLUMNS]
            body.append(" & ".join([name, "200" if hist == "c200" else "shipped"] + cells) + " \\\\")
    return "\n".join(body + ["\\bottomrule", "\\end{tabular}", ""])


SPECS = {"phase_a": "lrrr", "mcap": "lrrrrrr", "reuse_denoisers": "lrr", "bias": "lrrrr", "speed": "lrrr",
         "equal_time": "lrrr", "counts": "lrrrrrr", "acceptance": "lrrr"}


def write_all(record, results, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for key, table in record.items():
        with open(os.path.join(out_dir, key + ".tex"), "w", encoding="utf-8") as fh:
            fh.write(tabular(table["header"], table["rows"], SPECS[key]))
    if results:
        for hist in ("c200", "ship"):
            with open(os.path.join(out_dir, "five_%s.tex" % hist), "w", encoding="utf-8") as fh:
                fh.write(five_table(results, hist))
        with open(os.path.join(out_dir, "five_values.tex"), "w", encoding="utf-8") as fh:
            fh.write(five_values(results))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--results", default=os.path.join(HERE, "five_denoisers", "results.json"))
    a = ap.parse_args(argv)
    with open(os.path.join(HERE, "paper_record.json"), encoding="utf-8") as fh:
        record = json.load(fh)
    results = None
    if os.path.exists(a.results):
        with open(a.results) as fh:
            results = json.load(fh)
    write_all(record, results, a.out_dir)
    print("tables written to", a.out_dir, "(five-denoiser tables %s)" % ("included" if results else "not yet: no results"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `python -m unittest test_paper_tables -v 2>&1 | tail -n 3`
Expected: `Ran 4 tests ... OK`. A failing `test_every_recorded_cell_is_in_its_section` names the cell: fix the record against the spec, never the other way round.

- [ ] **Step 6: Generate the recorded tables, commit**

```bash
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python paper_tables.py ../../DenosingVolumetricReSTIR/tables
cd /c/research/Denoising-VolumetricReSTIR
git add -f outputs/decorr/paper_record.json outputs/decorr/paper_tables.py outputs/decorr/test_paper_tables.py
git commit -m "paper_record.json and paper_tables.py: the paper's recorded tables, each cell checked against its spec section, and the five-denoiser tables from results.json, as LaTeX"
```
Expected: eight `.tex` tables now; the three `five_*.tex` once `results.json` exists (re-run then).

---

### Task 11: the bibliography, each entry checked

**Files:**
- Modify: `DenosingVolumetricReSTIR/references.bib` (not committed)
- Create: `DenosingVolumetricReSTIR/citations_checked.md` (not committed)
- Create: `outputs/decorr/bib_check.py`
- Test: `outputs/decorr/test_bib_check.py`

**Interfaces:**
- Produces: `bib_check.check(tex_path, bib_path, checked_path) -> list[str]` (problems; empty = pass): every `\cite*{}` key in the bibliography, every entry cited, every entry listed in `citations_checked.md`.

- [ ] **Step 1: Write the failing test**

`outputs/decorr/test_bib_check.py`:
```python
"""bib_check.py on small files.

    cd outputs/decorr && python -m unittest test_bib_check -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bib_check


class TestBibCheck(unittest.TestCase):
    def files(self, tex, bib, checked):
        d = tempfile.mkdtemp()
        paths = []
        for name, text in (("p.tex", tex), ("r.bib", bib), ("c.md", checked)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
            paths.append(os.path.join(d, name))
        return paths

    def test_clean(self):
        p = self.files("see \\citet{Lin21} and \\cite{Bitterli20, Sawhney24}", "@article{Lin21,\n}\n@article{Bitterli20,\n}\n"
                       "@article{Sawhney24,\n}\n", "| Lin21 | Papers/x.pdf |\n| Bitterli20 | doi |\n| Sawhney24 | Papers/y.pdf |\n")
        self.assertEqual(bib_check.check(*p), [])

    def test_undefined_unused_and_unchecked(self):
        p = self.files("\\cite{Lin21,Missing}", "@article{Lin21,\n}\n@misc{Unused,\n}\n", "| Unused | doi |\n")
        problems = bib_check.check(*p)
        self.assertIn("cited but not in the bibliography: Missing", problems)
        self.assertIn("in the bibliography but never cited: Unused", problems)
        self.assertIn("not in citations_checked.md: Lin21", problems)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_bib_check -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'bib_check'`.

- [ ] **Step 3: Write `bib_check.py`**

`outputs/decorr/bib_check.py`:
```python
"""The paper's bibliography against its text (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, criterion 5):
every cited key is in references.bib, every entry is cited, and every entry is in citations_checked.md (how it was
checked). Prints the problems; exit 1 if any.

    python bib_check.py <paper.tex> <references.bib> <citations_checked.md>
"""
import re
import sys


def check(tex_path, bib_path, checked_path):
    tex = open(tex_path, encoding="utf-8").read()
    cited = {k.strip() for group in re.findall(r"\\cite[a-z]*\*?(?:\[[^\]]*\])?\{([^}]*)\}", tex) for k in group.split(",")}
    bib = set(re.findall(r"@\w+\{([^,\s]+),", open(bib_path, encoding="utf-8").read()))
    checked = set(re.findall(r"^\|\s*([^|\s]+)\s*\|", open(checked_path, encoding="utf-8").read(), flags=re.M))
    problems = ["cited but not in the bibliography: " + k for k in sorted(cited - bib)]
    problems += ["in the bibliography but never cited: " + k for k in sorted(bib - cited)]
    problems += ["not in citations_checked.md: " + k for k in sorted(bib - checked)]
    return problems


if __name__ == "__main__":
    found = check(*sys.argv[1:4])
    print("\n".join(found) or "bibliography OK")
    sys.exit(1 if found else 0)
```

- [ ] **Step 4: Run it to see it pass**

Run: `python -m unittest test_bib_check -v 2>&1 | tail -n 3`
Expected: `Ran 2 tests ... OK`.

- [ ] **Step 5: Check every citation and write the bibliography**

For each entry below, confirm title, authors, venue, year and DOI or URL: the PDFs in `Papers/` by reading their first page (Read tool, `pages: "1"`), the others on the publisher's page (load WebSearch/WebFetch with ToolSearch first). Write the entry into `references.bib` under exactly the key given (Tasks 12–13 cite these keys), and a line into `citations_checked.md` (`| Key | how checked: Papers/<file> p.1, or the URL | date |`).

| Key | Work | Checked against | Cited in |
|---|---|---|---|
| `Bitterli20` | Bitterli et al. 2020, ReSTIR | publisher | §2 |
| `Lin21` | Lin et al. 2021, Volumetric ReSTIR | `Papers/Fast-Volume-Rendering-with-Spatiotemporal-Reservoir-Resampling.pdf` | §1, §2, §3 |
| `Sawhney24` | Sawhney et al. 2024, MCMC mutations for ReSTIR | `Papers/Decorrelating-ReSTIR Samplers-via-MCMC-Mutations.pdf` | §1, §2, §3, §4 |
| `Sawhney24Supp` | its supplement | `Papers/ReSTIRMCMC-supplemental.pdf` | §2 (the covariance analysis) |
| `Talbot05` | Talbot et al. 2005, importance resampling | publisher | §2 |
| `Hastings70` | Hastings 1970, Metropolis–Hastings | publisher (Biometrika) | §2 |
| `Pauly00` | Pauly et al. 2000, MLT in participating media | `Papers/Metropolis-Light-Transport-for-Participating-Media.pdf` | §2, §4 |
| `Kelemen02` | Kelemen et al. 2002, mutation strategy | publisher | §2, §4 |
| `Optix17` | Chaitanya et al. 2017 (the OptiX AI denoiser), re-keyed from the old `@online` entry | publisher | §2 |
| `OIDN` | Intel Open Image Denoise | the project page | §2 |
| `NRD` | NVIDIA Real-Time Denoisers | the SDK page | §2 |
| `Schied17` | Schied et al. 2017, SVGF (RELAX's basis) | publisher | §2 |
| `Zhdan21` | Zhdan 2021, ReBLUR (Ray Tracing Gems II) | publisher | §2 |
| `DLSSRR` | NVIDIA DLSS Ray Reconstruction | NVIDIA's page | §2, §6.1 |
| `Zhou25` | Zhou 2025, thesis (decoupled history) | `Papers/Zhou_Weijie.pdf` | §2, §7 |
| `RGBReSTIR` | RGB ReSTIR, GRIVAPP 2026 | `Papers/RGB_ReSTIR_GRIVAPP2026_preprint.pdf` | §2 |
| `GhostReSTIR` | Ghost ReSTIR | `Papers/Ghost-ReSTIR-Volumetric-Resampling-with-Ghost-Vertices in.pdf` | §2 |
| `Falcor` | Falcor | the repository | §6.1 |
| `Hoetzlein16` | Hoetzlein 2016, GVDB | publisher | §6.1 |
| `Kutz17` | Kutz et al. 2017, decomposition tracking | publisher | §6.1 (the reference renderer) |
| `Novak14` | Novák et al. 2014, residual ratio tracking | publisher | §6.1 (the reference renderer) |

Lin et al. 2026 and Junkins et al. 2026 only if found, then cited in §2 and §7. Remove `Andersson20`, `Zhu23` and the template's `software.bib` from the build (the new paper does not cite them). An entry that cannot be checked is left out, and the sentence citing it rewritten without it.
Expected: `citations_checked.md` lists every key in `references.bib`.

- [ ] **Step 6: Commit the checker**

```bash
cd /c/research/Denoising-VolumetricReSTIR
git add -f outputs/decorr/bib_check.py outputs/decorr/test_bib_check.py
git commit -m "bib_check.py: the paper's citations against its bibliography and the record of how each entry was checked"
```

---

### Task 12: the paper, sections 1–5

**Files:**
- Modify: `DenosingVolumetricReSTIR/paper.tex` (rewritten; not committed)
- Create: `DenosingVolumetricReSTIR/figures/moves.tex` (TikZ; not committed)

**Interfaces:**
- Consumes: `tables/phase_a.tex mcap.tex reuse_denoisers.tex bias.tex speed.tex equal_time.tex acceptance.tex` (Task 10), `references.bib` (Task 11).
- Produces: `paper.tex` with `\label{sec:intro} sec:background sec:correlation sec:method sec:cost` and `\label{tab:phasea} tab:mcap tab:reusedenoisers tab:bias tab:speed tab:equaltime fig:moves`, for Task 13 to cite.

- [ ] **Step 1: The preamble and skeleton** (replace the whole of `paper.tex`)

```latex
\documentclass[sigconf, screen, nonacm]{acmart}
\citestyle{acmauthoryear}
\usepackage{subcaption}
\usepackage{booktabs}
\usepackage{tikz}
\usetikzlibrary{arrows.meta, shapes.geometric, positioning}
\AtBeginDocument{\providecommand\BibTeX{{Bib\TeX}}}

\begin{document}
\title{Decorrelating Volumetric ReSTIR with Metropolis--Hastings Mutations, Seen Through Five Denoisers}

\begin{abstract}
% written in Task 13, Step 1, from the results
\end{abstract}

\begin{CCSXML}
<ccs2012>
 <concept>
  <concept_id>10010147.10010371.10010352.10010379</concept_id>
  <concept_desc>Computing methodologies~Ray tracing</concept_desc>
  <concept_significance>500</concept_significance>
 </concept>
 <concept>
  <concept_id>10010147.10010371.10010352</concept_id>
  <concept_desc>Computing methodologies~Rendering</concept_desc>
  <concept_significance>300</concept_significance>
 </concept>
</ccs2012>
\end{CCSXML}
\ccsdesc[500]{Computing methodologies~Ray tracing}
\ccsdesc[300]{Computing methodologies~Rendering}
\keywords{Volumetric ReSTIR, Metropolis--Hastings, Markov chain Monte Carlo mutations, spatiotemporal reuse, correlation, denoising}

\maketitle
\section{Introduction}\label{sec:intro}
Volumetric ReSTIR \citep{Lin21}.  % replaced in Step 2; one citation keeps BibTeX's first run from failing
\section{Background}\label{sec:background}
\section{Where the correlation comes from}\label{sec:correlation}
\section{Volumetric mutations}\label{sec:method}
\section{Cost}\label{sec:cost}
\bibliographystyle{ACM-Reference-Format}
\bibliography{references}
\end{document}
```
Build (with `S` as in Global Constraints): `cd /c/research/Denoising-VolumetricReSTIR/DenosingVolumetricReSTIR && "$S/tools/tectonic/tectonic.exe" -X compile paper.tex > "$S/paperbuild/new.log" 2>&1; echo "exit $?"`
Expected: exit 0 (the empty abstract compiles; Tectonic writes `paper.pdf` beside the source — expected, untracked).

- [ ] **Step 2: §1 Introduction** (about 0.7 column). Paragraphs, in order:
  1. Volumetric ReSTIR \citep{Lin21} reuses candidates across pixels and frames and reaches low noise at one sample per pixel; the price is that neighbouring pixels share samples and frames carry them forward, so the error becomes correlated: blotches rather than noise. Lin et al. observe the correlation at small reuse radii and name decorrelating it for denoisers as future work (paraphrase; no quotation).
  2. A denoiser cannot tell a blotch from detail: what reaches each denoiser (V7): RELAX ×16 and REBLUR ×60 the covariance at 8 px on Bistro, OptiX ×1.1, OIDN ×0.7, RR ×2.4 — temporal denoisers keep reuse's structure longest.
  3. Sawhney et al. \citep{Sawhney24} decorrelate ReSTIR DI and PT with Metropolis--Hastings mutations of each pixel's sample; we bring them to volumes and ask what they change in what a viewer sees after a denoiser — five of them.
  4. Contributions (itemize, the spec's four).
  5. One paragraph of findings, with the headline numbers left for Task 13 Step 1 (it adds them from `results.json`): large at long histories, small at the shipped one, unbiased, and a clear limit.

- [ ] **Step 3: §2 Background** (about 0.8 column), subsections:
  - ReSTIR: resampled importance sampling \citep{Talbot05}, reservoirs and spatiotemporal reuse \citep{Bitterli20}; the contribution weight $W = \mathrm{runningSum}/(\hat p(y)\,M)$ and the M cap that bounds the history.
  - Volumetric ReSTIR \citep{Lin21}: a sample is a scatter distance along the camera ray and a light sample, reused by copying the distance and reconnecting to the light; the target $\hat p$ is evaluated by deterministic tracking on a coarse grid; at two bounces a sample adds a bounce $(\omega, d)$ to a scatter point $x_2$ (path tag 0) or an emitting point $x_2$ (tag 1).
  - MCMC mutations \citep{Sawhney24}: Metropolis--Hastings \citep{Hastings70} chains on each pixel's sample with target $\hat p$ and the weight update of their Eq. 16; their supplement's covariance analysis; Pauly et al.'s propagation and scattering perturbations \citep{Pauly00}; Kelemen et al.'s step magnitudes \citep{Kelemen02}.
  - The five denoisers and which keep history: OptiX's AI denoiser \citep{Optix17} (temporal here, fed motion vectors and volume-aware guides), OIDN \citep{OIDN} (single frame), NRD RELAX (SVGF-derived, \citealp{Schied17}) and REBLUR \citep{Zhdan21} in spherical-harmonics mode, denoising medium and surfaces separately \citep{NRD}, and DLSS Ray Reconstruction \citep{DLSSRR}.
  - Other remedies for reuse correlation: a decoupled history \citep{Zhou25}, colour clumping \citep{RGBReSTIR}, null-scattering resampling \citep{GhostReSTIR} (out of scope); the duplication-driven M cap and the error--correlation trade-off only if Task 11 verified their papers.

- [ ] **Step 4: §3 Where the correlation comes from** (about 1 column, Tables `phase_a`, `mcap`, `reuse_denoisers`). Content:
  - Setup: eight scenes at 1920×1080, 10 separately seeded chains × 10 captures, 95% CIs from a bootstrap over chains; $\bar\rho(r)$ the robust correlation (Sawhney et al.'s Eq. 21 normalised), $\Delta\bar\rho$ its excess over the same scene without reuse, measured in the medium (V9: the near-noiseless background dilutes the whole-frame number).
  - Reuse correlates neighbours on every scene: $\Delta\bar\rho(8)$ 0.0053–0.0196 over the frame (V1, Table~\ref{tab:phasea}); a 17×17 box average then has 5.7–7.9× the variance of independent pixels (V1); and still 1.7–38× less relMSE than no reuse (V1), except the explosion's blurred error (V1's open item, one sentence).
  - Spatial reuse creates it, temporal history multiplies it 2.7–3.9× (V2); the M cap is the strongest lever (V3, Table~\ref{tab:mcap}: plume g = −0.9 from 0.016 at cap 4 to 0.120 at cap 200); radius 10 is the lowest-error radius (V3); the shared R2 offsets shape but do not cause it (V4).
  - What reaches the denoisers (V7, Table~\ref{tab:reusedenoisers}).
  Tables via `\input{tables/phase_a}` etc. inside `table` environments with captions naming the source settings.

- [ ] **Step 5: §4 Volumetric mutations** (about 1.5 columns, Figure~\ref{fig:moves}, Tables `bias`, `acceptance`). Content:
  - 4.1 The weight update: Eq. 16 as $W(z) = \hat p(x_0)/\hat p(z)\,W(x_0)$, implemented as $\mathrm{runningSum} \leftarrow \mathrm{runningSum}\,\hat p(x_0)/p_y$, $p_y \leftarrow \hat p(z)$, $M$ kept; invalid reservoirs untouched; $p_y$ stays $\hat p$ at the pixel's own sample, as spatial reuse's Talbot MIS reads it (Phase B).
  - 4.2 The moves, each with its measure and acceptance (Phase B round 1, V-B4, V-B9, V-B10, two-bounce Step 1): light (emitter $u$ torus step; environment rotation, log-uniform 0.1°–5°, uniform azimuth), depth (propagation perturbation, log-uniform 0.5–16 march steps), free flight (independence move from the renderer's distance sampler, $q = \sigma_t T$), re-selection (independence move from the renderer's light samplers, position-aware for point lights with a 5% uniform share), and at two bounces direction (tag 0 rotation of $\omega$; tag 1 isotropic step of $x_2$ in volume), distance (tag 0) and rebounce ($\omega$ from the phase function, $d$ by free flight; $q$ divided by $d^2$ for tag 1). Rules: fixed, state-independent move probabilities; an inapplicable move is a self-transition; a proposal with $\hat p = 0$ is rejected, never redrawn; paths whose first vertex is a surface are not moved. Acceptance rates: V-B1 (plume env rotation 25%, depth 45–52%; bistro light 95%, depth 39%) and Table~\ref{tab:acceptance} (V-C1).
  - Figure~\ref{fig:moves}: `\input{figures/moves}` with this starting TikZ (adjust coordinates until nothing overlaps on the built page):
```latex
\begin{figure}[t]
\centering
\begin{tikzpicture}[font=\footnotesize, >={Stealth[length=1.8mm]}]
  \fill[black!8] (2.5,0.6) ellipse (2.2cm and 1.25cm);
  \node[black!55] at (4.1,1.65) {medium};
  \draw[thick] (0,0.15) -- (0.4,0.4) -- (0.4,-0.1) -- cycle;
  \node[below] at (0.2,-0.12) {camera};
  \coordinate (x1) at (1.9,0.3);
  \draw[->] (0.4,0.15) -- (x1);
  \fill (x1) circle (1.5pt) node[below=2pt] {$x_1$};
  \draw[<->, blue!70!black, thick] (1.45,0.55) -- (2.35,0.62);
  \node[blue!70!black, above] at (1.7,0.62) {depth, free flight};
  \node[draw, star, star points=5, fill=orange!70, minimum size=7pt, inner sep=0pt] (L) at (5.5,1.75) {};
  \node[right] at (L.east) {light};
  \coordinate (x2) at (3.3,1.05);
  \draw[->, thick, red!70!black] (x1) -- (x2) node[midway, below right=-1pt] {$\omega, d$};
  \fill (x2) circle (1.5pt) node[above=1pt] {$x_2$};
  \draw[dashed] (x1) -- (L);
  \draw[dashed] (x2) -- (L);
  \node[red!70!black, align=left, anchor=north west] at (2.2,-0.05) {direction, distance, rebounce\\(two bounces; tag 1: step of $x_2$)};
  \node[orange!60!black, align=left, anchor=west] at (4.15,0.95) {light: $u$ step, rotation,\\re-selection};
\end{tikzpicture}
\caption{What each move changes. One bounce: the scatter depth of $x_1$ along the camera ray and the light sample (dashed from $x_1$). Two bounces: also the bounce $(\omega, d)$ to $x_2$, whose light connection the light moves act on; an emitting $x_2$ (tag 1) is moved by a small step in volume.}
\Description{A schematic of a camera ray entering a cloud, a scatter point x1 on it, a bounce to a second point x2, and dashed connections to a light, each labelled with the mutations that move it.}
\label{fig:moves}
\end{figure}
```
  - 4.3 Placement after spatial reuse (V-B9: reaches what spatial reuse shares within the frame; on the 3-light bunny colour $\bar\rho(8)$ 0.0028 → 0.0002 with five re-selections after spatial reuse vs 0.0015 after temporal).
  - 4.4 Unbiasedness: V-C6's argument in five steps (ReSTIR's input guarantee; Eq. 16 needs only that the kernel leaves $\hat p$ invariant; every move does, by detailed balance in $\hat p$'s measure; the implementation is that kernel, including early rejection; downstream use), its stated assumptions, and the bias suite (Table~\ref{tab:bias}: ten setups, 64 seed-paired chains × 12 frames at M cap 200, largest |z| 1.80, χ² 8.77 on 10 degrees of freedom, p = 0.55).
  - 4.5 Two findings from building it (V-B9): counting rejection reasons on the GPU found an `&&` that does not short-circuit in this shader path (re-selection accepted 0 of 50M proposals), and an in-place swizzle in Falcor's environment `evalPdf` that biased re-selection by −0.44% in red until the move evaluated the density itself.

- [ ] **Step 6: §5 Cost** (about 0.6 column, Tables `speed`, `equal_time`). Content:
  - The pass draws a move kind per step; drawing it per pixel made a warp run every kind its pixels picked. Stage 1 shares one $\hat p$ evaluation per step (bit-identical); Stage 2 draws the kind once per step for the whole frame (the same chain in law): the pass 2.5–4.1× faster (V-C4, Table~\ref{tab:speed}); early rejection stops a shadow march once the proposal cannot be accepted: a further −3% to −29% (V-C5 A).
  - One step costs about 4–11 initial candidates (V-C3). At equal time at M cap 200, mutations cut the denoised error −50% to −82% where more candidates give −21% to +16% (V-C3, Table~\ref{tab:equaltime}); at Bistro's shipped cap more candidates win (V-B5).
  - Fewer mutations: three are within 2–12% of five's error, one is 18–43% worse (V-C5 C).

- [ ] **Step 7: Build and look at it**

```bash
S="C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
cd /c/research/Denoising-VolumetricReSTIR/DenosingVolumetricReSTIR && "$S/tools/tectonic/tectonic.exe" -X compile paper.tex > "$S/paperbuild/new.log" 2>&1; echo "exit $?"; grep -iE "undefined|error|overfull" "$S/paperbuild/new.log" | head
```
Expected: exit 0; no `undefined` reference or citation. Read the PDF's pages (Read tool) and check the diagram, the tables' widths at column width and the section flow.

---

### Task 13: the paper, sections 6–8, the abstract and the appendix

**Files:**
- Modify: `DenosingVolumetricReSTIR/paper.tex` (not committed)
- Copy into `DenosingVolumetricReSTIR/figures/`: `teaser_five.png five_strip.png history_chart.pdf gallery_mutations.png gallery_mutations_rr.png gallery_mutations_b2.png gallery_mutations_b2_rr.png swarm_counts_denoisers.png swarm_chat_maps.png` and the `variety_*.png` / `variety_rr_*.png` of the 17 gallery setups (from `outputs/decorr/figs`)

**Interfaces:**
- Consumes: `results.json`, `ref_change.json`, `motion.json`, `tables/five_c200.tex five_ship.tex five_values.tex counts.tex` (Tasks 7–10), the figures (Task 8).

- [ ] **Step 1: Read the results and write the abstract and the intro's findings paragraph.** From `results.json` compute, per denoiser at each history, the median and range of the cut (`1 - m5/m0`), and per setup plain ReSTIR at the shipped cap against M cap 200 with mutations; print them (a short Python snippet in the session) and put each number used into the ledger draft (Task 14). The abstract (150–200 words): the problem; the moves; unbiased (ten setups, p = 0.55); the five-denoiser result at M cap 200 (median and range across denoisers); the shipped history (its median and range, and how plain ReSTIR there compares with M cap 200 with mutations); the limit (the shared normalization; the decoupled history); the cost (+10% to +52% of the frame after a 2.5–4.1× faster pass). Every quantitative sentence must match criterion 2.

- [ ] **Step 2: The teaser** (after `\keywords`, before `\maketitle`):
```latex
\begin{teaserfigure}
  \includegraphics[width=\textwidth]{figures/teaser_five.png}
  \caption{<setup name from five_figures.py> at a 200-frame history, through five denoisers: plain Volumetric ReSTIR (left of each pair) and the same with five Metropolis--Hastings mutations per pixel (right), against the path-traced reference; in-medium relMSE under each crop.}
  \Description{Ten zoomed crops of the same region, two per denoiser (before and after mutations), and the reference.}
  \label{fig:teaser}
\end{teaserfigure}
```
(Replace `<setup name ...>` with the name printed by `five_figures.py`, from `paper_tables.SETUP_NAMES`.)

- [ ] **Step 3: §6 Results.**
  - 6.1 Setup: the GPU (RTX 5070 Laptop GPU, 8 GB) and CPU (read with `powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).Name"`); the Falcor 9 port \citep{Falcor} with GVDB volumes \citep{Hoetzlein16}; the reference renderer (decomposition tracking \citep{Kutz17} for free flights, ratio tracking \citep{Novak14} for shadow rays); 1920×1080 for 17 setups, 960×540 for two; the pass as shipped; both histories (the shipped cap 4, 10 on the night street); 2 seeded chains; the references (2048 × 16 spp, the explosion 4096; re-rendered by the fixed reference renderer, with `ref_change.json`'s finding in one sentence); the metric; each reference's own relMSE in the table; the denoiser versions (OptiX 9.1, OIDN 2.3.3, NRD 4.17, and the DLSS RR DLL's version from `powershell -NoProfile -Command "(Get-Item 'C:\research\Denoising-VolumetricReSTIR\build\windows-vs2022\bin\Release\nvngx_dlssd.dll').VersionInfo.FileVersion"`, preset E at native resolution); four denoisers share one graph, RR runs alone because its G-buffer jitters the camera (one sentence).
  - 6.2 M cap 200: `\input{tables/five_c200}` in a `table*` (caption: change in in-medium relMSE with five mutations, per denoiser; last column the reference's own relMSE), Figure `five_strip` (`figure*`), the per-denoiser medians and ranges from Step 1, which setups gain least and why (from the record: emissive lamps on the night street, V-B10), RR's brightness (its `brightness` values in `results.json`: report the range, and that its relMSE partly ranks brightness, V-C7).
  - 6.3 The shipped history: `\input{tables/five_ship}` (main text if the page budget allows, else the appendix), Figure `history_chart.pdf` (column width), and the comparison of plain ReSTIR at the shipped cap with M cap 200 + mutations from Step 1, stated as criterion 2 says.
  - 6.4 How many mutations: `\input{tables/counts}` and `figures/swarm_counts_denoisers.png` (V-C7: one mutation is 28–82% worse than ten after OptiX on the four count scenes; the storm keeps paying to ten).
  - 6.5 The galleries: `figures/gallery_mutations_b2.png` and `gallery_mutations_b2_rr.png` in the main text (the approved two-bounce figures, re-scored), the one-bounce galleries in the appendix; numbers that moved with the new references, from Task 8 Step 7.

- [ ] **Step 4: §7 Limits.**
  - A pixel's brightness is mostly its reservoir's normalization $\hat c = \mathrm{runningSum}/M$, which Eq. 16 keeps: 97–98% of the swarm's brightness-error blotch variance is in $\hat c$ (V-C7), with `figures/swarm_chat_maps.png`; spatial-only correlation is unchanged to four decimals by five mutations (V-B7).
  - A decoupled history removes more at a long history: the swarm 0.0273 vs 0.0499 with ten mutations, the close panels 0.0091 vs 0.0337 (V-C7); on the plume and Emerald Square 8–9× less correlation than shipped at lower error (V-B8); mutations add nothing on top of it after temporal reuse (V-B8).
  - The duplication-driven cap biases these volumes (V-B8: stationary blobs near the plume's flame).
  - DLSS RR darkens its input (V-C7: down to a third on the decoupled history's input) and its relMSE partly ranks brightness.
  - Paths whose first vertex is a surface are not moved (V-C2: the cathedral's walls keep their streaks).
  - Motion: with the camera turning 0.1° a frame at the shipped history, five mutations change the error by `motion.json`'s three values (OptiX, RR, raw) — the one test of motion; every other number here is a still pose.

- [ ] **Step 5: §8 Conclusion.** Mutations make a long history usable and are unbiased; at the shipped history their effect is small; where the artifact lives in the weights, decouple the history; measure in the medium and through the denoiser that will be used.

- [ ] **Step 6: The appendix** (after `\bibliography`, `\appendix`): A. the one-bounce galleries (`gallery_mutations.png`, `gallery_mutations_rr.png`); B. `\input{tables/five_values}` (before → after for every setup, denoiser and history); C. the shipped-cap table if not in §6.3; D. per-scene figures (`variety_<label>.png`, `variety_rr_<label>.png`), two per page, each captioned with its setup name.

- [ ] **Step 7: Build and look at every page**

```bash
S="C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python paper_tables.py ../../DenosingVolumetricReSTIR/tables
cd ../../DenosingVolumetricReSTIR && "$S/tools/tectonic/tectonic.exe" -X compile paper.tex > "$S/paperbuild/new.log" 2>&1; echo "exit $?"; grep -iE "undefined|error" "$S/paperbuild/new.log" | head
python -c "import re; print(len(re.findall(rb'/Type\s*/Page[^s]', open('paper.pdf','rb').read())), 'pages')"
```
Expected: exit 0, no `undefined`. Main text (up to the references) about 10 pages: if it runs over, move the shipped-cap table and the RR gallery to the appendix first. Read every page: no overfull table, every figure legible at its width, captions under their figures.

---

### Task 14: the numbers ledger, the final checks, the hand-off

**Files:**
- Create: `outputs/decorr/check_numbers.py`
- Test: `outputs/decorr/test_check_numbers.py`
- Create: `DenosingVolumetricReSTIR/numbers_ledger.md` (not committed)

**Interfaces:**
- Produces: `check_numbers.numbers(tex: str) -> list[str]`, `check_numbers.ledger(md: str) -> set[str]`, `check_numbers.missing(tex, md) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`outputs/decorr/test_check_numbers.py`:
```python
"""check_numbers.py: every number in the paper's text has a ledger entry.

    cd outputs/decorr && python -m unittest test_check_numbers -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_numbers as cn

TEX = r"""
\begin{figure}[t]\includegraphics[width=0.48\linewidth]{figures/a.png}\end{figure}
Reuse correlates neighbours: $\Delta\bar\rho(8)$ 0.0053--0.0196 \citep{Lin21} at M cap 200, a cut of $-$84\% and ×60.
% a comment with 0.999 is ignored
Section~\ref{sec:intro} and 5 mutations.
"""


class TestCheckNumbers(unittest.TestCase):
    def test_finds_the_texts_numbers_only(self):
        self.assertEqual(cn.numbers(TEX), ["0.0053", "0.0196", "200", "84%", "60"])

    def test_missing_against_the_ledger(self):
        md = "| number | where | source |\n|---|---|---|\n| 0.0053 | §3 | V1 |\n| 0.0196 | §3 | V1 |\n| 200 | §3 | E3 |\n| 84% | §6 | results |\n"
        self.assertEqual(cn.missing(TEX, md), ["60"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /c/research/Denoising-VolumetricReSTIR/outputs/decorr && python -m unittest test_check_numbers -v 2>&1 | tail -n 3`
Expected: `ModuleNotFoundError: No module named 'check_numbers'`.

- [ ] **Step 3: Write `check_numbers.py`**

`outputs/decorr/check_numbers.py`:
```python
"""Every number in the paper has a source (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, criterion 1):
the numbers in paper.tex (and the tables it inputs) against the numbers ledger's first column.

    python check_numbers.py <paper.tex> <numbers_ledger.md> [<table.tex> ...]

A number is a decimal (0.0151), a percentage (84%, written 84\% or $-$84\%), or an integer of two digits or more
(200, 1080). Ignored: comments, optional arguments and layout lengths, citations, labels, references, one-digit
integers, signs. Exit 1 listing every number missing from the ledger.
"""
import re
import sys

DROP = [r"(?<!\\)%.*", r"\\(?:cite[a-z]*|ref|label|eqref|includegraphics|input|begin|end|usepackage|usetikzlibrary)"
        r"\*?(?:\[[^\]]*\])?\{[^}]*\}", r"\[[^\]]*\]", r"[0-9.]+\\(?:linewidth|textwidth|columnwidth)", r"\$-\$|−"]


def numbers(tex):
    s = tex
    for pat in DROP:
        s = re.sub(pat, " ", s)
    s = s.replace("\\%", "%")
    out = []
    for m in re.finditer(r"(?<![\w.])(\d+\.\d+|\d+)(%?)", s):
        value, pct = m.groups()
        if pct or "." in value or len(value) >= 2:
            out.append(value + pct)
    return out


def ledger(md):
    return {line.split("|")[1].strip() for line in md.splitlines() if line.startswith("|") and line.count("|") >= 3}


def missing(tex, md):
    have = ledger(md)
    return [n for n in dict.fromkeys(numbers(tex)) if n not in have]


if __name__ == "__main__":
    tex = "\n".join(open(p, encoding="utf-8").read() for p in [sys.argv[1]] + sys.argv[3:])
    gone = missing(tex, open(sys.argv[2], encoding="utf-8").read())
    print("\n".join("no ledger entry: " + n for n in gone) or "every number has a ledger entry")
    sys.exit(1 if gone else 0)
```
(The `DROP` patterns run in order: comments first, then commands with arguments, then any remaining `[...]`, lengths, then signs — so `$-$84\%` becomes `84%` and `0.48\linewidth` disappears.)

- [ ] **Step 4: Run them to see them pass**

Run: `python -m unittest test_check_numbers -v 2>&1 | tail -n 3`
Expected: `Ran 2 tests ... OK`.

- [ ] **Step 5: Write the ledger and run every check**

`DenosingVolumetricReSTIR/numbers_ledger.md`: a table `| number | where in the paper | source |`, one row per distinct number, the source being a spec section (`2026-09-27 … V3`), a results key (`results.json bunnyspot/c200/m5/optix/mean`), `ref_change.json`, `motion.json`, or a setting (`spec E3`). Then:
```bash
cd /c/research/Denoising-VolumetricReSTIR
S="C:/Users/kaana/AppData/Local/Temp/claude/C--research-Denoising-VolumetricReSTIR/a147ce95-9ebe-4c07-baad-4002de1ef04b/scratchpad"
P=DenosingVolumetricReSTIR
python outputs/decorr/check_numbers.py $P/paper.tex $P/numbers_ledger.md $P/tables/*.tex
python outputs/decorr/bib_check.py $P/paper.tex $P/references.bib $P/citations_checked.md
cd $P && "$S/tools/tectonic/tectonic.exe" -X compile paper.tex > "$S/paperbuild/final.log" 2>&1; echo "exit $?"; grep -ciE "undefined" "$S/paperbuild/final.log"
cd /c/research/Denoising-VolumetricReSTIR && for t in outputs/decorr/test_*.py; do (cd outputs/decorr && python -m unittest "$(basename "$t" .py)" 2>&1 | tail -n 1); done; (cd Source/RenderPasses/VolumetricReSTIR/Scripts && python -m unittest discover -s tests 2>&1 | tail -n 1)
```
Expected: `every number has a ledger entry`, `bibliography OK`, exit 0 with `0` undefined, every test module `OK`. For each ledger row, open its source and confirm the number (spot-check every row of the abstract and §6–§7 against `results.json`).

- [ ] **Step 6: Commit the checker; hand the paper over**

```bash
git add -f outputs/decorr/check_numbers.py outputs/decorr/test_check_numbers.py
git commit -m "check_numbers.py: every number in the paper against its ledger entry"
```
Send `DenosingVolumetricReSTIR/paper.pdf` to the user (SendUserFile, display render) with a two-line summary; update the memory file `decorrelation-study.md` with where the paper, results and ledger are. Then the final whole-branch review of the committed code (the executing skill's Final Review).
