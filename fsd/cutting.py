"""1D cutting stock: first-fit-decreasing vs an exact pattern ILP (HiGHS).

Bar model (assumptions, stated in the README):

* stock bars of length ``L`` (default 6000 and 6500 mm);
* ``TRIM`` mm is cut off each bar first to square the mill ends;
* every piece costs its length plus one saw ``KERF``;
* a bar is feasible if ``sum(piece + KERF) <= L - TRIM``.

Objective (both methods are scored the same way): minimise purchased bar length;
ties are broken by fewer bars. With this lexicographic objective the totals
(bars per stock length, purchased length, offcut) are unique even if several
cutting patterns achieve them.
"""
import itertools
from collections import Counter

import numpy as np

STOCK = (6000, 6500)
KERF = 5
TRIM = 20
TIE = 10000          # cost = TIE * length + 1 per bar -> lexicographic (length, bars)


def capacity(L, trim=TRIM):
    return L - trim


def fits(pieces, L, kerf=KERF, trim=TRIM):
    return sum(p + kerf for p in pieces) <= capacity(L, trim)


def _check_demand(demand, stock, kerf, trim):
    for length, q in demand.items():
        if q < 0 or length <= 0:
            raise ValueError("bad demand %r x %r" % (length, q))
        if not any(length + kerf <= capacity(L, trim) for L in stock):
            raise ValueError("piece %d mm does not fit any stock bar" % length)


def ffd(demand, stock=STOCK, kerf=KERF, trim=TRIM):
    """First-fit decreasing. New bars open at the longest stock length; at the
    end every bar is shrunk to the shortest stock length that still holds it."""
    _check_demand(demand, stock, kerf, trim)
    pieces = sorted((l for l, q in demand.items() for _ in range(q)), reverse=True)
    longest = max(stock)
    bars = []          # [used_mm, [pieces]] in opening order
    live = []          # bars that can still take the smallest piece (same order)
    cap = capacity(longest, trim)
    smallest = (pieces[-1] + kerf) if pieces else 0
    for p in pieces:
        need = p + kerf
        for b in live:
            if b[0] + need <= cap:
                b[0] += need
                b[1].append(p)
                break
        else:
            b = [need, [p]]
            bars.append(b)
            live.append(b)
        if cap - b[0] < smallest:      # nothing left can ever fit: close it
            live.remove(b)
    out = []
    for used, ps in bars:
        L = min(s for s in stock if used <= capacity(s, trim))
        out.append((L, tuple(sorted(ps, reverse=True))))
    return out


def patterns(demand, stock=STOCK, kerf=KERF, trim=TRIM):
    """Every non-empty feasible pattern (L, counts-per-length) within demand."""
    lengths = sorted(demand, reverse=True)
    out = []
    for L in sorted(stock):
        cap = capacity(L, trim)
        ranges = [range(min(demand[l], cap // (l + kerf)) + 1) for l in lengths]
        for combo in itertools.product(*ranges):
            if any(combo) and sum(a * (l + kerf) for a, l in zip(combo, lengths)) <= cap:
                out.append((L, dict(zip(lengths, combo))))
    return out


def ilp(demand, stock=STOCK, kerf=KERF, trim=TRIM):
    """Exact optimum via full pattern enumeration + integer program in HiGHS.

    Returns (bars, info) with bars as [(L, pieces)] and info holding the solver
    status, the MIP gap reported by HiGHS and the LP-relaxation bound.
    """
    import highspy

    _check_demand(demand, stock, kerf, trim)
    demand = {l: q for l, q in demand.items() if q > 0}
    if not demand:
        return [], {"status": "Optimal", "mip_gap": 0.0, "lp_bound_mm": 0.0}
    pats = patterns(demand, stock, kerf, trim)
    lengths = sorted(demand, reverse=True)
    n = len(pats)
    cost = np.array([TIE * L + 1 for L, _ in pats], dtype=float)

    def solve(integer):
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("mip_rel_gap", 0.0)
        h.setOptionValue("mip_abs_gap", 0.5)          # costs are integers
        h.setOptionValue("random_seed", 0)
        h.setOptionValue("threads", 1)
        inf = highspy.kHighsInf
        for j in range(n):
            h.addVar(0.0, inf)
            h.changeColCost(j, cost[j])
            if integer:
                h.changeColIntegrality(j, highspy.HighsVarType.kInteger)
        for l in lengths:
            idx = [j for j, (_, a) in enumerate(pats) if a[l] > 0]
            val = [float(pats[j][1][l]) for j in idx]
            h.addRow(float(demand[l]), float(demand[l]), len(idx),
                     np.array(idx, dtype=np.int32), np.array(val))
        h.run()
        return h

    h = solve(True)
    status = h.modelStatusToString(h.getModelStatus())
    if status != "Optimal":
        raise RuntimeError("HiGHS status %s" % status)
    x = [int(round(v)) for v in h.getSolution().col_value]
    mip_gap = h.getInfo().mip_gap
    lp = solve(False)
    lp_bound = lp.getInfo().objective_function_value / TIE
    bars = []
    for (L, a), k in zip(pats, x):
        pieces = tuple(l for l in lengths for _ in range(a[l]))
        bars.extend([(L, pieces)] * k)
    bars.sort(key=lambda b: (-b[0], b[1]), reverse=False)
    return bars, {"status": status, "mip_gap": float(mip_gap), "lp_bound_mm": lp_bound}


def score(bars, kerf=KERF, trim=TRIM):
    """Totals for a list of bars. All lengths in mm."""
    by_stock = Counter(L for L, _ in bars)
    purchased = sum(L for L, _ in bars)
    net = sum(sum(ps) for _, ps in bars)
    pieces = sum(len(ps) for _, ps in bars)
    kerf_mm = pieces * kerf
    trim_mm = len(bars) * trim
    offcut = purchased - net - kerf_mm - trim_mm
    return {
        "bars": len(bars),
        "bars_by_stock": {str(k): by_stock[k] for k in sorted(by_stock)},
        "pieces": pieces,
        "purchased_mm": purchased,
        "net_mm": net,
        "kerf_mm": kerf_mm,
        "trim_mm": trim_mm,
        "offcut_mm": offcut,
        "yield_pct": round(100.0 * net / purchased, 2) if purchased else 0.0,
    }


def validate(bars, demand, stock=STOCK, kerf=KERF, trim=TRIM):
    """Raise unless bars are feasible stock lengths and cut exactly the demand."""
    got = Counter()
    for L, ps in bars:
        if L not in stock:
            raise ValueError("bar length %r not in stock" % L)
        if not fits(ps, L, kerf, trim):
            raise ValueError("pattern %r overfills %d mm bar" % (ps, L))
        got.update(ps)
    want = Counter({l: q for l, q in demand.items() if q})
    if got != want:
        raise ValueError("cut %r != demand %r" % (dict(got), dict(want)))


def group_patterns(bars):
    """[(L, pieces, qty)] in a stable order for cutting sheets."""
    c = Counter(bars)
    return sorted(((L, ps, q) for (L, ps), q in c.items()), key=lambda r: (-r[2], -r[0], r[1]))
