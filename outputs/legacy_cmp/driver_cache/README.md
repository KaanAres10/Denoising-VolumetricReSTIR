# Reading the NVIDIA driver's compiled shaders

Nsight Graphics 2026.2 shows DXIL (D3D12) or SPIR-V (Vulkan) only, never the machine code. The driver's
own shader caches hold it, and CUDA's `nvdisasm` (12.8+, `-b SM120` for Blackwell) disassembles it.
Needs Python's `zstandard`.

Caches (read only; the driver owns them):
* Vulkan: `%LOCALAPPDATA%\NVIDIA\GLCache\<app>\<hash>\*.bin` -- zstd frames, some holding CUDA-style ELF
  images (`EM_CUDA`, `.text.main_N`; registers per thread in bits 24-31 of the `.text` section's `sh_info`).
  `unpack.py <bin> <dir>` then `cutelf.py <dir> <out>` then `sass.py <out>` (registers, instruction count,
  raw `.text` for `nvdisasm -b SM120`).
* D3D12: `%LOCALAPPDATA%\NVIDIA\DXCache\*.nvph`, 256 MB files. In `82fda9192aad5f25.nvph` each compile is
  a zstd frame sequence: DXIL bitcode (`BC\xC0\xDE`), an `STR` record (the driver's 64-bit shader hash at
  byte 16, the same hash Nsight shows), an `NVuc` container (the code: size at byte 164, offset at byte
  168, shared memory at byte 116), and, when a profiler was attached, an ELF copy.
  `scan_nvph.py <file> <dir>` lists the ELF copies; `hash_elfs.py <file> <hash>...` pairs hashes with them;
  `frames.py` snapshots every frame so two snapshots can be diffed around one run;
  `nvuc.py <file> <hex offset> <out.sass>` disassembles an `NVuc` entry.
* 9.0's SM 6.6 kernels go to `0002a9192aad5f25.nvph` in another container (`\x7fNC\xed`, payload not
  readable). Compiled for SM 6.5 (`VR_SHADER_MODEL=6_5`) they land in the readable format.

`sassloops.py <file.sass>` lists the loops (backward branches) that contain TEX, with their size and the
registers they touch.
