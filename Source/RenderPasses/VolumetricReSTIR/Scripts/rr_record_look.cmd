@echo off
rem Record a video that matches the live side-by-side windows (rr_compare_windows.cmd): the same Look
rem graph at the same window size (native, not shrunk), starting where the windows start and orbiting
rem the plume -- or held still with RR_RECORD_ORBIT_DEG=0.
rem
rem   left : DLSS 310.7.0, preset %1 (default E)  -> outputs\lookorbit_prev_<preset>
rem   right: DLSS 310.9.1, preset %2 (default F)  -> outputs\lookorbit_cur_<preset>
rem   video: outputs\video\lookorbit_prev_<L>_vs_lookorbit_cur_<R>.mp4, the two side by side 1:1
rem          (prefix "look" instead of "lookorbit" when held still)
rem
rem   rr_record_look.cmd          E vs F (RR2)
rem   rr_record_look.cmd D E      D vs E
rem
rem Headless -- no windows open. About a minute per side at 960x540. Each run REPLACES its own two
rem capture folders: frames left over from a longer earlier run would otherwise end up in the video.
rem Options: RR_COMPARE_SIZE (default 960x540, as the windows), RR_RECORD_FRAMES (default 300 = 10 s),
rem          RR_RECORD_ORBIT_DEG (default -180; 0 holds the camera still),
rem          RR_RECORD_STOPS / RR_RECORD_STOP_S (stop-and-go: halt the orbit N times for S seconds each;
rem          prefix "lookstop"), e.g. RR_RECORD_STOPS=3 with the default 5 s.
setlocal EnableExtensions
rem Same rule as rr_compare_windows.cmd: nothing left over in the calling shell may change the graph.
for /f "delims==" %%v in ('set VR_ 2^>nul') do set "%%v="

set "ROOT=%~dp0..\..\..\.."
set "MOGWAI=%ROOT%\build\windows-vs2022\bin\Release\Mogwai.exe"
set "SCRIPT=%~dp0record_look.py"
set "OUTROOT=%ROOT%\outputs"
if not exist "%MOGWAI%" (
    echo Mogwai.exe not found at %MOGWAI% -- build the Release configuration first.
    exit /b 1
)

set "LEFT=%~1"
if "%LEFT%"=="" set "LEFT=E"
set "RIGHT=%~2"
if "%RIGHT%"=="" set "RIGHT=F"
set "VR_DISPLAY=%RR_COMPARE_SIZE%"
if "%VR_DISPLAY%"=="" set "VR_DISPLAY=960x540"
if not "%RR_RECORD_FRAMES%"=="" set "VR_RECORD_FRAMES=%RR_RECORD_FRAMES%"
set "VR_RECORD_ORBIT_DEG=%RR_RECORD_ORBIT_DEG%"
if "%VR_RECORD_ORBIT_DEG%"=="" set "VR_RECORD_ORBIT_DEG=-180"
if not "%RR_RECORD_STOPS%"=="" set "VR_RECORD_STOPS=%RR_RECORD_STOPS%"
if not "%RR_RECORD_STOP_S%"=="" set "VR_RECORD_STOP_S=%RR_RECORD_STOP_S%"
set "PREFIX=lookorbit"
if "%VR_RECORD_ORBIT_DEG%"=="0" set "PREFIX=look"
if not "%VR_RECORD_STOPS%"=="" if not "%VR_RECORD_STOPS%"=="0" if not "%VR_RECORD_ORBIT_DEG%"=="0" set "PREFIX=lookstop"
set "VR_DENOISER=rr"

echo Recording DLSS 310.7.0 preset %LEFT% ...
set "VR_SDK=Previous310_7"
set "VR_PRESET=%LEFT%"
set "VR_TAG=%PREFIX%_prev_%LEFT%"
set "VR_OUT_DIR=%OUTROOT%\%PREFIX%_prev_%LEFT%"
if exist "%VR_OUT_DIR%" rmdir /s /q "%VR_OUT_DIR%"
"%MOGWAI%" --headless --script "%SCRIPT%" > nul
if errorlevel 1 (echo   failed -- see the newest Mogwai.exe.*.log & exit /b 1)

echo Recording DLSS 310.9.1 preset %RIGHT% ...
set "VR_SDK=Current"
set "VR_PRESET=%RIGHT%"
set "VR_TAG=%PREFIX%_cur_%RIGHT%"
set "VR_OUT_DIR=%OUTROOT%\%PREFIX%_cur_%RIGHT%"
if exist "%VR_OUT_DIR%" rmdir /s /q "%VR_OUT_DIR%"
"%MOGWAI%" --headless --script "%SCRIPT%" > nul
if errorlevel 1 (echo   failed -- see the newest Mogwai.exe.*.log & exit /b 1)

pushd "%OUTROOT%"
python video_rr2.py %PREFIX%_prev_%LEFT% %PREFIX%_cur_%RIGHT%
popd
endlocal
