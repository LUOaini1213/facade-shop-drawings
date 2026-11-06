import csv
import difflib
import filecmp
import json
import re

import ezdxf

from conftest import ROOT
from fsd import checks

COMMITTED = ROOT / "out"
DETERMINISTIC = ["members.csv", "drawing_register.csv", "summary.json", "cutting/summary.csv",
                 "cutting/stock_sensitivity.csv"] + ["drawings/FSD-SD-10%d.dxf" % i for i in range(1, 6)]
CLEAN = {"drawings": [], "members": [], "cutting": []}


def test_fresh_build_passes_all_checks(built):
    assert checks.run_all(built) == CLEAN


def test_committed_outputs_pass_all_checks():
    assert checks.run_all(COMMITTED) == CLEAN


def test_committed_outputs_equal_fresh_build(built):
    diff = [f for f in DETERMINISTIC if not filecmp.cmp(built / f, COMMITTED / f, shallow=False)]
    detail = []
    for f in diff[:3]:
        a = (COMMITTED / f).read_text(encoding="utf-8").splitlines()
        b = (built / f).read_text(encoding="utf-8").splitlines()
        detail += list(difflib.unified_diff(a, b, f, f, n=1, lineterm=""))[:12]
    assert diff == [], chr(10).join(detail)


def test_headline_numbers(built):
    s = json.loads((built / "summary.json").read_text(encoding="utf-8"))
    assert s["panels"] == 810 and s["members"] == 3962 and s["drawings"] == 5
    assert s["pooled_ilp"]["purchased_mm"] <= s["pooled_ffd"]["purchased_mm"]
    assert s["by_type_ilp"]["purchased_mm"] >= s["pooled_ilp"]["purchased_mm"]


def _pages(path):
    return len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes()))


def test_pdfs_have_one_page_per_sheet():
    reg = list(csv.DictReader(open(COMMITTED / "drawing_register.csv", encoding="utf-8")))
    assert _pages(COMMITTED / "drawings" / "shop_drawings.pdf") == len(reg)
    assert _pages(COMMITTED / "cutting" / "cutting_sheets.pdf") >= len(reg) + 1


# ---- the checker itself must catch tampering --------------------------------

def _edit(path, fn):
    doc = ezdxf.readfile(path)
    fn(doc)
    doc.saveas(path)


def test_check_catches_moved_dimension(built_copy):
    def move(doc):
        d = next(iter(doc.modelspace().query("DIMENSION")))
        d.dxf.defpoint3 = d.dxf.defpoint3 + (1.0, 0, 0)
    _edit(built_copy / "drawings" / "FSD-SD-102.dxf", move)
    assert checks.check_drawings(built_copy)


def test_check_catches_overridden_dimension_text(built_copy):
    def fake(doc):
        next(iter(doc.modelspace().query("DIMENSION"))).dxf.text = "1580"
    _edit(built_copy / "drawings" / "FSD-SD-101.dxf", fake)
    assert checks.check_drawings(built_copy)


def test_check_catches_missing_layer(built_copy):
    def drop(doc):
        msp = doc.modelspace()
        for e in list(msp.query("*[layer=='CUTLINE']")):
            msp.delete_entity(e)
        doc.layers.remove("CUTLINE")
    _edit(built_copy / "drawings" / "FSD-SD-103.dxf", drop)
    assert any("missing layers" in f for f in checks.check_drawings(built_copy))


def test_check_catches_wrong_schedule_text(built_copy):
    def bump(doc):
        for t in doc.modelspace().query("TEXT[layer=='SCHEDULE']"):
            t.dxf.text = t.dxf.text.replace("620 total", "621 total")
    _edit(built_copy / "drawings" / "FSD-SD-102.dxf", bump)
    assert any("schedule" in f for f in checks.check_drawings(built_copy))


def test_check_catches_cut_list_dropping_a_member(built_copy):
    p = built_copy / "cutting" / "plan_U3.csv"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    p.write_text("".join(lines[:-1]), encoding="utf-8")
    assert checks.check_cutting(built_copy, 5, 20, (6000, 6500))


def test_check_catches_member_length_change(built_copy):
    p = built_copy / "members.csv"
    s = p.read_text(encoding="utf-8").replace(",MUL-L,3880,", ",MUL-L,3881,", 1)
    p.write_text(s, encoding="utf-8")
    assert checks.check_members(built_copy)


# ---- README numbers -----------------------------------------------------------

def test_readme_numbers_match_outputs():
    import check_readme
    bad, _, _ = check_readme.check((ROOT / "README.md").read_text(encoding="utf-8"))
    assert bad == []


def test_readme_check_catches_changed_and_stray_numbers():
    import check_readme
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert check_readme.check(text.replace("76.69%", "77.69%"))[0]
    assert check_readme.check(text + "\nWe saved 4,321 m.\n")[0]
