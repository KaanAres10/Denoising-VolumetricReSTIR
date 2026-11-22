# Building on Linux

Linux has one graphics backend, Vulkan, so a Linux render is a different engine from the D3D12 one the study's numbers come from:
re-render references and tables there, and never mix the two in one table. Everything below was built on Ubuntu 24.04.5 with GCC 13.3
in WSL, which can compile but not ray trace. The passes were run on Vulkan under Windows, on the real GPU. A full render on native
Linux is still to be done.

## System

Ubuntu 24.04 LTS with the HWE kernel, an NVIDIA RTX GPU, the proprietary driver (hold it with `apt-mark hold`, since OptiX's denoiser ships
inside the driver and an update can change images), and the Xorg session.

```bash
sudo apt install -y build-essential git curl unzip xorg-dev libgtk-3-dev
```

CUDA 12.8, the Windows build's version, from NVIDIA's own repository. Ubuntu's packaged 12.0 is too old for GCC 13.

```bash
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb -o /tmp/cuda-keyring.deb
```
```bash
sudo dpkg -i /tmp/cuda-keyring.deb
```
```bash
sudo apt update
```
```bash
sudo apt install -y --no-install-recommends cuda-nvcc-12-8 cuda-driver-dev-12-8 cuda-cccl-12-8 cuda-toolkit-12-8-config-common
```
```bash
export PATH=/usr/local/cuda-12.8/bin:$PATH
```

## SDKs

`external/gvdb` is in the repository. The rest is git-ignored and goes in by hand, before configuring.

**Dependencies.** `setup.sh` points `external/packman` at Linux packages, so run it only in a Linux checkout, never in one a Windows build uses.

```bash
./setup.sh
```

**OptiX 9.1.** Only the headers are used: NVIDIA's Linux SDK, or the `include` folder copied from the Windows SDK.

```bash
mkdir -p ~/sdk/optix-9.1.0 && cp -r <OptiX SDK 9.1.0>/include ~/sdk/optix-9.1.0/ && ln -sfn ~/sdk/optix-9.1.0 external/packman/optix
```

**OIDN 2.3.3.**

```bash
curl -fsSL https://github.com/RenderKit/oidn/releases/download/v2.3.3/oidn-2.3.3.x86_64.linux.tar.gz | tar xz -C external
```

**DLSS 310.9.1.**

```bash
git clone --depth 1 --branch v310.9.1 https://github.com/NVIDIA/DLSS external/dlss-310.9.1
```

**NRD 4.17.3.** Copy `external/nrd-4/Include` and `external/nrd-4/Shaders` from the Windows checkout, because the shaders carry local patches (see
`Source/RenderPasses/NRDPass/README.md`). Then build the library, which needs CMake 3.30 or newer: newer than Falcor's packman CMake and Ubuntu 24.04's.

```bash
sh build_scripts/build_nrd_linux.sh <path to cmake 3.30 or newer>
```

## Build

```bash
./tools/.packman/cmake/bin/cmake --preset linux-gcc
```
```bash
./tools/.packman/cmake/bin/cmake --build build/linux-gcc --config Release
```

Configure prints which SDKs it found (`FALCOR_HAS_CUDA`, `_OPTIX`, `_OIDN`, `_NRD`, `_DLSS`, `_GVDB`). A pass whose SDK is missing is left out of
the build with no error, and then fails only when a graph asks for it.

## Traps

- **Volume data lives on one system.** The loader writes `*_nodes.bin` caches next to each VBX, and later runs read them. Don't run Linux on data a
  Windows checkout also uses, or the two will feed each other's caches.
- **A black frame on Vulkan can mean a lost GPU.** Falcor does not report it, and every later readback is zero, including passes earlier in the
  graph. Under Windows the NVIDIA driver logs event 153; on Linux look for `Xid` in `dmesg`.
- **Slang warning 39001** (`explicit binding ... overlaps`) on any shader declaring `register()` bindings means exactly that kind of fault.

## Not ported yet

- The study scripts still name Windows paths and tools (`Mogwai.exe`, `windows-vs2022`, `cygpath`, `tasklist`, `REPO` in `vr_graph.py`).
- `gImportVDB`, which converts VDB to VBX, has no Linux build. Existing VBX files load fine.
- The older DLSS variants (`dlss_cnn`, `dlss_310_7`) are Windows-only: use the default.
- Some interactive scripts create `GBufferRaster` directly. `vr_graph.add_gbuffer` falls back to `GBufferRT` on Vulkan; they do not.
