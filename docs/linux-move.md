# Moving this machine to Ubuntu (checklist, 2026-11-22)

The laptop turns to Ubuntu 24.04 LTS (HWE kernel, Xorg, pinned NVIDIA driver; see docs/linux.md for the build).
Everything below is what a fresh clone would NOT have. Copy it off the Windows disk before it is wiped.

## 1. The git history (local only)

Branch `decorrelation` holds about 200 commits that were never pushed (the GitHub repo is public, so they stay local
until the paper is out). A git bundle keeps every branch in one file:

    git bundle create C:\research\linux-move-backup\Denoising-VolumetricReSTIR.bundle --all
    git bundle verify C:\research\linux-move-backup\Denoising-VolumetricReSTIR.bundle

On Linux:

    git clone -b decorrelation Denoising-VolumetricReSTIR.bundle Denoising-VolumetricReSTIR
    git -C Denoising-VolumetricReSTIR config core.autocrlf input

Copying the whole folder (with its .git) works too; the bundle is the safety net. Last commits before the move:
the Linux port (0058165), the mutation-pass speed-up switches (241fd10), the night street's (x, t) strips and
temporal covariance (aef9794).

## 2. Untracked folders inside the repo (copy by hand)

| Folder | Size | What |
|---|---|---|
| `DenosingVolumetricReSTIR/` | 0.2 GB | the paper (LaTeX source, figures, ledger); never committed |
| `VolumetricReSTIRData/` | 60 GB | scenes, volumes, references |
| `outputs/decorr/` | 122 GB | every study run; only its scripts are in git. `five_denoisers/results.json`, `summary.tsv`, `spacetime*.json` and `figs/` are not |
| `outputs/pending_9p/` | 34 GB | `forkref/cap/v9sa_ref/` holds references the paper uses |
| rest of `outputs/` | ~127 GB | older studies (legacy_cmp, orbit_*, rb_v9p_* for mask_check) |
| `BifrostVDB/` | 8.5 GB | the lantern construct's Bifrost exports |
| `Dust_Devil/`, `Fire_01/`, `Gasoline_Explosion_01/`, `Midair_Explosion_01/`, `TornadoLoopingVDB/` | 5.5 GB | EmberGen / VDB sources |
| `RenderMan_Swatch_Blender/` | 0.9 GB | the swatch scene |
| `Papers/` | 0.7 GB | related-work PDFs |
| `external/nrd-4/`, `external/dlss-310*/`, `external/dlss-legacy-37/` | 0.3 GB | SDKs (git-ignored); the Linux builds need their Linux libraries, see docs/linux.md |

Outside the repo: `C:\research\falcor8-baseline-bin\` (2.5 GB, the Falcor 8 binary behind the locked tables; Windows
only), `C:\ProgramData\NVIDIA Corporation\OptiX SDK 9.1.0\include` (OptiX headers; on Linux install the SDK).
The sibling repos (KaanAres10.github.io, ReLightGS, eradiate) are clean and pushed.

## 3. Claude's memory and the viewer

- Claude Code keeps its notes for this project in `%USERPROFILE%\.claude\projects\C--research-Denoising-VolumetricReSTIR\memory\`
  (20 files). A copy is in `C:\research\linux-move-backup\claude-memory\`. On Linux the folder is keyed on the repo's
  new path with every `/` turned into `-`, e.g. `~/.claude/projects/-home-<user>-research-Denoising-VolumetricReSTIR/memory/`:
  copy the files there. Several notes name Windows paths; they say so where it matters.
- The night-street viewer (artifact "Night Street M-Cap Viewer") stays online. Its built page is copied to
  `C:\research\linux-move-backup\viewer\index.html`. Its build scripts (icat/ in a temporary scratchpad) were lost
  to a temp-folder cleanup before the move; the page and the published images are what remain.

## 4. First steps on Linux

1. docs/linux.md: drivers, Vulkan SDK, build as a normal user with a clean PATH.
2. Nothing has rendered on native Linux yet: render the plume and Bistro on `-d vulkan` and compare against the
   Windows Vulkan captures (numbers in docs/linux.md), not against D3D12.
3. The study scripts hold Windows paths (`C:/research/...`, `.exe`); they need a pass before any study runs.
4. Never point a Linux run at data a Windows install still uses: the loader writes `*_nodes.bin` next to the VBX.
5. Tables and the paper are D3D12 numbers; Vulkan is a new engine: score each against its own reference.
