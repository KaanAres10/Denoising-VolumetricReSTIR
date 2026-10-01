"""The measure assumptions the Phase-B mutations rest on, checked on numpy replicas of the shader math.

A Metropolis-Hastings step accepts with min(1, p_hat(z) / p_hat(x)) only if the proposal is symmetric in
the measure p_hat is a density in. For this estimator that is dt x area (emissive), dt x solid angle
(env map); the reservoir stores the emissive point as the area-uniform u and the env direction as the
lat-long uv, so these tests pin that:
  - sample_triangle (Falcor MathHelpers.slang) maps u to area with a CONSTANT Jacobian, so a symmetric
    step in u is a symmetric step in area on the fixed triangle;
  - the inverse VolumeUtils.slang applies to the barycentrics it gets back recovers u;
  - the lat-long maps round-trip, so the env move can go uv -> direction -> uv;
  - the env move (rotate by a log-uniform angle, uniform azimuth) has a density that depends only on
    the angle between the directions: symmetric in solid angle;
  - the torus step frac(u + delta) and the depth step t + delta are symmetric.

    python -m unittest test_mutation_measures -v
"""
import unittest

import numpy as np

RNG = np.random.default_rng(20260927)
f32 = np.float32


def sample_triangle(u):
    """MathHelpers.slang: barycentrics (1-u-v, u, v) of the uniformly sampled point."""
    su = np.sqrt(u[..., 0])
    b = np.stack([1 - su, u[..., 1] * su], axis=-1)
    return np.stack([1 - b[..., 0] - b[..., 1], b[..., 0], b[..., 1]], axis=-1)


def stored_light_uv(bary_yz):
    """VolumeUtils.slang: the random numbers u recovered from TriangleLightSample.uv = bary.yz."""
    su = 1 - bary_yz[..., 0]
    safe = np.where(su > 0, su, 1)
    return np.stack([su * su, np.where(su > 0, np.clip(bary_yz[..., 1] / safe, 0, 1), 0)], axis=-1)


def world_to_latlong_map(d):
    p = d / np.linalg.norm(d, axis=-1, keepdims=True)
    return np.stack([np.arctan2(p[..., 0], -p[..., 2]) * (0.5 / np.pi) + 0.5,
                     np.arccos(np.clip(p[..., 1], -1, 1)) / np.pi], axis=-1)


def latlong_map_to_world(uv):
    phi = np.pi * (2 * np.clip(uv[..., 0], 0, 1) - 1)
    theta = np.pi * np.clip(uv[..., 1], 0, 1)
    return np.stack([np.sin(theta) * np.sin(phi), np.cos(theta), -np.sin(theta) * np.cos(phi)], axis=-1)


def perp_stark(u):
    """MathHelpers.slang: a unit vector perpendicular to u."""
    a = np.abs(u)
    uyx = (a[..., 0] - a[..., 1]) < 0
    uzx = (a[..., 0] - a[..., 2]) < 0
    uzy = (a[..., 1] - a[..., 2]) < 0
    xm = uyx & uzx
    ym = ~xm & uzy
    zm = ~(xm | ym)
    v = np.cross(u, np.stack([xm, ym, zm], axis=-1).astype(u.dtype))
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def kelemen_step(lo, hi, u):
    """MutateSamples.cs.slang: magnitude hi * exp(-log(hi / lo) * u.x), sign from u.y."""
    s = hi * np.exp(-np.log(hi / lo) * u[..., 0])
    return np.where(u[..., 1] < 0.5, s, -s)


def rotate_proposal(w, lo, hi, n):
    """MutateSamples.cs.slang's env-map move from direction w: n proposals."""
    theta = np.abs(kelemen_step(lo, hi, RNG.random((n, 2))))
    phi = 2 * np.pi * RNG.random(n)
    w = np.broadcast_to(w, (n, 3))
    t = perp_stark(w)
    b = np.cross(w, t)
    w2 = np.cos(theta)[:, None] * w + np.sin(theta)[:, None] * (np.cos(phi)[:, None] * t + np.sin(phi)[:, None] * b)
    return w2 / np.linalg.norm(w2, axis=-1, keepdims=True)


