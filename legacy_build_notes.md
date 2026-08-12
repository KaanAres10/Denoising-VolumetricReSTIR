# Reproducing the falcor4-legacy build (for denoiser comparison)

`legacy/` is a git worktree of `origin/falcor4-legacy` (Falcor 4.x). It is gitignored. It exists to
answer one question: were OIDN and OptiX more temporally stable before the v8 port? They were --
see the numbers at the bottom.

## Build

    msbuild legacy/Falcor.sln /p:Configuration=ReleaseD3D12 /p:Platform=x64 ^
        /p:WindowsTargetPlatformVersion=10.0.26100.0 /p:PlatformToolset=v143 /m

## Every deviation from a clean checkout, and why

Kept deliberately small and auditable: a heavily-patched "legacy" build is not evidence about the
legacy build.

| # | problem | fix | affects rendering? |
|---|---|---|---|
| 1 | targets Windows SDK 10.0.19041, only 10.0.26100 installed | property override | no |
| 2 | NuGet `boost.1.67.0.0` missing, no NuGet client on the machine | fetched the .nupkg from nuget.org, extracted to `legacy/packages/boost.1.67.0.0/` | no |
| 3 | toolset v142 (VS2019) not installed | build with v143 | no |
| 4 | `prebuild.bat` runs packman, whose S3 endpoint returns 403 | guarded: skipped when `.packman/Slang` exists. Only `github-slang` is required and it is already vendored | no (build script) |
| 5 | v143's `/permissive-` is stricter than v142's about `typename` on dependent types | added `typename` to `T::value_type` in template arguments: `ComputeParallelReduction.cpp` (5), `Gui.cpp` (7) | no -- compile-time disambiguator only |
| 6 | `.packman/{CUDA_13.0,OptiX_9.0.0,oidn}` never fetched | directory junctions to the installed CUDA 12.8, OptiX SDK 9.1.0/include, and `C:/oidn-2.3.3.x64.windows` | minor version gaps, see below |
| 7 | empty `.packman/nvapi` SHADOWED the vendored SDK at `Source/Externals/nvapi`, so deploycommon's `IF exist` passed and its three copies silently failed, leaving `Shaders/NVAPI` empty and crashing LightCollection | replaced the empty dir with a junction to the real SDK | no |

Runtime also needs the media path, which the script does not set:

    FALCOR_MEDIA_FOLDERS = <repo>/VolumetricReSTIRData;<repo>/legacy/Media

## Two things that looked like blockers and were not

* **"Unsupported shader-model '6_5'"** is COSMETIC. `kSupportedShaderModels` in `Program.cpp` is a
  hardcoded list used only to build a warning string, and the code says so itself ("This is not an
  error") and continues. Compilation goes through Slang/DXC regardless. I wrongly cited this as
  evidence that the shader toolchain was unusable.
* **NVAPI** is not needed as a C++ library here. `LightCollection::initIntegrator` only calls
  `findFileInShaderDirectories("NVAPI/nvHLSLExtns.h")` -- it wants the HLSL extension headers on the
  shader path, and those were already vendored in the tree.

## Fidelity caveats

CUDA 12.8 against an expected 13.0, OptiX 9.1.0 against 9.0.0, and MSVC v143 against v142. Minor
version gaps on the APIs these passes use, and nothing closer is available. Good enough to compare
temporal behaviour; NOT good enough to claim bit-exact reproduction of the original binaries.

## Result, bistro authored orbit, 300 frames at 1920x1080

Instability by spatial scale (x1e-3, measured at 720p so sigma matches every other number here):

| config | s=32 | s=128 | whole-frame | sharpness |
|---|---|---|---|---|
| LEGACY OptiX (no TAA) | **18.42** | **8.89** | 7.27 | **167.5** |
| v8 OptiX (mvec, +TAA) | 30.05 | 18.61 | 16.39 | 92.2 |
| v8 OptiX (colour only, +TAA) | 35.40 | 22.94 | 20.45 | 79.0 |

Legacy is ~40% more stable at s=32, ~52% at s=128 and 82% sharper -- while having NO TAA, where both
v8 rows have TAA helping them. So TAA is not the explanation and the gap is real.

**Confound to respect:** legacy's ToneMapper runs `autoExposure=True` with the Linear operator, and
per-frame auto-exposure actively counteracts global brightness change, which flatters the
whole-frame column specifically. The s=32 and s=128 columns are local measures and far less exposed
to it, and legacy wins those decisively, so the conclusion survives -- but do not quote the
whole-frame row as if it were clean.

**Still unattributed.** The pipelines differ in more than the denoiser: `OptixDenoiserRecent` vs v8's
`OptixDenoiser`, Linear+autoExposure vs fixed +8 EV, and possibly the estimator itself. The decisive
next test is to compare the UNDENOISED `accumulated_color` sequence from both builds: if legacy's raw
input is already cleaner, this is the estimator and not the denoiser at all -- which was the standing
hypothesis before this build existed.
