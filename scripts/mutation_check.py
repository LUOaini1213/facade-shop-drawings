"""Mutation check: plant one deliberate bug at a time; the test suite must fail.

Each mutant is an exact source substitution that must match exactly once.
Every mutant runs in its own temporary copy of the repository, so the working
tree is never modified. Exit 1 if any mutant survives (tests still pass).

    python scripts/mutation_check.py            # all mutants, 4 in parallel
    python scripts/mutation_check.py --jobs 1
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (id, file, original, mutated, what the bug means)
MUTANTS = [
    ("M01", "fsd/members.py", 'prof = "SILL" if i == idx[0]', 'prof = "SILL" if i == idx[-1]',
     "sill and head swapped"),
    ("M02", "fsd/members.py", "out.append((prof, w - 2 * mw, z))", "out.append((prof, w - mw, z))",
     "transom cut length ignores one mullion"),
    ("M03", "fsd/members.py", 'vision = h - 4 * t - c["DOOR_LEAF_H"]', 'vision = h - 3 * t - c["DOOR_LEAF_H"]',
     "door unit zone stack miscounts transoms"),
    ("M04", "fsd/members.py", 'out = [("MUL-L", h, 0), ("MUL-R", h, 0)]',
     'out = [("MUL-L", h, 0), ("MUL-R", h - 1, 0)]', "right mullion 1 mm short"),
    ("M05", "fsd/cutting.py", "return sum(p + kerf for p in pieces) <= capacity(L, trim)",
     "return sum(p + kerf for p in pieces) < capacity(L, trim)", "exact-fit bar rejected"),
    ("M06", "fsd/cutting.py", "    return L - trim\n", "    return L - trim // 2\n",
     "only one end trimmed"),
    ("M07", "fsd/cutting.py", "L = min(s for s in stock if used <= capacity(s, trim))",
     "L = max(s for s in stock if used <= capacity(s, trim))", "FFD never shrinks bars"),
    ("M08", "fsd/cutting.py", "kerf_mm = pieces * kerf", "kerf_mm = (pieces - 1) * kerf",
     "kerf loss undercounted"),
    ("M09", "fsd/cutting.py", "h.addRow(float(demand[l]), float(demand[l]),",
     "h.addRow(0.0, float(demand[l]),", "ILP demand rows relaxed"),
    ("M10", "fsd/cutting.py", "for l, q in demand.items() for _ in range(q)), reverse=True)",
     "for l, q in demand.items() for _ in range(q)), reverse=False)", "first-fit increasing"),
    ("M11", "fsd/drawings.py", "ELEV_SCALE = 20", "ELEV_SCALE = 25", "elevation scale changed"),
    ("M12", "fsd/drawings.py", "_dim(msp, (ex + mw * s, top), (ex + (w - mw) * s, top)",
     "_dim(msp, (ex + mw * s, top), (ex + (w - 2 * mw) * s, top)", "daylight dimension wrong"),
    ("M13", "fsd/drawings.py", 'msp.add_blockref("FSD_MULLION", (ax + (mw + jt) * s5, ay),',
     'msp.add_blockref("FSD_MULLION", (ax + (mw + jt + 5) * s5, ay),', "section A joint drawn 25 mm"),
    ("M14", "fsd/drawings.py", '"%-8s L=%d  %d/panel  %d total" % (prof, length, n, n * qty)',
     '"%-8s L=%d  %d/panel  %d total" % (prof, length, n, n * (qty + 1))', "schedule total off by one panel"),
    ("M15", "fsd/drawings.py", '_rect(b, mw, z, mw + length, z + c["TRANSOM_H"], "FRAME")',
     '_rect(b, mw, z, mw + length, z + c["TRANSOM_H"] + 10, "FRAME")', "transom drawn 90 mm high"),
    ("M16", "fsd/drawings.py", '"TYPE": ptype, "QTY": "%d No." % qty,',
     '"TYPE": ptype, "QTY": "%d No." % (qty * 2),', "title block quantity wrong"),
    ("M17", "fsd/checks.py", 'if abs(kg_panel[p["pid"]] - p["frame_alu_kg"]) > 5e-4:',
     'if abs(kg_panel[p["pid"]] - p["frame_alu_kg"]) > 5e9:', "per-panel reconciliation disabled"),
    ("M18", "fsd/checks.py", '"SECTION", "CUTLINE", "SCHEDULE"}', '"SECTION", "SCHEDULE"}',
     "layer requirement dropped"),
    ("M19", "fsd/checks.py", 'if faked:', 'if faked and False:', "dimension text override ignored"),
    ("M20", "fsd/upstream.py", "if got != digest:", "if got == digest:", "hash pin inverted"),
    ("M21", "scripts/build.py", '"ffd_gap_pct": "%.2f" % (100.0 * (acc["FFD"][1] - acc["ILP"][1]) / acc["ILP"][1]),',
     '"ffd_gap_pct": "%.2f" % (100.0 * (acc["FFD"][1] - acc["ILP"][1]) / acc["FFD"][1]),',
     "gap measured against the wrong base"),
]

IGNORE = shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pdf", "*.png")


def run(mutant):
    """mutant=None runs the unmutated baseline, which must pass."""
    if mutant is None:
        mutant = ("BASE", None, None, None, "")
    mid, rel, old, new, _ = mutant
    with tempfile.TemporaryDirectory(prefix="mut_%s_" % mid) as tmp:
        dst = Path(tmp) / "repo"
        shutil.copytree(ROOT, dst, ignore=IGNORE)
        # the PDF page-count test needs the committed PDFs
        for pdf in ROOT.glob("out/**/*.pdf"):
            (dst / pdf.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, dst / pdf.relative_to(ROOT))
        if rel is not None:
            f = dst / rel
            src = f.read_text(encoding="utf-8")
            if src.count(old) != 1:
                return mid, "BAD-PATTERN (%d matches)" % src.count(old)
            f.write_text(src.replace(old, new), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
                           cwd=dst, capture_output=True, text=True)
        if rel is None:
            return mid, "pass" if r.returncode == 0 else "FAIL
" + r.stdout[-3000:]
        return mid, "killed" if r.returncode != 0 else "SURVIVED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    todo = [m for m in MUTANTS if not args.only or m[0] in args.only]
    _, base = run(None)                  # a kill only counts if the clean suite passes
    print("baseline (no mutation): %s" % base)
    if base != "pass":
        return 1
    with ThreadPoolExecutor(args.jobs) as ex:
        results = dict(ex.map(run, todo))
    bad = 0
    for mid, rel, _, _, why in todo:
        print("%s %-9s %-18s %s" % (mid, results[mid], rel, why))
        bad += results[mid] != "killed"
    print("mutation check: %d/%d killed" % (len(todo) - bad, len(todo)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
