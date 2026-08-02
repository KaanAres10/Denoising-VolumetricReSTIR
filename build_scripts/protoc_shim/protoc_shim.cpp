/** Shim for the single protobuf symbol Falcor.dll ends up importing.
 *
 * Falcor.dll's import table names libprotoc.dll and takes exactly ONE symbol from it:
 *
 *     ?__global_delete@@YAXPEAX_K@Z   ==   void __global_delete(void*, unsigned __int64)
 *
 * which is a sized `operator delete`. No packman package on a current checkout ships
 * libprotoc.dll -- not falcor_dependencies, not nv-usd (the "nopy" variant here has one DLL in
 * bin/ and no protobuf at all) -- and no linked .lib or .obj carries a /DEFAULTLIB directive for
 * it either, so the import cannot be removed by turning a CMake option off. FALCOR_ENABLE_USD only
 * gates the USD *importer plugin*; the import survives with it ON or OFF.
 *
 * The loader resolves static imports before any code runs, so a missing libprotoc.dll kills the
 * process at startup with 0xC0000135 (STATUS_DLL_NOT_FOUND) before main(): no log, no window, and
 * even `Mogwai --help` fails, which reads as a corrupt build rather than a missing file. See the
 * matching note in deploycommon.bat, which already aliases zlib.dll to z.dll for the same reason.
 *
 * Forwarding to the CRT is semantically correct -- this IS sized operator delete, and the sized
 * form is permitted to ignore its size argument. If a real libprotoc.dll ever appears in the
 * dependency set, delete this target: the CMake guard below already declines to build over one.
 */

#include <new>

extern "C++" void __global_delete(void* p, unsigned __int64 /*size*/)
{
    ::operator delete(p);
}
