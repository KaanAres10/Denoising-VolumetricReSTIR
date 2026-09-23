# Falcor 4.x (falcor4-legacy) vs 8.0 vs 9.0: the raw estimator alone, bistro orbit, 300 frames at 1080p.
# legacy/Scripts/_time_raw_legacy.py and Scripts/time_raw.py hold the graph, scene, path and timing
# identical. 3 wall-clock runs per engine, the order rotated each round so no engine always runs
# first (hot/cold GPU); every run is its own process. Then one per-pass profiler run per engine.
$repo = "C:\research\Denoising-VolumetricReSTIR"
$out = "$repo\outputs\legacy_cmp"
$exe = @{ legacy = "$repo\legacy\Bin\x64\Release\Mogwai.exe"
          v8     = "C:\research\falcor8-baseline-bin\Release\Mogwai.exe"
          v9     = "$repo\build\windows-vs2022\bin\Release\Mogwai.exe" }
$script = @{ legacy = "$repo\legacy\Scripts\_time_raw_legacy.py"
             v8     = "$repo\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py"
             v9     = "$repo\Source\RenderPasses\VolumetricReSTIR\Scripts\time_raw.py" }
$cwd = @{ legacy = "$repo\legacy"; v8 = $repo; v9 = $repo }

function Clear-Env { Get-ChildItem Env: | Where-Object { $_.Name -like "VR_*" -or $_.Name -like "NRD4_*" } | ForEach-Object { Set-Item -Path ("Env:" + $_.Name) -Value $null } }
function Run-One($eng, $tag, $passes) {
  Clear-Env
  if (-not (Test-Path "$repo\build\windows-vs2022\bin\Release\libprotoc.dll") -or -not (Test-Path "$repo\build\windows-vs2022\bin\Release\z.dll")) {
    & "$repo\tools\.packman\cmake\bin\cmake.exe" --build "$repo\build\windows-vs2022" --config Release --target restore_runtime_dlls 2>&1 | Out-Null }
  $env:VR_FRAMES = "300"; $env:VR_ENGINE = $eng
  $res = "$out\$tag.txt"; $env:VR_RESULT = $res
  if ($passes) {
    if ($eng -eq "legacy") { $env:VR_PASSTIME = "$out\${tag}_pass" } else { $env:VR_PASS_TIMES = "1" }
  }
  Set-Location $cwd[$eng]
  & $exe[$eng] --script $script[$eng] 2>&1 | Out-File "$out\$tag.log" -Encoding utf8
  $line = if (Test-Path $res) { (Get-Content $res -TotalCount 1) } else { "NO RESULT" }
  Write-Output ("{0,-22} exit={1} {2}" -f $tag, $LASTEXITCODE, $line)
}

$orders = @(@("legacy","v8","v9"), @("v9","legacy","v8"), @("v8","v9","legacy"))
foreach ($rep in 1..3) { foreach ($eng in $orders[$rep - 1]) { Run-One $eng "wall_${eng}_r$rep" $false } }
foreach ($eng in @("legacy","v8","v9")) { Run-One $eng "pass_$eng" $true }
Write-Output "LEGACY CMP DONE"
