import glob, os, re, cv2, numpy as np
cv2.setNumThreads(0)
def load(d):
    got=[]
    for f in glob.glob(d+"/*.png"):
        m=re.search(r"\.(\d+)\.png$", os.path.basename(f))
        if m: got.append((int(m.group(1)), f))
    return [cv2.resize(cv2.imread(f, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32).mean(axis=2)/255.0,
                       (1280,720), interpolation=cv2.INTER_AREA) for _,f in sorted(got)]
def row(label, d):
    if not glob.glob(d+"/*.png"):
        print("%-32s (no frames)" % label, flush=True); return
    g=load(d); h,w=g[0].shape
    inner=np.zeros((h,w),bool); inner[int(0.05*h):int(0.95*h), int(0.34*w):int(0.66*w)]=True
    def sc(mask,s):
        mu=float(np.mean([x[mask].mean() for x in g]))
        b=[cv2.GaussianBlur(x,(0,0),s) for x in g]
        return 1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2])[mask].mean() for i in range(2,len(b))]))/mu
    mu=float(np.mean([x.mean() for x in g]))
    detp=float(np.mean([np.abs(x-cv2.GaussianBlur(x,(0,0),2))[inner].mean() for x in g]))/mu
    print("%-32s %8.2f %9.2f %10.2f %12.4f"
          % (label, sc(np.ones((h,w),bool),32), sc(inner,16), sc(~inner,16), detp), flush=True)
print("%-32s %8s %9s %10s %12s" % ("TAA motion vectors","s=32","plume","surfaces","plume detail"), flush=True)
for name, a, b in (("RELAX-SH","fx_relax","fxv_relax"),
                   ("REBLUR-SH","fx_reblur","fxv_reblur"),
                   ("DLSS RR","fx_rr","fxv_rr"),
                   ("OptiX","fx_optix_matched","fxv_optix"),
                   ("raw ReSTIR","fx_raw","fx_raw_volmv")):
    row(name + " - surface mvec", a)
    row(name + " - VOLUME mvec", b)
