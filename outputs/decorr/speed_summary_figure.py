"""The mutation speed-up's performance and Stage A's images on two pages (user, 2026-10-08: "show performance of each
and visual results for stage A and also fewer mutations"):

  figs/speed_summary.png -- per scene setup, the whole ReSTIR pass per frame (1080p, M cap 200, GPU median) as a
      stacked bar: the mutation pass on top, the rest of the frame below, for plain ReSTIR, 5 mutations at each stage
      (original, Stage 1, Stage 2, Stage 2 + A) and with A at 3 and 1 mutations. The runs come from different sessions
      (run_cost.sh, the speed A/Bs, run_fewer_mutations.sh), so the rest-of-frame part varies by a few percent.
  figs/stageA_identical.png -- per setup, one raw frame with early rejection off and on (run_speed_stageA.sh), zoomed
      where plain ReSTIR's denoised error is largest, their difference, and the mutation pass's time.

    python speed_summary_figure.py <root>        (root: outputs/decorr)
"""
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc
import paper_figure
import speed_ab_check as ab
import stages_figure as sf
import variety_figures as vf

P = "/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR"
SCENES = (("explosiondusk", "Explosion"), ("bunnycathedral_d0.3", "Cathedral"), ("bunnyback_g0.8", "Backlit rim"),
          ("bunnysoftbox", "Panel lights"), ("wdassunset_g0.85", "Sunset"))
# (name, colour of the mutation segment): the 5-mutation stages on the blue ordinal ramp (light = oldest), the fewer
# mutations on orange; plain ReSTIR has no mutation segment. Reference palette (dataviz skill): blue 250/350/450/600,
# orange; neutral rest-of-frame grey; text in ink tokens.
BARS = (("plain", None), ("5, original", "#86b6ef"), ("5, Stage 1", "#5598e7"), ("5, Stage 2", "#2a78d6"),
        ("5, Stage 2 + A", "#184f95"), ("3, Stage 2 + A", "#eb6834"), ("1, Stage 2 + A", "#f4a582"))
REST = "#c9c7bf"
INK, INK2 = "#0b0b0b", "#52514e"


def lanes(run_dir):
    with open(os.path.join(run_dir, "c.passes.json")) as fh:
        d = json.load(fh)
    return d[P + "/gpu_time"]["median"], d.get(P + "/Mutate Samples/gpu_time", {}).get("median", 0.0)


def mean_lanes(dirs):
    v = [lanes(d) for d in dirs if os.path.exists(os.path.join(d, "c.passes.json"))]
    return tuple(float(np.mean(x)) for x in zip(*v))


def timings(root, label):
    """[(total ms, mutation ms)] in BARS order."""
    s = lambda name, v: [os.path.join(root, "speed_ab", name, label, v + n) for n in "12"]
    f = lambda n: [os.path.join(root, "fewer_cost", label, "mut%d%s" % (n, v)) for v in "ab"]
    # Pairs from the session that measured them together: original / Stage 1 (stage1 A/B), Stage 2 / Stage 2 + A
    # (stageA's A/B: A off is Stage 2 bit for bit), 3 / 1 mutations (run_fewer_mutations.sh).
    return [lanes(os.path.join(root, "cost", label, "mut0")), mean_lanes(s("stage1", "A")), mean_lanes(s("stage1", "B")),
            mean_lanes(s("stageA", "A")), mean_lanes(s("stageA", "B")), mean_lanes(f(3)), mean_lanes(f(1))]