def ks_distance(a, b):
    """Two-sample Kolmogorov-Smirnov statistic."""
    a, b = np.sort(a), np.sort(b)
    grid = np.concatenate([a, b])
    return np.max(np.abs(np.searchsorted(a, grid, side="right") / len(a) - np.searchsorted(b, grid, side="right") / len(b)))


class TestEmissiveTriangle(unittest.TestCase):
    def test_triangle_warp_has_a_constant_jacobian(self):
        # |det d(bary.yz)/du| = 0.5 everywhere: the unit square of u maps onto the half-unit
        # barycentric triangle uniformly, so a step symmetric in u is symmetric in area.
        u = np.column_stack([RNG.uniform(1e-3, 1 - 1e-3, 1000), RNG.uniform(1e-3, 1 - 1e-3, 1000)])
        h = 1e-6
        J = np.empty((1000, 2, 2))
        for j in range(2):
            e = np.zeros(2)
            e[j] = h
            J[:, :, j] = (sample_triangle(u + e)[:, 1:] - sample_triangle(u - e)[:, 1:]) / (2 * h)
        np.testing.assert_allclose(np.abs(np.linalg.det(J)), 0.5, rtol=1e-6)

    def test_stored_light_uv_recovers_the_random_numbers(self):
        u = np.column_stack([RNG.uniform(1e-3, 1, 100000), RNG.uniform(0, 1, 100000)]).astype(f32)
        back = stored_light_uv(sample_triangle(u)[:, 1:].astype(f32))
        np.testing.assert_allclose(back, u, atol=1e-5)


class TestEnvMap(unittest.TestCase):
    def test_latlong_maps_round_trip_away_from_the_poles(self):
        uv = np.column_stack([RNG.uniform(0, 1, 100000), RNG.uniform(0.01, 0.99, 100000)]).astype(f32)
        back = world_to_latlong_map(latlong_map_to_world(uv).astype(f32)).astype(f32)
        du = np.abs(back[:, 0] - uv[:, 0])
        du = np.minimum(du, 1 - du)  # u wraps at the seam
        self.assertLess(du.max(), 1e-5)
        self.assertLess(np.abs(back[:, 1] - uv[:, 1]).max(), 1e-5)

    def test_rotation_proposal_density_depends_only_on_the_angle(self):
        # Two very different starting directions (near a pole, on the equator): the distribution of the
        # angle to the proposal is the same, and it is exactly the drawn theta in [lo, hi].
        lo, hi, n = np.radians(0.1), np.radians(5.0), 1_000_000
        angles = []
        for w in (np.array([0.05, 0.998, 0.03]), np.array([0.8, 0.0, -0.6])):
            w = w / np.linalg.norm(w)
            w2 = rotate_proposal(w, lo, hi, n)
            angles.append(np.arccos(np.clip(w2 @ w, -1, 1)))
        self.assertLess(ks_distance(*angles), 0.003)
        for a in angles:
            self.assertGreaterEqual(a.min(), lo * 0.999)
            self.assertLessEqual(a.max(), hi * 1.001)

    def test_rotation_proposal_azimuth_is_uniform(self):
        # Uniform azimuth about w makes the density at w' a function of angle(w, w') alone, which is
        # symmetric in w and w'.
        w = np.array([0.3, -0.5, 0.81])
        w = w / np.linalg.norm(w)
        w2 = rotate_proposal(w, np.radians(0.1), np.radians(5.0), 200000)
        t = perp_stark(w[None])[0]
        b = np.cross(w, t)
        az = np.arctan2(w2 @ b, w2 @ t)
        hist, _ = np.histogram(az, bins=36, range=(-np.pi, np.pi))
        self.assertLess(np.abs(hist / hist.mean() - 1).max(), 0.05)


