"""Independent checks on the committed outputs.

These deliberately do *not* call the generators in ``fsd.drawings`` /
``fsd.members``. Expected values come straight from the upstream facade-bim
files: panel sizes and per-panel areas / frame masses in ``panels.csv``, type
totals in ``takeoff.csv`` and constants in ``config.py.txt``.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf

from . import upstream

REQUIRED_LAYERS = {"BORDER", "TITLE", "FRAME", "GLAZING", "INFILL", "DIMS", "TEXT",
                   "SECTION", "CUTLINE", "SCHEDULE"}
REQUIRED_BLOCKS = {"FSD_TITLE", "FSD_MULLION", "FSD_TRANSOM"}
ELEV, SECT = 20, 5
AREA_COLS = ("vision_igu_m2", "spandrel_m2", "louver_m2", "door_glass_m2")


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def expected_types():
    """{type: dict(w, h, qty, n_horizontal, fill_areas)} from upstream data only."""
    c = upstream.config()
    out = {}
    for p in upstream.panels():
        t = p["type"]
        w, h = p["w_mm"], p["h_mm"]
        net = w - 2 * c["MULLION_W"]
        mull = 2 * h / 1000.0 * c["MULLION_KG_M"]
        n_h = (p["frame_alu_kg"] - mull) / (net / 1000.0 * c["TRANSOM_KG_M"])
        if abs(n_h - round(n_h)) > 1e-3:
            raise ValueError("%s: frame mass does not invert to whole members" % p["pid"])
        areas = sorted(float(p[k]) for k in AREA_COLS if float(p[k]) > 0)
        rec = {"w": w, "h": h, "net": net, "n_h": int(round(n_h)), "areas": areas}
        if t in out:
            if {k: out[t][k] for k in rec} != rec:
                raise ValueError("type %s is not uniform" % t)
            out[t]["qty"] += 1
        else:
            out[t] = dict(rec, qty=1)
    return out


def _dims(msp):
    out = []
    for d in msp.query("DIMENSION"):
        lfac = d.get_dim_style().dxf.get("dimlfac", 1.0)
        ov = d.override()
        lfac = ov.get("dimlfac", lfac)
        out.append((round(d.get_measurement() * lfac, 3), lfac, d))
    return out


def check_drawing(path, ptype, exp, c):
    """Return a list of failure strings (empty = pass)."""
    fails = []
    doc = ezdxf.readfile(path)
    aud = doc.audit()
    if aud.has_errors:
        fails.append("audit errors: %d" % len(aud.errors))
    layers = {l.dxf.name for l in doc.layers}
    if not REQUIRED_LAYERS <= layers:
        fails.append("missing layers %s" % sorted(REQUIRED_LAYERS - layers))
    blocks = {b.name for b in doc.blocks}
    need = REQUIRED_BLOCKS | {"FSD_PANEL_%s" % ptype}
    if not need <= blocks:
        fails.append("missing blocks %s" % sorted(need - blocks))
        return fails
    msp = doc.modelspace()
    mw, jt, dep, th = c["MULLION_W"], c["JOINT"], c["DEPTH"], c["TRANSOM_H"]

    # --- dimensions -------------------------------------------------------
    dims = _dims(msp)
    faked = [d.dxf.get("text", "") for _, _, d in dims if d.dxf.get("text", "") not in ("", "<>")]
    if faked:
        fails.append("dimension text overridden: %s" % faked)
    if any(d[2].dxf.layer != "DIMS" for d in dims):
        fails.append("dimension not on DIMS layer")
    elev = [v for v, f, _ in dims if f == ELEV]
    sect = sorted(v for v, f, _ in dims if f == SECT)
    if len(elev) + len(sect) != len(dims):
        fails.append("dimension with unexpected DIMLFAC")
    if sect != sorted([mw, jt, mw, dep, th, jt, th, dep]):
        fails.append("section dims %s" % sect)
    rest = Counter(elev)
    for v in (exp["w"], exp["net"], mw, exp["h"]):
        if rest[v] < 1:
            fails.append("elevation lacks %s" % v)
        rest[v] -= 1
    chain = sorted(rest.elements())
    if sum(chain) != exp["h"]:
        fails.append("zone chain %s sums to %s, not h=%s" % (chain, sum(chain), exp["h"]))
    if chain.count(th) != exp["n_h"]:
        fails.append("chain has %d transoms, upstream frame mass implies %d" % (chain.count(th), exp["n_h"]))
    fill = sorted(round(z * exp["net"] / 1e6, 3) for z in chain if z != th)
    if len(fill) != len(exp["areas"]) or any(abs(a - b) > 6e-4 for a, b in zip(fill, exp["areas"])):
        fails.append("fill zones give areas %s, upstream %s" % (fill, exp["areas"]))

    # --- panel block geometry (1:1) --------------------------------------
    rects = []
    for e in doc.blocks.get("FSD_PANEL_%s" % ptype).query("LWPOLYLINE[layer=='FRAME']"):
        xs = [p[0] for p in e.get_points()]
        ys = [p[1] for p in e.get_points()]
        rects.append((round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), min(xs), min(ys)))
    sizes = Counter((a, b) for a, b, _, _ in rects)
    want = Counter({(mw, exp["h"]): 2, (exp["net"], th): exp["n_h"]})
    if sizes != want:
        fails.append("panel block frame members %s != %s" % (dict(sizes), dict(want)))
    xs = [x for _, _, x, _ in rects] + [x + a for a, _, x, _ in rects]
    ys = [y for _, _, _, y in rects] + [y + b for _, b, _, y in rects]
    if (min(xs), max(xs), min(ys), max(ys)) != (0, exp["w"], 0, exp["h"]):
        fails.append("panel block extents wrong")

    # overall width / height dims must sit on the inserted panel's edges
    ins = [i for i in msp.query("INSERT") if i.dxf.name == "FSD_PANEL_%s" % ptype]
    if len(ins) != 1 or abs(ins[0].dxf.xscale - 1.0 / ELEV) > 1e-12:
        fails.append("panel elevation not inserted once at 1:%d" % ELEV)
    else:
        x0, y0 = ins[0].dxf.insert.x, ins[0].dxf.insert.y
        s = 1.0 / ELEV
        edges = set()
        for v, f, d in dims:
            if f == ELEV and v in (exp["w"], exp["h"]):
                p1, p2 = d.dxf.defpoint2, d.dxf.defpoint3
                edges.add((v, round(min(p1.x, p2.x) - x0, 6), round(min(p1.y, p2.y) - y0, 6),
                           round(max(p1.x, p2.x) - x0, 6), round(max(p1.y, p2.y) - y0, 6)))
        if (exp["w"], 0, 0, round(exp["w"] * s, 6), 0) not in edges:
            fails.append("width dimension not on panel edge")
        if (exp["h"], 0, 0, 0, round(exp["h"] * s, 6)) not in edges:
            fails.append("height dimension not on panel edge")

    # --- section views: profile blocks at 1:5, spaced by the joint ----------
    s5 = 1.0 / SECT
    for name, gap, axis, size in (("FSD_MULLION", mw + jt, "x", (mw, dep)),
                                  ("FSD_TRANSOM", th + jt, "y", (dep, th))):
        pts = [p for e in doc.blocks.get(name).query("LWPOLYLINE") for p in e.get_points()]
        ext = (round(max(p[0] for p in pts) - min(p[0] for p in pts), 6),
               round(max(p[1] for p in pts) - min(p[1] for p in pts), 6))
        if ext != size:
            fails.append("%s block is %s, expected %s" % (name, ext, size))
        refs = [i for i in msp.query("INSERT") if i.dxf.name == name]
        if len(refs) != 2 or any(abs(i.dxf.xscale - s5) > 1e-12 or abs(i.dxf.yscale - s5) > 1e-12
                                 for i in refs):
            fails.append("%s not inserted twice at 1:%d" % (name, SECT))
            continue
        a, b = sorted(getattr(i.dxf.insert, axis) for i in refs)
        if abs((b - a) - gap * s5) > 1e-9:
            fails.append("%s spacing %.3f != %.3f" % (name, (b - a) / s5, gap))

    # --- title block ------------------------------------------------------
    tb = [i for i in msp.query("INSERT") if i.dxf.name == "FSD_TITLE"]
    if len(tb) != 1:
        fails.append("title block count %d" % len(tb))
    else:
        a = {x.dxf.tag: x.dxf.text for x in tb[0].attribs}
        if a.get("DWG_NO") != "FSD-SD-%d" % (100 + int(ptype[1:])):
            fails.append("DWG_NO %r" % a.get("DWG_NO"))
        if a.get("TYPE") != ptype or a.get("QTY") != "%d No." % exp["qty"]:
            fails.append("TYPE/QTY %r %r" % (a.get("TYPE"), a.get("QTY")))
        if "1:%d" % ELEV not in a.get("SCALE", "") or "1:%d" % SECT not in a.get("SCALE", ""):
            fails.append("SCALE %r" % a.get("SCALE"))
        if not re.fullmatch(r"P\d+|[A-Z]", a.get("REV", "")):
            fails.append("REV %r" % a.get("REV"))
        if "NOT FOR CONSTRUCTION" not in a.get("STATUS", ""):
            fails.append("STATUS %r" % a.get("STATUS"))

    # --- member schedule text ---------------------------------------------
    sched = {}
    for t in msp.query("TEXT[layer=='SCHEDULE']"):
        m = re.fullmatch(r"(\S+)\s+L=(\d+)\s+(\d+)/panel\s+(\d+) total", t.dxf.text)
        if m:
            sched[m.group(1)] = tuple(int(g) for g in m.groups()[1:])
    q = exp["qty"]
    n_mid = exp["n_h"] - 2
    want = {"MUL-L": (exp["h"], 1, q), "MUL-R": (exp["h"], 1, q),
            "SILL": (exp["net"], 1, q), "HEAD": (exp["net"], 1, q)}
    if n_mid:
        want["TRANSOM"] = (exp["net"], n_mid, n_mid * q)
    if sched != want:
        fails.append("schedule %s != %s" % (sched, want))
    return fails


def check_drawings(out):
    c = upstream.config()
    exp = expected_types()
    reg = _read_csv(out / "drawing_register.csv")
    fails = []
    if sorted(r["panel_type"] for r in reg) != sorted(exp):
        fails.append("register types %s" % [r["panel_type"] for r in reg])
    if sum(int(r["panels"]) for r in reg) != sum(e["qty"] for e in exp.values()):
        fails.append("register panel count")
    for r in reg:
        if int(r["panels"]) != exp[r["panel_type"]]["qty"]:
            fails.append("register qty %s" % r["drawing_no"])
        f = check_drawing(out / r["file"], r["panel_type"], exp[r["panel_type"]], c)
        fails += ["%s: %s" % (r["drawing_no"], x) for x in f]
    return fails


def check_members(out):
    """members.csv reconciles with upstream per-panel and per-type frame mass."""
    c = upstream.config()
    rows = _read_csv(out / "members.csv")
    fails = []
    kg_panel, kg_type = defaultdict(float), defaultdict(float)
    for r in rows:
        lm = c["MULLION_KG_M"] if r["profile"].startswith("MUL") else c["TRANSOM_KG_M"]
        kg = int(r["length_mm"]) / 1000.0 * lm
        kg_panel[r["pid"]] += kg
        kg_type[r["type"]] += kg
    panels = upstream.panels()
    if set(kg_panel) != {p["pid"] for p in panels}:
        fails.append("members.csv does not cover exactly the upstream panels")
    for p in panels:
        if abs(kg_panel[p["pid"]] - p["frame_alu_kg"]) > 5e-4:
            fails.append("%s frame %.3f != upstream %.3f" % (p["pid"], kg_panel[p["pid"]], p["frame_alu_kg"]))
    for t, r in upstream.takeoff().items():
        if t in kg_type and abs(kg_type[t] - float(r["frame_alu_kg"])) > 5e-3:
            fails.append("type %s frame %.2f != take-off %s" % (t, kg_type[t], r["frame_alu_kg"]))
    total = float(upstream.takeoff()["合计"]["frame_alu_kg"])
    if abs(sum(kg_type.values()) - total) > 5e-3:
        fails.append("total frame %.2f != take-off %.2f" % (sum(kg_type.values()), total))
    if len({r["mark"] for r in rows}) != len(rows):
        fails.append("duplicate member marks")
    return fails


def check_cutting(out, kerf, trim, stock):
    """Each plan cuts every member exactly once, from feasible bars, and its
    totals match summary.csv; the pooled ILP optimum is re-solved."""
    from . import cutting as X
    members = {r["mark"]: r for r in _read_csv(out / "members.csv")}
    summ = _read_csv(out / "cutting" / "summary.csv")
    fails = []
    plans = {"ALL": "plan_pooled.csv"}
    plans.update({t: "plan_%s.csv" % t for t in sorted({m["type"] for m in members.values()})})
    for batch, name in plans.items():
        cuts = _read_csv(out / "cutting" / name)
        want = {k for k, m in members.items() if batch == "ALL" or m["type"] == batch}
        marks = [r["mark"] for r in cuts]
        if len(marks) != len(set(marks)) or set(marks) != want:
            fails.append("%s: cut marks do not match members exactly once" % name)
        bars = defaultdict(list)
        for r in cuts:
            m = members.get(r["mark"])
            if m is None or m["profile"] != r["profile"] or m["length_mm"] != r["length_mm"]:
                fails.append("%s: %s length/profile mismatch" % (name, r["mark"]))
                continue
            bars[(r["profile"], int(r["bar"]))].append((int(r["stock_mm"]), int(r["length_mm"]),
                                                        int(r["bar_offcut_mm"])))
        for prof in sorted({p for p, _ in bars}):
            pb = {b: v for (p, b), v in bars.items() if p == prof}
            purchased = net = 0
            for b, v in pb.items():
                L = v[0][0]
                if L not in stock or any(x[0] != L for x in v):
                    fails.append("%s %s bar %d: bad stock" % (name, prof, b))
                used = sum(x[1] + kerf for x in v)
                if used > L - trim:
                    fails.append("%s %s bar %d overfilled" % (name, prof, b))
                if any(x[2] != L - trim - used for x in v):
                    fails.append("%s %s bar %d offcut wrong" % (name, prof, b))
                purchased += L
                net += sum(x[1] for x in v)
            row = [r for r in summ if r["batch"] == batch and r["profile"] == prof and r["method"] == "ILP"]
            if len(row) != 1 or int(row[0]["purchased_mm"]) != purchased or \
                    int(row[0]["net_mm"]) != net or int(row[0]["bars"]) != len(pb):
                fails.append("%s %s: plan totals differ from summary.csv" % (name, prof))
            if batch == "ALL":
                d = Counter(int(members[m]["length_mm"]) for m in want if members[m]["profile"] == prof)
                opt = X.score(X.ilp(d, stock, kerf, trim)[0])["purchased_mm"]
                ffd = X.score(X.ffd(d, stock, kerf, trim))["purchased_mm"]
                frow = [r for r in summ if r["batch"] == "ALL" and r["profile"] == prof and r["method"] == "FFD"]
                if opt != purchased:
                    fails.append("pooled %s: committed %d != re-solved optimum %d" % (prof, purchased, opt))
                if len(frow) != 1 or int(frow[0]["purchased_mm"]) != ffd:
                    fails.append("pooled %s: FFD total differs on re-run" % prof)
    for r in summ:
        p = int(r["purchased_mm"])
        if int(r["net_mm"]) + int(r["kerf_mm"]) + int(r["trim_mm"]) + int(r["offcut_mm"]) != p:
            fails.append("summary row %s/%s/%s does not balance" % (r["batch"], r["profile"], r["method"]))
        if int(r["bars_6000"]) * 6000 + int(r["bars_6500"]) * 6500 != p:
            fails.append("summary row %s/%s/%s bar mix != purchased" % (r["batch"], r["profile"], r["method"]))
    net_all = sum(int(r["net_mm"]) for r in summ if r["batch"] == "ALL" and r["method"] == "ILP")
    if net_all != sum(int(m["length_mm"]) for m in members.values()):
        fails.append("pooled net length != members.csv total")
    return fails


def run_all(out):
    from . import cutting as X
    out = Path(out)
    upstream.verify_source()
    res = {"drawings": check_drawings(out), "members": check_members(out),
           "cutting": check_cutting(out, X.KERF, X.TRIM, X.STOCK)}
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    if s["source_commit"] != upstream.verify_source()["commit"]:
        res["members"].append("summary.json source commit stale")
    return res
