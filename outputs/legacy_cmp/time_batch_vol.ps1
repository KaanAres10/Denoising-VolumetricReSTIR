# Falcor 4.x fork vs 9.0, wall clock, bistro orbit, 300 frames at 1080p: the raw estimator alone
# (time_batch.ps1's setup), volume-only (VR_NO_SURFACE=1 / VR_USE_SURFACE=0) and full scene.
# 3 runs per engine and scene type, order rotated each round, every run its own process. v9f is 9.0 with
# the opt-in VR_FP_MODE_VOLUME=fast (fast math, as the fork), volume-only.
param([int]$rounds = 3, [string]$outName = "wallvs")
$repo = "C:\research\Denoising-VolumetricReSTIR"
$out = "$repo\outputs\legacy_cmp\$outName"
New-Item -ItemType Directory -Force $out | Out-Null
$exe = @{ legacy = "$repo\legacy\Bin\x64\Release\Mogwai.exe"
          v9     = "$repo\build\windows-vs2022\bin\Release\Mogwai.exe"
          v9f    = "$repo\build\windows-vs2022\bin\Release\Mogwai.exe" }
$script = @{ legacy = "$repo\legacy\Scripts\_time_raw_legacy.py"
             v9     = "$repo\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py"
             v9f    = "$repo\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" }
$cwd = @{ legacy = "$repo\legacy"; v9 = $repo; v9f = $repo }

function Clear-Env { Get-ChildItem Env: | Where-Object { $_.Name -like "VR_*" -or $_.Name -like "NRD4_*" } | ForEach-Object { Set-Item -Path ("Env:" + $_.Name) -Value $null } }
function Run-One($eng, $vol, $tag) {
  Clear-Env
  if (-not (Test-Path "$repo\build\windows-vs2022\bin\Release\python310.dll") -or -not (Test-Path "$repo\build\windows-vs2022\bin\Release\z.dll")) {
    & "$repo\tools\.packman\cmake\bin\cmake.exe" --build "$repo\build\windows-vs2022" --config Release --target restore_runtime_dlls 2>&1 | Out-Null }
  $env:VR_FRAMES = "300"; $env:VR_ENGINE = $(if ($eng -eq "v9f") { "v9" } else { $eng })
  if ($eng -eq "v9f") { $env:VR_FP_MODE_VOLUME = "fast" }
  if ($vol) { if ($eng -eq "legacy") { $env:VR_NO_SURFACE = "1" } else { $env:VR_USE_SURFACE = "0" } }
  $res = "$out\$tag.txt"; $env:VR_RESULT = $res
  Set-Location $cwd[$eng]
  & $exe[$eng] --script $script[$eng] 2>&1 | Out-File "$out\$tag.log" -Encoding utf8
  $line = if (Test-Path $res) { (Get-Content $res -TotalCount 1) } else { "NO RESULT" }
  Write-Output ("{0,-18} {1}" -f $tag, $line)
}
$orders = @(@("legacy","v9","v9f"), @("v9f","legacy","v9"), @("v9","v9f","legacy"))
foreach ($rep in 1..$rounds) {
  foreach ($eng in $orders[($rep - 1) % 3]) { Run-One $eng $true "vol_${eng}_r$rep" }
  foreach ($eng in @("legacy","v9")) { Run-One $eng $false "full_${eng}_r$rep" }
}
Write-Output "WALLVS DONE"
