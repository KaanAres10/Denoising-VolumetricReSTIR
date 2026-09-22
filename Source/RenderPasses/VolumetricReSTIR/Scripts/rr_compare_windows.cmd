@echo off
rem Two small Mogwai windows side by side on bistro, one per DLSS Ray Reconstruction version:
rem
rem   left : DLSS 310.7.0 -- the previous RR -- starting on preset %1 (default E)
rem   right: DLSS 310.9.1 -- RR2 is its preset F -- starting on preset %2 (default F)
rem
rem   rr_compare_windows.cmd           E  |  F
rem   rr_compare_windows.cmd D E       D (310.7.0)  |  E (310.9.1, bit-identical to 310.7.0's E)
rem
rem Each window is its own process: the DLL is fixed per window, the preset is not -- switch it live in
rem Graphs > DLSSDPass > Render preset. The "Running:" line under it shows the DLL version actually
rem loaded and the preset in use. Each window also opens a console with its log. F2 hides the UI
rem overlay; WASD + mouse moves the camera; the two cameras are independent.
rem
rem Options, set beforehand (all optional; nothing else reads these names):
rem   RR_COMPARE_SIZE=960x540          size of each window
rem   RR_COMPARE_POS_LEFT=0,60         top-left of each window's image, in screen pixels; the right
rem   RR_COMPARE_POS_RIGHT=<w+20>,60   one defaults to just past the left one
rem   RR_COMPARE_EXIT_FRAME=N          close both after N frames (for testing)
setlocal EnableExtensions

rem Drop every VR_* variable inherited from the calling shell, so the windows always run the
rem configuration described above. A PowerShell session keeps any $env:VR_... set earlier: a leftover
rem VR_DISPLAY=1920x1080 once turned this into two full-HD windows at ~1 FPS on an 8 GB GPU.
for /f "delims==" %%v in ('set VR_ 2^>nul') do set "%%v="

set "ROOT=%~dp0..\..\..\.."
set "MOGWAI=%ROOT%\build\windows-vs2022\bin\Release\Mogwai.exe"
set "SCRIPT=%~dp0run_bistro_relax.py"
if not exist "%MOGWAI%" (
    echo Mogwai.exe not found at %MOGWAI% -- build the Release configuration first.
    exit /b 1
)

set "LEFT=%~1"
if "%LEFT%"=="" set "LEFT=E"
set "RIGHT=%~2"
if "%RIGHT%"=="" set "RIGHT=F"
set "SIZE=%RR_COMPARE_SIZE%"
if "%SIZE%"=="" set "SIZE=960x540"
for /f "tokens=1 delims=x" %%w in ("%SIZE%") do set /a RIGHT_X=%%w+20
set "POS_LEFT=%RR_COMPARE_POS_LEFT%"
if "%POS_LEFT%"=="" set "POS_LEFT=0,60"
set "POS_RIGHT=%RR_COMPARE_POS_RIGHT%"
if "%POS_RIGHT%"=="" set "POS_RIGHT=%RIGHT_X%,60"

set "VR_DENOISER=rr"
set "VR_DISPLAY=%SIZE%"
if not "%RR_COMPARE_EXIT_FRAME%"=="" set "VR_EXIT_FRAME=%RR_COMPARE_EXIT_FRAME%"

rem A child copies the environment when it starts, so each window keeps the values set just before it.
set "VR_SDK=Previous310_7"
set "VR_PRESET=%LEFT%"
set "VR_WINDOW_POS=%POS_LEFT%"
start "RR 310.7.0 - preset %LEFT% (log)" "%MOGWAI%" --script "%SCRIPT%"

set "VR_SDK=Current"
set "VR_PRESET=%RIGHT%"
set "VR_WINDOW_POS=%POS_RIGHT%"
start "RR 310.9.1 - preset %RIGHT% (log)" "%MOGWAI%" --script "%SCRIPT%"

echo Opened: left = DLSS 310.7.0 preset %LEFT%, right = DLSS 310.9.1 preset %RIGHT% (%SIZE% each).
endlocal
