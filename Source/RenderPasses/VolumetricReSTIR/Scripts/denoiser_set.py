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
