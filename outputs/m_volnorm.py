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
    g=load(d); h,w=g[0].shape
    inner=np.zeros((h,w),bool); inner[int(0.05*h):int(0.95*h), int(0.34*w):int(0.66*w)]=True
    def sc(mask,s):
        mu=float(np.mean([x[mask].mean() for x in g]))
        b=[cv2.GaussianBlur(x,(0,0),s) for x in g]
        return 1e3*float(np.mean([np.abs(b[i]-2*b[i-1]+b[i-2])[mask].mean() for i in range(2,len(b))]))/mu
    mu=float(np.mean([x.mean() for x in g]))
    # detail measured INSIDE the plume: this is the guide the density gradient is supposed to help.
    det_plume=float(np.mean([np.abs(x-cv2.GaussianBlur(x,(0,0),2))[inner].mean() for x in g]))/mu
    print("%-34s %8.2f %9.2f %10.2f %12.4f"
          % (label, sc(np.ones((h,w),bool),32), sc(inner,16), sc(~inner,16), det_plume), flush=True)
print("%-34s %8s %9s %10s %12s" % ("RELAX-SH, volume normal mode","s=32","plume","surfaces","plume detail"), flush=True)
row("camera-facing stand-in", "fx_relax_camera")
row("density gradient", "fx_relax")
