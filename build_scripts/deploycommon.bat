@echo off
setlocal

rem %1 -> Project directory
rem %2 -> Binary output directory
rem %3 -> Build configuration
rem %4 -> Slang directory
rem %5 -> DLSS directory
rem %6 -> NRD directory (whichever SDK CMake selected; see FALCOR_NRD_DIR)

set ExtDir=%1\external\packman\
set OutDir=%2

set IsDebug=0
if "%3" == "Debug" set IsDebug=1

set SlangDir=%4
set DLSSDir=%5

rem Copy externals
if %IsDebug% EQU 0 (
    robocopy %ExtDir%\deps\bin\ %OutDir% /E /r:0 >nul
) else (
    robocopy %ExtDir%\deps\debug\bin\ %OutDir% /E /r:0 >nul
    robocopy %ExtDir%\deps\bin\ %OutDir% assimp-vc143-mt.* /r:0 >nul
    rem Needed for OpenVDB (debug version links to release version of Half_2.5)
    robocopy %ExtDir%\deps\bin\ %OutDir% Half-2_5.* /r:0 >nul
)
robocopy %ExtDir%\python\ %OutDir% python*.dll /r:0 >nul
robocopy %ExtDir%\python %OutDir%\pythondist /E /r:0 >nul
robocopy %SlangDir%\bin %OutDir% *.dll /r:0 >nul
robocopy %ExtDir%\pix\bin\x64 %OutDir% WinPixEventRuntime.dll /r:0 >nul
robocopy %ExtDir%\dxcompiler\bin\x64 %OutDir% dxil.dll /r:0 >nul
robocopy %ExtDir%\dxcompiler\bin\x64 %OutDir% dxcompiler.dll /r:0 >nul
robocopy %ExtDir%\nvtt\ %OutDir% cudart64_110.dll /r:0 >nul
robocopy %ExtDir%\nvtt\ %OutDir% nvtt30106.dll /r:0 >nul
robocopy %ExtDir%\cuda\bin\ %OutDir% cudart*.dll /r:0 >nul
robocopy %ExtDir%\cuda\bin\ %OutDir% nvrtc*.dll /r:0 >nul
robocopy %ExtDir%\cuda\bin\ %OutDir% cublas*.dll /r:0 >nul
robocopy %ExtDir%\cuda\bin\ %OutDir% curand*.dll /r:0 >nul

rem Copy Aftermath
set AftermathDir=%ExtDir%\aftermath
if exist %AftermathDir% (
    copy /y %AftermathDir%\lib\x64\GFSDK_Aftermath_Lib.x64.dll %OutDir% >nul
    copy /y %AftermathDir%\lib\x64\llvm_7_0_1.dll %OutDir% >nul
)

rem Copy NVAPI
set NvApiDir=%ExtDir%\nvapi
set NvApiTargetDir=%OutDir%\shaders\nvapi
if exist %NvApiDir% (
    if not exist %NvApiTargetDir% mkdir %NvApiTargetDir% >nul
    copy /y %NvApiDir%\nvHLSLExtns.h %NvApiTargetDir% >nul
    copy /y %NvApiDir%\nvHLSLExtnsInternal.h %NvApiTargetDir% >nul
    copy /y %NvApiDir%\nvShaderExtnEnums.h %NvApiTargetDir% >nul
)

rem Copy NRD.
rem
rem The directory comes from CMake (%6 = FALCOR_NRD_DIR) rather than being probed here, because two
rem SDKs can be vendored at once and only CMake knows which one the code was compiled against.
rem Probing for existence would happily ship v4 shaders next to a v3.1-built NRDPass -- and a
rem DLL/shader mismatch compiles and then denoises incorrectly instead of failing.
rem
rem Layout differs between them: v4 is FLAT (Shaders\*.cs.hlsl beside ml.hlsli), v3.1 nests under
rem Shaders\Source. Both are copied recursively, so only the Lib layout needs a branch -- v4 ships
rem Release only.
set NrdDir=%6
set NrdTargetDir=%OutDir%\shaders\nrd\Shaders
if not "%NrdDir%" == "" (
    if exist %NrdDir%\Include\NRD.h (
        if not exist %NrdTargetDir% mkdir %NrdTargetDir% >nul
        rem /PURGE: a leftover v3.1 Source\ subtree would still satisfy #includes and could win over
        rem the v4 headers, giving a silently mixed shader set.
        robocopy %NrdDir%\Shaders %NrdTargetDir% /s /purge /r:0 >nul
        if exist %NrdDir%\Lib\Debug (
            if %IsDebug% EQU 0 (
                robocopy %NrdDir%\Lib\Release %OutDir% *.dll /r:0 >nul
            ) else (
                robocopy %NrdDir%\Lib\Debug %OutDir% *.dll /r:0 >nul
            )
        ) else (
            robocopy %NrdDir%\Lib\Release %OutDir% *.dll /r:0 >nul
        )
    )
)

