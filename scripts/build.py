"""Build every output from the pinned facade-bim inputs.

    python scripts/build.py            # writes out/
    python scripts/build.py --out DIR  # writes elsewhere (used by CI to diff)
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fsd import cutting as X  # noqa: E402
from fsd import drawings as D  # noqa: E402
from fsd import members as M  # noqa: E402
from fsd import render as R  # noqa: E402
from fsd import upstream as U  # noqa: E402

# Stock-length sensitivity. 7800 is hypothetical (= the shortest bar that holds
# two 3880 mm mullions plus kerf and trim); availability was not checked.
SENSITIVITY = [(6000,), (6500,), (6000, 6500), (6000, 6500, 7800)]


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def assign_marks(bars, rows, profile, ptype=None):
    """Give every cut piece a member mark, in panel sequence order."""
    queue = {}
    for r in rows:
        if r["profile"] == profile and (ptype is None or r["type"] == ptype):
            queue.setdefault(r["length_mm"], []).append(r["mark"])
    for q in queue.values():
        q.reverse()
    out = []
    for b, (L, pieces) in enumerate(bars, 1):
        off = L - X.TRIM - sum(pieces) - X.KERF * len(pieces)
        for k, p in enumerate(pieces, 1):
            out.append({"profile": profile, "bar": b, "stock_mm": L, "cut": k,
                        "length_mm": p, "mark": queue[p].pop(), "bar_offcut_mm": off})
    return out


def plan_batch(rows, batch, ptype, stock=X.STOCK):
    """FFD and ILP for every profile in one batch (one panel type or pooled)."""
    summary, cuts, groups = [], [], []
    for prof in M.PROFILES:
        d = M.demand(rows, prof, ptype)
        if not d:
            continue
        f_bars = X.ffd(d, stock)
        o_bars, info = X.ilp(d, stock)
        X.validate(f_bars, d, stock)
        X.validate(o_bars, d, stock)
        fs, os_ = X.score(f_bars), X.score(o_bars)
        for method, s in (("FFD", fs), ("ILP", os_)):
            summary.append({
                "batch": batch, "profile": prof, "method": method,
                "pieces": s["pieces"], "bars": s["bars"],
                "bars_6000": s["bars_by_stock"].get("6000", 0),
                "bars_6500": s["bars_by_stock"].get("6500", 0),
                "purchased_mm": s["purchased_mm"], "net_mm": s["net_mm"],
                "kerf_mm": s["kerf_mm"], "trim_mm": s["trim_mm"], "offcut_mm": s["offcut_mm"],
                "yield_pct": "%.2f" % s["yield_pct"],
                "gap_vs_ilp_pct": "%.2f" % (100.0 * (s["purchased_mm"] - os_["purchased_mm"])
                                             / os_["purchased_mm"]),
                "solver_status": info["status"] if method == "ILP" else "",
                "solver_mip_gap": "%.6f" % info["mip_gap"] if method == "ILP" else "",
            })
        expanded = [(L, ps) for L, ps, q in X.group_patterns(o_bars) for _ in range(q)]
        cuts.extend(assign_marks(expanded, rows, prof, ptype))
        groups.extend((prof, L, ps, q) for L, ps, q in X.group_patterns(o_bars))
    return summary, cuts, groups


def totals(summary, batch, method):
    sel = [r for r in summary if r["batch"] == batch and r["method"] == method]
    out = {k: sum(int(r[k]) for r in sel) for k in
           ("pieces", "bars", "bars_6000", "bars_6500", "purchased_mm", "net_mm",
            "kerf_mm", "trim_mm", "offcut_mm")}
    out["yield_pct"] = round(100.0 * out["net_mm"] / out["purchased_mm"], 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    src = U.verify_source()
    panels, c = U.panels(), U.config()
    rows = M.member_rows(panels, c)
    write_csv(out / "members.csv", rows, ["mark", "pid", "type", "profile", "length_mm", "z_mm"])

    # drawings
    reg = D.build_all(out / "drawings", panels)
    write_csv(out / "drawing_register.csv", reg, list(reg[0].keys()))

    # cutting
    types = list(M.panel_types(panels))
    summary, sheets = [], []
    p_sum, p_cuts, p_groups = plan_batch(rows, "ALL", None)
    summary += p_sum
    write_csv(out / "cutting" / "plan_pooled.csv", p_cuts, list(p_cuts[0].keys()))
    for t in types:
        s, cuts, groups = plan_batch(rows, t, t)
        summary += s
        write_csv(out / "cutting" / ("plan_%s.csv" % t), cuts, list(cuts[0].keys()))
        sheets.append(("Cutting sheet - panel type %s (%s)" % (t, U.TYPE_NAMES[t]),
                       "Batch = all %s panels. Stock %s mm, kerf %d mm, end trim %d mm. "
                       "Optimal plan (HiGHS). Indicative - not for production."
                       % (t, " / ".join(map(str, X.STOCK)), X.KERF, X.TRIM), groups))
    sheets.append(("Cutting sheet - whole job pooled",
                   "All 810 panels in one batch per profile. Optimal plan (HiGHS).", p_groups))
    write_csv(out / "cutting" / "summary.csv", summary, list(summary[0].keys()))

    sens = []
    for stock in SENSITIVITY:
        acc = {"FFD": [0, 0, 0], "ILP": [0, 0, 0]}
        for prof in M.PROFILES:
            d = M.demand(rows, prof)
            for method, bars in (("FFD", X.ffd(d, stock)), ("ILP", X.ilp(d, stock)[0])):
                X.validate(bars, d, stock)
                s = X.score(bars)
                acc[method][0] += s["bars"]
                acc[method][1] += s["purchased_mm"]
                acc[method][2] += s["net_mm"]
        sens.append({
            "stock_mm": "/".join(map(str, stock)),
            "ffd_bars": acc["FFD"][0], "ffd_purchased_mm": acc["FFD"][1],
            "ilp_bars": acc["ILP"][0], "ilp_purchased_mm": acc["ILP"][1],
            "ilp_yield_pct": "%.2f" % (100.0 * acc["ILP"][2] / acc["ILP"][1]),
            "ffd_gap_pct": "%.2f" % (100.0 * (acc["FFD"][1] - acc["ILP"][1]) / acc["ILP"][1]),
        })
    write_csv(out / "cutting" / "stock_sensitivity.csv", sens, list(sens[0].keys()))

    by_type = {k: sum(totals(summary, t, "ILP")[k] for t in types)
               for k in ("bars", "purchased_mm", "net_mm", "offcut_mm")}
    kg = M.frame_kg(rows, c)
    result = {
        "source_commit": src["commit"],
        "panels": len(panels),
        "panel_types": len(types),
        "members": len(rows),
        "frame_alu_kg": round(sum(kg.values()), 2),
        "drawings": len(reg),
        "stock_mm": list(X.STOCK), "kerf_mm": X.KERF, "trim_mm": X.TRIM,
        "pooled_ilp": totals(summary, "ALL", "ILP"),
        "pooled_ffd": totals(summary, "ALL", "FFD"),
        "by_type_ilp": by_type,
        "instances": sum(1 for r in summary if r["method"] == "ILP"),
        "instances_ffd_optimal": sum(1 for r in summary if r["method"] == "FFD"
                                     and float(r["gap_vs_ilp_pct"]) == 0.0),
    }
    (out / "summary.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")

    if not args.no_pdf:
        img = ROOT / "docs" / "img"
        img.mkdir(parents=True, exist_ok=True)
        R.shop_pdf([out / r["file"] for r in reg], out / "drawings" / "shop_drawings.pdf",
                   preview=(3, img / "FSD-SD-104.png"))
        R.cutting_pdf(sheets, out / "cutting" / "cutting_sheets.pdf", X.KERF, X.TRIM,
                      preview=(len(sheets) - 1, img / "cutting_pooled.png"))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
