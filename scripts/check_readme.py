"""Recompute every number quoted in README.md from the committed outputs.

Two rules, both must hold:

1. Every table and headline fact below, formatted from ``out/``, appears
   verbatim in the README.
2. Every number token in the README (outside code blocks and links) is either
   one of those recomputed values or a declared *input* (upstream config
   constant, stock length, kerf, trim, view scale, drawing number).

    python scripts/check_readme.py           # check
    python scripts/check_readme.py --print   # print the generated blocks
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ezdxf  # noqa: E402

from fsd import cutting as X  # noqa: E402
from fsd import drawings as D  # noqa: E402
from fsd import upstream as U  # noqa: E402

OUT = ROOT / "out"


def rd(p):
    with open(OUT / p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def n(v, dp=0):
    return "{:,.{}f}".format(v, dp)


def m(mm):
    return n(mm / 1000.0, 2)


def blocks_and_facts():
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    summ = rd("cutting/summary.csv")
    sens = rd("cutting/stock_sensitivity.csv")
    members = rd("members.csv")
    reg = rd("drawing_register.csv")
    pooled = rd("cutting/plan_pooled.csv")

    # panel type table
    per_panel = Counter((r["type"], r["pid"]) for r in members)
    mem_per = {t: per_panel[(t, pid)] for t, pid in per_panel}
    sizes = {}
    for r in members:
        if r["profile"] == "MUL-L":
            sizes.setdefault(r["type"], int(r["length_mm"]))
    rows = ["| Type | Name | Panels | Size W x H (mm) | Members per panel | Drawing |",
            "|---|---|---|---|---|---|"]
    w = {p["type"]: p["w_mm"] for p in U.panels()}
    for g in reg:
        t = g["panel_type"]
        rows.append("| %s | %s | %s | %s x %s | %d | %s |" % (
            t, U.TYPE_NAMES[t], n(int(g["panels"])), n(w[t]), n(sizes[t]), mem_per[t], g["drawing_no"]))
    t_types = "\n".join(rows)

    # pooled by profile
    rows = ["| Profile | Pieces | Bars | Purchased (m) | Yield | FFD vs optimum |",
            "|---|---|---|---|---|---|"]
    for r in summ:
        if r["batch"] == "ALL" and r["method"] == "ILP":
            f = [x for x in summ if x["batch"] == "ALL" and x["profile"] == r["profile"]
                 and x["method"] == "FFD"][0]
            rows.append("| %s | %s | %s | %s | %s%% | +%s%% |" % (
                r["profile"], n(int(r["pieces"])), n(int(r["bars"])), m(int(r["purchased_mm"])),
                r["yield_pct"], f["gap_vs_ilp_pct"]))
    p, pf = s["pooled_ilp"], s["pooled_ffd"]
    gap_all = 100.0 * (pf["purchased_mm"] - p["purchased_mm"]) / p["purchased_mm"]
    rows.append("| **Total** | **%s** | **%s** | **%s** | **%s%%** | **+%.2f%%** |" % (
        n(p["pieces"]), n(p["bars"]), m(p["purchased_mm"]), "%.2f" % p["yield_pct"], gap_all))
    t_pooled = "\n".join(rows)

    # sensitivity
    rows = ["| Stock lengths (mm) | Optimal bars | Optimal purchase (m) | Optimal yield | FFD bars | FFD purchase (m) | FFD vs optimum |",
            "|---|---|---|---|---|---|---|"]
    for r in sens:
        label = " / ".join(n(int(x)) for x in r["stock_mm"].split("/"))
        rows.append("| %s | %s | %s | %s%% | %s | %s | +%s%% |" % (
            label, n(int(r["ilp_bars"])), m(int(r["ilp_purchased_mm"])), r["ilp_yield_pct"],
            n(int(r["ffd_bars"])), m(int(r["ffd_purchased_mm"])), r["ffd_gap_pct"]))
    t_sens = "\n".join(rows)

    dims = sum(len(ezdxf.readfile(OUT / g["file"]).modelspace().query("DIMENSION")) for g in reg)
    typical_off = Counter(int(r["bar_offcut_mm"]) for r in pooled
                          if r["profile"] == "MUL-L" and r["length_mm"] == "3880"
                          and sum(1 for q in pooled if q["profile"] == "MUL-L" and q["bar"] == r["bar"]) == 1)
    bt = s["by_type_ilp"]
    mull_y = [r["yield_pct"] for r in summ if r["batch"] == "ALL" and r["method"] == "ILP"
              and r["profile"].startswith("MUL")]
    hor_y = sorted(float(r["yield_pct"]) for r in summ if r["batch"] == "ALL" and r["method"] == "ILP"
                   and not r["profile"].startswith("MUL"))
    hor = [r for r in pooled if r["profile"] == "SILL"]
    hor_len = int(hor[0]["length_mm"])
    hor_per_bar = Counter(Counter(r["bar"] for r in hor).values()).most_common(1)[0][0]
    s7 = [r for r in sens if r["stock_mm"].count("/") == 2][0]
    base = [r for r in sens if r["stock_mm"] == "6000/6500"][0]
    from mutation_check import MUTANTS
    facts = {
        "panels": "%s panels" % n(s["panels"]),
        "types": "%d panel types" % s["panel_types"],
        "members": "%s members" % n(s["members"]),
        "drawings": "%d A3 shop drawings" % s["drawings"],
        "dims": "%d dimensions" % dims,
        "frame": "%s kg" % n(s["frame_alu_kg"], 2),
        "pooled": "%s bars of %s mm" % (n(p["bars"]), n(6000)),
        "purchased": "%s m purchased" % m(p["purchased_mm"]),
        "net": "%s m of members" % m(p["net_mm"]),
        "yield": "yield %.2f%%" % p["yield_pct"],
        "offcut": "offcut %s m" % m(p["offcut_mm"]),
        "kerf": "kerf %s m" % m(p["kerf_mm"]),
        "trim": "end trim %s m" % m(p["trim_mm"]),
        "b6500": "%d of %s mm" % (p["bars_6500"], n(6500)),
        "inst": "all %d instances" % s["instances"],
        "inst_ok": "%d of %d" % (s["instances_ffd_optimal"], s["instances"]),
        "typ_off": "%s mm offcut" % n(typical_off.most_common(1)[0][0]),
        "mull_y": "mullions yield %s%%" % mull_y[0],
        "hor_y": "%.2f-%.2f%%" % (hor_y[0], hor_y[-1]),
        "bytype": "%s bars (%s m)" % (n(bt["bars"]), m(bt["purchased_mm"])),
        "saving": "saves %d bars (%s m)" % (bt["bars"] - p["bars"], m(bt["purchased_mm"] - p["purchased_mm"])),
        "s7_gap": "+%s%%" % s7["ffd_gap_pct"],
        "s7_save": "%.1f%% less aluminium" % (100.0 * (1 - int(s7["ilp_purchased_mm"]) / int(base["ilp_purchased_mm"]))),
        "mutants": "%d planted bugs" % len(MUTANTS),
        "batches": "%d profile batches by panel type" % sum(1 for r in summ if r["batch"] != "ALL"
                                                            and r["method"] == "ILP"),
        "hor_len": "(%s mm, %s to a bar)" % (n(hor_len), WORDS[hor_per_bar]),
    }
    inputs = set()
    c = U.config()
    for v in list(c.values()) + list(X.STOCK) + [X.KERF, X.TRIM, D.ELEV_SCALE, D.SECT_SCALE,
                                                  7800, 3880 + 3880, 2 * (3880 + X.KERF) + X.TRIM]:
        inputs |= {str(v), n(v) if isinstance(v, int) else str(v)}
    inputs |= {g["drawing_no"].split("-")[-1] for g in reg}
    inputs |= {s["source_commit"][:7], "3.11", "1", "8"}
    # "3.11" = Python version; "1" from the scale notation 1:20 / 1:5; "8" = storeys of facade-bim's block
    return {"types": t_types, "pooled": t_pooled, "sens": t_sens}, facts, inputs


WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
NUM = re.compile(r"(?<![\w.\-])\d[\d,]*(?:\.\d+)?(?![\w])")


def prose(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def check(readme):
    blocks, facts, inputs = blocks_and_facts()
    bad = []
    for k, v in list(blocks.items()) + list(facts.items()):
        if v not in readme:
            bad.append("missing %s: %r" % (k, v))
    allowed = set(inputs)
    for v in list(blocks.values()) + list(facts.values()):
        allowed |= set(NUM.findall(v.replace("**", " ")))
    for tok in NUM.findall(prose(readme).replace("**", " ")):
        t = tok.rstrip(",")
        if t not in allowed:
            bad.append("number %r in README is not recomputed or a declared input" % t)
    return bad, len(facts), len(blocks)


def main():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "--print" in sys.argv:
        blocks, facts, _ = blocks_and_facts()
        for k, v in blocks.items():
            print("<!-- %s -->\n%s\n" % (k, v))
        for k, v in facts.items():
            print("%-9s %s" % (k, v))
        return 0
    bad, nf, nb = check(readme)
    for b in bad:
        print("FAIL", b)
    print("README check: %s (%d facts, %d tables)" % ("FAIL" if bad else "PASS", nf, nb))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