def summary(root, out):
    fig, axes = plt.subplots(2, len(SCENES), figsize=(4.2 * len(SCENES), 9.6), facecolor="#fcfcfb")
    fig.subplots_adjust(top=0.84, bottom=0.12, left=0.05, right=0.995, hspace=0.42, wspace=0.28)
    fig.suptitle("ReSTIR frame time with mutations, stage by stage (1080p, M cap 200; bar = whole ReSTIR pass, "
                 "coloured top = the mutation pass)", fontsize=15, color=INK, y=0.985)
    for row, suffix in enumerate(("", "_b2")):
        for col, (base, title) in enumerate(SCENES):
            ax = axes[row, col]
            ax.set_facecolor("#fcfcfb")
            t = timings(root, base + suffix)
            x = np.arange(len(BARS))
            # The other passes run the same code in every config (plain ReSTIR's frames are bit-identical across the
            # changes); their run-to-run spread, up to ~15% even within one A/B session, is GPU clock noise. One value
            # per setup -- their median over these runs -- so the bars differ only by the mutation pass.
            rest = float(np.median([tot - mut for tot, mut in t]))
            t = [(rest + mut, mut) for _, mut in t]
            ax.bar(x, [rest] * len(t), width=0.72, color=REST, edgecolor="#fcfcfb", linewidth=2)
            for i, ((tot, mut), (_, colour)) in enumerate(zip(t, BARS)):
                if colour:
                    ax.bar(i, mut, bottom=tot - mut, width=0.72, color=colour, edgecolor="#fcfcfb", linewidth=2)
                ax.text(i, tot, "%.0f" % tot, ha="center", va="bottom", fontsize=9, color=INK)
            ax.set_xticks(x)
            ax.set_xticklabels([b[0] for b in BARS], rotation=55, ha="right", fontsize=9, color=INK2)
            ax.set_title("%s, %s" % (title, "2 bounces" if suffix else "1 bounce"), fontsize=12, color=INK)
            ax.set_ylim(0, max(tot for tot, _ in t) * 1.14)
            ax.tick_params(axis="y", labelsize=9, colors=INK2)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            for s in ("left", "bottom"):
                ax.spines[s].set_color("#d6d4cc")
            ax.yaxis.grid(True, color="#ebeae5", linewidth=0.8)
            ax.set_axisbelow(True)
            if col == 0:
                ax.set_ylabel("ms per frame", fontsize=10, color=INK2)
    # Legend: identity never by colour alone (the x labels name every bar too).
    handles = [plt.Rectangle((0, 0), 1, 1, color=REST)] + [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in BARS[1:]]
    names = ["rest of the frame"] + ["mutation pass: %s" % n.replace("1, ", "1 mutation, ").replace(", ", " mutations, ", 1)
                                     if not n.startswith("1,") else "mutation pass: " + n.replace("1, ", "1 mutation, ")
                                     for n, _ in BARS[1:]]
    fig.legend(handles, names, loc="upper center", ncol=4, frameon=False, fontsize=10, bbox_to_anchor=(0.5, 0.945),
               labelcolor=INK2)
    fig.text(0.5, 0.01, "Mutation pass: original / Stage 1 and Stage 2 / Stage 2 + A from their speed A/Bs (A B B A, mean of "
             "2 runs), 3 / 1 mutations from run_fewer_mutations.sh. Grey: the setup's median time of the other passes over "
             "these runs (same code everywhere; their run-to-run spread, up to ~15%, is GPU clock noise).",
             ha="center", fontsize=9, color=INK2)
    fig.savefig(out, dpi=80, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def identical(root, out):
    labels = sf.LABELS
    fig, axes = plt.subplots(len(labels), 4, figsize=(15, 3.5 * len(labels)), facecolor="white",
                             gridspec_kw={"width_ratios": [1, 1, 1, 1.3]})
    fig.subplots_adjust(top=0.955, bottom=0.005, left=0.07, right=0.995, hspace=0.3, wspace=0.05)
    fig.suptitle("Stage A (early rejection) changes no pixel: raw ReSTIR output with it off and on, and their "
                 "difference\n(one frame of the A/B, 1080p, M cap 200, 5 mutations; zoomed where plain ReSTIR's "
                 "error is largest)", fontsize=14)
    for i, label in enumerate(labels):
        p = paper_figure.prepare(root, label, sf.DEN[0], sf.DEN[2], vf.EXPOSURE.get(label, 99.0), label in vf.PAPER_DISPLAY)
        (y, x), size = p.boxes[0], p.size
        d = os.path.join(root, "speed_ab", "stageA", label)
        fa, fb = ab._frames(os.path.join(d, "A1"), ".exr"), ab._frames(os.path.join(d, "B1"), ".exr")
        f = min(fa)
        off = mc.read_exr(fa[f])[..., :3][..., ::-1].astype(np.float64)[p.crop]
        on = mc.read_exr(fb[f])[..., :3][..., ::-1].astype(np.float64)[p.crop]
        same = ab.compare(os.path.join(d, "A1"), os.path.join(d, "B1"))
        t = ab.times(d)
        box = np.s_[y:y + size, x:x + size]
        for j, (img, title) in enumerate(((off, "early rejection off"), (on, "early rejection on"))):
            ax = axes[i, j]
            ax.imshow(p.show(img[box]), interpolation="nearest")
            ax.set_title(title + ("\nMutate Samples %.1f ms" % (t["A"]["mutate"] if j == 0 else t["B"]["mutate"])),
                         fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])
        diff = np.abs(on - off)[box].max(axis=-1)
        ax = axes[i, 2]
        ax.imshow(diff, cmap="magma", vmin=0, vmax=max(1e-6, float(diff.max())))
        ax.set_title("|on - off|, max %.3g" % float(diff.max()), fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        ax = axes[i, 3]
        ax.axis("off")
        # The whole pass is left out: its other passes swing by up to ~15% run to run (GPU clocks), more than A's
        # effect; speed_summary.png shows the frame with that noise taken out.
        ax.text(0.04, 0.5, "%d/%d frames bit-identical\nMutate Samples %.1f -> %.1f ms (%+.0f%%)"
                % (same["identical"], same["frames"], t["A"]["mutate"], t["B"]["mutate"],
                   100 * (t["B"]["mutate"] / t["A"]["mutate"] - 1)),
                va="center", fontsize=11, transform=ax.transAxes)
        axes[i, 0].set_ylabel(label.replace("_b2", "\n2 bounces").replace("_", " "), fontsize=11)
    fig.savefig(out, dpi=72)
    plt.close(fig)
    return out


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    print(summary(root, os.path.join(root, "figs", "speed_summary.png")))
    print(identical(root, os.path.join(root, "figs", "stageA_identical.png")))


if __name__ == "__main__":
    main(sys.argv)
