# One-frame Nsight GPU Trace of the raw bistro config (the matched Look settings), for one engine.
# Usage: gputrace_v8_v9.ps1 v8|v9 <outdir>. Needs GPU performance counters; see STATE.md, "OPEN: Final Shading".
param([string]$eng, [string]$d)
$ng = "C:\Program Files\NVIDIA Corporation\Nsight Graphics 2026.2.0\host\windows-desktop-nomad-x64\ngfx.exe"
$exe = @{ v8 = "C:\research\falcor8-baseline-bin\Release\Mogwai.exe"; v9 = "C:\research\Denoising-VolumetricReSTIR\build\windows-vs2022\bin\Release\Mogwai.exe" }[$eng]
Get-ChildItem Env: | Where-Object { $_.Name -like "VR_*" -or $_.Name -like "NRD4_*" } | ForEach-Object { Set-Item -Path ("Env:" + $_.Name) -Value $null }
$env:VR_SCENE="bistro"; $env:VR_FRAMES="80"; $env:VR_WARM="20"; $env:VR_DISPLAY="1920x1080"
$env:VR_NRD_SPLIT="1"; $env:VR_NRD_SH="1"; $env:VR_NRD_TAA="1"; $env:VR_TAA_LDR="1"; $env:VR_NRD_EMISSION="1"; $env:VR_NRD_VOLMASK="1"; $env:VR_VOL_NORMAL="gradient"
$env:VR_DENOISER="none"; $env:VR_NRD_METHOD="RelaxDiffuseSh"; $env:VR_TIME="1"
New-Item -ItemType Directory -Force $d | Out-Null
$env:VR_OUT_DIR="$d\out"; $env:VR_TAG="t"
Set-Location C:\research\Denoising-VolumetricReSTIR
if (-not (Test-Path build\windows-vs2022\bin\Release\libprotoc.dll) -or -not (Test-Path build\windows-vs2022\bin\Release\z.dll)) {
  .\tools\.packman\cmake\bin\cmake.exe --build build\windows-vs2022 --config Release --target restore_runtime_dlls 2>&1 | Out-Null }
& $ng --activity "GPU Trace Profiler" --exe $exe --dir "C:\research\Denoising-VolumetricReSTIR" --args "--script C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts\capture_orbit.py" --start-after-frames 50 --limit-to-frames 1 --auto-export --output-dir $d 2>&1 | Select-Object -Last 12
Write-Output "--- files ---"
Get-ChildItem $d -Recurse -File | Where-Object { $_.FullName -notlike "*\out\*" } | Select-Object -First 30 | ForEach-Object { "{0,12:N0}  {1}" -f $_.Length, $_.FullName.Substring($d.Length) }