class TestSteps(unittest.TestCase):
    def test_torus_step_is_symmetric(self):
        u = RNG.random(1_000_000)
        d = kelemen_step(1 / 1024, 1 / 64, RNG.random((1_000_000, 2)))
        moved = np.mod(u + d, 1.0)
        wrapped = (moved - u + 0.5) % 1.0 - 0.5  # signed torus displacement
        np.testing.assert_allclose(wrapped, d, atol=1e-12)  # steps are far below the half-period
        self.assertLess(ks_distance(wrapped, -wrapped), 0.003)
        self.assertLess(abs(wrapped.mean()), 1e-4)

    def test_kelemen_step_magnitude_is_log_uniform_and_the_sign_fair(self):
        lo, hi = 0.5, 16.0
        d = kelemen_step(lo, hi, RNG.random((1_000_000, 2)))
        mag = np.abs(d)
        self.assertGreaterEqual(mag.min(), lo * 0.9999)
        self.assertLessEqual(mag.max(), hi * 1.0001)
        hist, _ = np.histogram(np.log(mag), bins=20, range=(np.log(lo), np.log(hi)))
        self.assertLess(np.abs(hist / hist.mean() - 1).max(), 0.03)
        self.assertLess(abs((d > 0).mean() - 0.5), 0.002)

def light_select_step(x, target, propose, q, u):
    """MutateSamples.cs.slang's light re-selection (independence Metropolis-Hastings) on a replica state: draw z
    from the scene's own light samplers, accept with min(1, p_hat(z) q(x) / (p_hat(x) q(z)))."""
    z = propose()
    pz, qz = target(z), q(z)
    return z if pz > 0 and qz > 0 and u * target(x) * qz < pz * q(x) else x


class TestLightSelect(unittest.TestCase):
    def test_independence_move_keeps_the_mixed_target(self):
        # One point light (a point mass), one emissive triangle (area, t in [0, 1)) and a sky (solid angle,
        # reduced to an angle a in [0, pi)): p_hat and q are densities in that mixed measure, and the chain
        # must spend on each part its share of the integral of p_hat -- whatever the proposal's kind
        # probabilities or the sky sampler's importance.
        point, tri_int, sky_int = 0.5, 1.0 / 3.0, 2.0 / np.pi   # integral of p_hat over each part
        def target(s):
            kind, v = s
            return point if kind == 0 else (v * v if kind == 1 else np.sin(v) / np.pi)
        pk = 1.0 / 3.0
        def propose():
            k = int(RNG.integers(0, 3))
            if k == 0:
                return (0, 0.0)
            if k == 1:
                return (1, RNG.random())                        # uniform point: q = pk / area
            return (2, np.pi * np.sqrt(RNG.random()))          # importance on the sky: density 2a / pi^2
        def q(s):
            kind, v = s
            return pk if kind == 0 else (pk if kind == 1 else pk * 2 * v / np.pi ** 2)
        x, kinds, tri = (1, 0.9), np.zeros(3), []
        for i in range(200000):
            x = light_select_step(x, target, propose, q, RNG.random())
            kinds[x[0]] += 1
            if x[0] == 1:
                tri.append(x[1])
        total = point + tri_int + sky_int
        np.testing.assert_allclose(kinds / kinds.sum(), [point / total, tri_int / total, sky_int / total], atol=0.01)
        # Within the triangle the chain follows p_hat = t^2: its CDF is t^3.
        self.assertLess(ks_distance(np.array(tri) ** 3, RNG.random(len(tri))), 0.02)

    def test_the_inverted_ratio_is_caught(self):
        # The same chain with q(z) / q(x) the wrong way round converges elsewhere: the test above can fail.
        pk = 0.5
        target = lambda s: 1.0 if s[0] == 0 else 1.0     # equal shares
        propose = lambda: (0, 0.0) if RNG.random() < 0.9 else (1, 0.0)
        q = lambda s: 0.9 if s[0] == 0 else 0.1
        wrong = lambda x, u: (lambda z: z if u * target(x) * q(x) < target(z) * q(z) else x)(propose())
        x, n0 = (0, 0.0), 0
        for i in range(50000):
            x = wrong(x, RNG.random())
            n0 += x[0] == 0
        self.assertGreater(abs(n0 / 50000 - 0.5), 0.2)


ANALYTIC_UNIFORM_MIX = 0.05  # MutateSamples.cs.slang's kAnalyticUniformMix