rem Copy RTXDI SDK shaders
set RtxdiSDKDir=%ExtDir%\rtxdi\rtxdi-sdk\include\rtxdi
set RtxdiSDKTargetDir=%OutDir%\shaders\rtxdi
if exist %RtxdiSDKDir% (
    if not exist %RtxdiSDKTargetDir% mkdir %RtxdiSDKTargetDir% >nul
    copy /y %RtxdiSDKDir%\ResamplingFunctions.hlsli %RtxdiSDKTargetDir% >nul
    copy /y %RtxdiSDKDir%\Reservoir.hlsli %RtxdiSDKTargetDir% >nul
    copy /y %RtxdiSDKDir%\RtxdiHelpers.hlsli %RtxdiSDKTargetDir% >nul
    copy /y %RtxdiSDKDir%\RtxdiMath.hlsli %RtxdiSDKTargetDir% >nul
    copy /y %RtxdiSDKDir%\RtxdiParameters.h %RtxdiSDKTargetDir% >nul
    copy /y %RtxdiSDKDir%\RtxdiTypes.h %RtxdiSDKTargetDir% >nul
)

rem Copy Agility SDK Runtime
rem
rem %7 = FALCOR_AGILITY_SDK_DIR. [9.0] the SDK moved from a packman package to a FetchPackage under
rem the BUILD tree, so %ExtDir%\agility-sdk no longer exists and the old `if exist` guard silently
rem skipped -- leaving the previous engine's D3D12Core.dll in place. That is not a benign staleness:
rem Falcor exports D3D12SDKVersion = FALCOR_D3D12_AGILITY_SDK_VERSION (717 in 9.0), and an older
rem runtime beside it makes device creation fail with "Failed to create device on GPU 0".
rem
rem Taken from CMake rather than probed, like the NRD directory above: only CMake knows the version
rem the binary was compiled to export, and a mismatch here fails at startup with no useful message.
set AgilitySDKDir=%7
if "%AgilitySDKDir%" == "" set AgilitySDKDir=%ExtDir%\agility-sdk
set AgilitySDKTargetDir=%OutDir%\D3D12
if exist "%AgilitySDKDir%\build\native\bin\x64\D3D12Core.dll" (
    if not exist %AgilitySDKTargetDir% mkdir %AgilitySDKTargetDir% >nul
    copy /y "%AgilitySDKDir%\build\native\bin\x64\D3D12Core.dll" %AgilitySDKTargetDir% >nul
    copy /y "%AgilitySDKDir%\build\native\bin\x64\d3d12SDKLayers.dll" %AgilitySDKTargetDir% >nul
) else (
    echo [deploycommon] WARNING: no Agility SDK at "%AgilitySDKDir%"; D3D12Core.dll left as-is.
)

rem Copy NanoVDB
set NanoVDBDir=%ExtDir%\nanovdb
set NanoVDBTargetDir=%OutDir%\shaders\NanoVDB
if exist %NanoVDBDir% (
    if not exist %NanoVDBTargetDir% mkdir %NanoVDBTargetDir% >nul
    copy /y %NanoVDBDir%\include\nanovdb\PNanoVDB.h %NanoVDBTargetDir% >nul
)

rem Copy USD files, making sure not to overwrite dlls provided by other components, or dlls that we don't need.
if %IsDebug% EQU 0 (
    robocopy %ExtDir%\nv-usd-release\lib %OutDir% *.dll /r:0 /XF Alembic.dll dds.dll nv_freeimage.dll python*.dll hdf5*.dll tbb*.dll >nul
    robocopy %ExtDir%\nv-usd-release\lib\usd %OutDir%\usd /E /r:0 >nul
    robocopy %ExtDir%\nv-usd-release\lib\python\pxr %OutDir%\pythondist\Lib\pxr /E /r:0 >nul
) else (
    robocopy %ExtDir%\nv-usd-debug\lib %OutDir% *.dll /r:0 /XF Alembic.dll dds.dll nv_freeimage.dll python*.dll hdf5*.dll tbb*.dll >nul
    robocopy %ExtDir%\nv-usd-debug\lib\usd %OutDir%\usd /E /r:0 >nul
    robocopy %ExtDir%\nv-usd-debug\lib\python\pxr %OutDir%\pythondist\Lib\pxr /E /r:0 >nul
)

