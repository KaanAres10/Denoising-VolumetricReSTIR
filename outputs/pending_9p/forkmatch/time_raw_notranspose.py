# time_raw.py with the estimator's previous-frame matrices NOT transposed (mTransposePrevMatrices=False):
# the reprojection the port had before the fix, for comparing temporal reuse against the fork.
import sys
S = r"C:\research\Denoising-VolumetricReSTIR\Source\RenderPasses\VolumetricReSTIR\Scripts"
sys.path.insert(0, S)
import vr_graph
_orig = vr_graph.add_restir
def _patched(*a, **k):
    k["mTransposePrevMatrices"] = False
    return _orig(*a, **k)
vr_graph.add_restir = _patched
exec(compile(open(S + r"\time_raw.py").read(), S + r"\time_raw.py", "exec"))