def analytic_pmf(w, i, eps=ANALYTIC_UNIFORM_MIX):
    """MutateSamples.cs.slang's analyticPmf: q(i) = (1 - eps) w_i / sum(w) + eps / N (uniform if sum(w) = 0)."""
    s = float(np.sum(w))
    return 1.0 / len(w) if not s > 0 else (1 - eps) * w[i] / s + eps / len(w)


def sample_analytic(w, u, eps=ANALYTIC_UNIFORM_MIX):
    """MutateSamples.cs.slang's sampleAnalytic: one u, split between the uniform share and an inverse-CDF walk over
    the weights; a rounding overshoot lands on the last light with a positive weight."""
    n, s = len(w), float(np.sum(w))
    if not s > 0:
        return min(int(u * n), n - 1)
    if u < eps:
        return min(int(u / eps * n), n - 1)
    target, last = (u - eps) / (1 - eps) * s, n - 1
    for i in range(n):
        if w[i] > 0:
            last = i
        target -= w[i]
        if target < 0:
            return i
    return last


class TestWeightedAnalyticProposal(unittest.TestCase):
    """The re-selection move's position-aware proposal for point lights: light i with probability
    (1 - eps) w_i / sum(w) + eps / N, w_i its unshadowed contribution at the scatter point."""
    # 12 lights: contributions over three orders of magnitude, two outside their spot cones (w = 0).
    w = np.array([5.0, 0.2, 0.0, 1.5, 0.01, 3.0, 0.0, 0.4, 8.0, 0.05, 0.7, 2.2])

    def test_draws_follow_the_pmf_the_move_evaluates(self):
        n = 200000
        counts = np.bincount([sample_analytic(self.w, RNG.random()) for _ in range(n)], minlength=len(self.w))
        pmf = np.array([analytic_pmf(self.w, i) for i in range(len(self.w))])
        self.assertAlmostEqual(pmf.sum(), 1.0, places=12)
        self.assertTrue(np.all(pmf > 0))                    # the uniform share: every light can be proposed
        np.testing.assert_allclose(counts / n, pmf, atol=0.003)

    def test_independence_move_keeps_the_target_and_accepts_more(self):
        # p_hat = w times a per-light transmittance the proposal does not know.
        T = np.array([0.9, 0.3, 1.0, 0.5, 0.8, 0.05, 0.7, 1.0, 0.6, 0.2, 0.9, 0.4])
        target = self.w * T
        def chain(weighted, n=150000):
            x, counts, acc = 8, np.zeros(len(self.w)), 0
            q = (lambda i: analytic_pmf(self.w, i)) if weighted else (lambda i: 1.0 / len(self.w))
            for _ in range(n):
                z = sample_analytic(self.w, RNG.random()) if weighted else int(RNG.integers(len(self.w)))
                if target[z] > 0 and RNG.random() * target[x] * q(z) < target[z] * q(x):
                    x, acc = z, acc + 1
                counts[x] += 1
            return counts / n, acc / n
        shares, acc_w = chain(True)
        np.testing.assert_allclose(shares, target / target.sum(), atol=0.01)
        _, acc_u = chain(False)
        self.assertGreater(acc_w, 2 * acc_u)


def free_flight_sample(sigma, edges, u):
    """VolumeTrackingAdapterGVDB.slang's SampleMediumAnalyticAdapterGVDB, nearest sampler, on a 1D ray: voxel k spans
    [edges[k], edges[k+1]) with extinction sigma[k]; each voxel draws dT = -log(1 - u) / sigma with a fresh u, and the
    first with edges[k] + dT < its exit holds the hit. Returns (t, sigma_t(t) T(0, t)), or (None, T(0, end)) on escape."""
    tau = 0.0
    for k, s in enumerate(sigma):
        uk = u()
        if s > 0:
            dT = -np.log(1 - uk) / s
            if edges[k] + dT < edges[k + 1]:
                return edges[k] + dT, s * np.exp(-(dT * s + tau))
        tau += (edges[k + 1] - edges[k]) * s
    return None, np.exp(-tau)