rem Copy MDL libs after USD to overwrite older versions included in USD distribution
set MDLDir=%ExtDir%\mdl-sdk
if exist %MDLDir% (
    robocopy %MDLDir%\nt-x86-64\lib %OutDir% *.dll /r:0 >nul
    if not exist %OutDir%\mdl\nvidia mkdir %OutDir%\mdl\nvidia >nul
    robocopy %MDLDir%\examples\mdl\nvidia %OutDir%\mdl\nvidia core* /r:0 >nul
)

rem Copy NVTT
if %IsDebug% EQU 0 (
    robocopy %ExtDir%\nvtt\lib\x64-v141\Release %OutDir% nvtt.dll /r:0 >nul
) else (
    robocopy %ExtDir%\nvtt\lib\x64-v141\Debug %OutDir% nvtt.dll /r:0 >nul
)

rem Copy DLSS. nvngx_dlssd.dll is Ray Reconstruction and only exists in SDKs from the 310.x line;
rem robocopy silently skips missing files, so this stays correct against the 3.5.0 packman package.
if exist %DLSSDir% (
    robocopy %DLSSDir%\lib\Windows_x86_64\rel %OutDir% nvngx_dlss.dll nvngx_dlssd.dll /r:0 >nul
)

rem Copy the legacy (3.7.x) Super Resolution DLL into its own subdirectory. It must NOT sit next to
rem the current one -- same filename, and whichever NGX finds first wins. DLSSPass selects between
rem them by passing this directory as the NGX feature search path. There is deliberately no
rem nvngx_dlssd.dll here: no 3.x SDK ever shipped Ray Reconstruction.
rem
rem The vendored SDKs live in external\, not external\packman\ (%ExtDir%). This used to test
rem %ExtDir%\dlss-legacy-37, which never exists, so the copy silently never ran and dlss_cnn\ only
rem existed because it had been populated by hand -- a fresh build directory had no CNN DLL at all.
if exist %1\external\dlss-legacy-37 (
    robocopy %1\external\dlss-legacy-37\lib\Windows_x86_64\rel %OutDir%\dlss_cnn nvngx_dlss.dll /r:0 >nul
)

rem Copy the 310.7.0 SDK's DLLs into their own subdirectory, for the "Previous310_7" SDK variant of
rem DLSSPass and DLSSDPass: Ray Reconstruction's transformer presets D/E as they were before 310.9.1
rem made RR2 (preset F) the default. Same rule as dlss_cnn -- never beside the current DLLs -- and
rem both features are copied because one NGX session serves every DLSS pass in a graph, so the two
rem passes must be able to select the same directory.
if exist %1\external\dlss-310 (
    robocopy %1\external\dlss-310\lib\Windows_x86_64\rel %OutDir%\dlss_310_7 nvngx_dlss.dll nvngx_dlssd.dll /r:0 >nul
)

rem Falcor.dll imports libprotoc/protobuf/abseil and z.dll at LOAD time (via the USD build), but the
rem USD deployment only puts them in plugins\. The loader searches the executable's directory, not
rem plugins\, so without these the process dies at startup with 0xC0000135 (STATUS_DLL_NOT_FOUND)
rem before main() -- no log, no window, and Mogwai --help fails too, which makes it look like a
rem corrupt build rather than a missing file.
if exist %OutDir%\plugins\libprotoc.dll (
    robocopy %OutDir%\plugins %OutDir% libprotoc.dll libprotobuf.dll abseil_dll.dll /r:0 >nul
)
if not exist %OutDir%\z.dll (
    if exist %ExtDir%\nv-usd-release\bin\zlib.dll (
        rem Same library, and the import binds by the name Falcor was linked against.
        copy /y %ExtDir%\nv-usd-release\bin\zlib.dll %OutDir%\z.dll >nul
    )
)

rem robocopy sets the error level to something that is not zero even if the copy operation was successful. Set the error level to zero
exit /b 0