def free_flight_pdf(sigma, edges, t):
    """MutateSamples.cs.slang's FreeFlightPdfAdapterGVDB: the same march stopped at t, sigma_t(t) T(0, t); 0 outside."""
    tau = 0.0
    for k, s in enumerate(sigma):
        if edges[k] <= t < edges[k + 1]:
            return s * np.exp(-(tau + (t - edges[k]) * s))
        tau += (edges[k + 1] - edges[k]) * s
    return 0.0


def flight_step(x, target, sigma, edges, u, use_q=True):
    """MutateSamples.cs.slang's free-flight depth move: an INDEPENDENCE proposal from the renderer's own distance
    sampler (on its coarse grid), accepted with min(1, p_hat(z) q(x) / (p_hat(x) q(z))); an escape proposes nothing."""
    z, qz = free_flight_sample(sigma, edges, lambda: RNG.random())
    if z is None:
        return x
    qx = free_flight_pdf(sigma, edges, x) if use_q else 1.0
    if not use_q:
        qz = 1.0
    pz = target(z)
    return z if pz > 0 and qz > 0 and u * target(x) * qz < pz * qx else x


class TestFreeFlight(unittest.TestCase):
    # The proposal's grid: coarse voxels of width 1, the fourth empty -- a gap no bounded depth step crosses.
    coarse = np.array([0.3, 0.5, 0.2, 0.0, 0.25, 0.15])   # T(0, 6) = exp(-1.4): 1/4 escape
    edges = np.arange(7, dtype=float)
    # p_hat's own grid: twice as fine, zero only where the coarse grid is (the conservative grid covers it).
    fine = np.array([0.2, 0.4, 0.9, 0.1, 0.1, 0.3, 0.0, 0.0, 0.4, 0.1, 0.05, 0.25])
    fine_edges = np.arange(13, dtype=float) / 2

    def target(self, t):
        """sigma_s(t) T(0, t) L(t) on the fine grid, with a light term that varies along the ray."""
        return free_flight_pdf(self.fine, self.fine_edges, t) * 0.8 * (1.0 + 3.0 * np.sin(t) ** 2)

    def test_the_evaluator_is_the_sampler_density(self):
        samples, pdfs = [], []
        for i in range(100000):
            t, p = free_flight_sample(self.coarse, self.edges, lambda: RNG.random())
            if t is not None:
                samples.append(t)
                pdfs.append(p)
                if i < 1000:
                    self.assertAlmostEqual(p, free_flight_pdf(self.coarse, self.edges, t), places=12)
        # Mass per half-voxel against the evaluator's integral (midpoint rule on a fine grid).
        hist = np.histogram(samples, bins=self.fine_edges)[0] / 100000
        grid = np.linspace(0, 6, 60001)[:-1] + 0.5e-4
        dens = np.array([free_flight_pdf(self.coarse, self.edges, t) for t in grid]) * 1e-4
        expected = np.add.reduceat(dens, np.arange(0, 60000, 5000))
        np.testing.assert_allclose(hist, expected, atol=0.004)

    def run_chain(self, use_q, n=120000):
        x, out = 0.3, np.empty(n)
        for i in range(n):
            x = flight_step(x, self.target, self.coarse, self.edges, RNG.random(), use_q)
            out[i] = x
        return np.histogram(out, bins=self.fine_edges)[0] / n

    def expected_shares(self):
        grid = np.linspace(0, 6, 60001)[:-1] + 0.5e-4
        dens = np.array([self.target(t) for t in grid])
        share = np.add.reduceat(dens, np.arange(0, 60000, 5000))
        return share / share.sum()

    def test_independence_depth_move_keeps_the_target(self):
        # The chain crosses the empty voxel (a jump no random walk with bounded steps makes) and spends on each
        # half-voxel its share of p_hat, although p_hat and q live on different grids and 1/4 of proposals escape.
        np.testing.assert_allclose(self.run_chain(True), self.expected_shares(), atol=0.01)

    def test_without_the_proposal_ratio_it_converges_elsewhere(self):
        # Accepting with p_hat(z) / p_hat(x) alone samples p_hat q instead: the test above can fail.
        self.assertGreater(np.abs(self.run_chain(False, 40000) - self.expected_shares()).max(), 0.05)


if __name__ == "__main__":
    unittest.main()
