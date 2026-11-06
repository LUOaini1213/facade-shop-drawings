from collections import Counter

from fsd import members as M
from fsd import upstream as U


def test_upstream_files_match_pinned_hashes():
    assert U.verify_source()["commit"].startswith("fac01b7")


def test_member_count_and_profiles():
    rows = M.member_rows()
    assert len(rows) == 3962
    per_type = Counter((r["type"], r["profile"]) for r in rows)
    assert per_type[("U4", "TRANSOM")] == 4          # 2 door units x 2 intermediate members
    assert per_type[("U5", "TRANSOM")] == 0          # parapet: sill + head only
    assert per_type[("U2", "MUL-L")] == per_type[("U2", "MUL-R")] == 620


def test_frame_mass_reconciles_with_takeoff():
    c = U.config()
    kg = M.frame_kg(M.member_rows(), c)
    for t, row in U.takeoff().items():
        if t in kg:
            assert round(kg[t], 2) == float(row["frame_alu_kg"])
    assert round(sum(kg.values()), 2) == 34386.02


def test_sill_bottom_head_top():
    c = U.config()
    for t, (w, h, _) in M.panel_types(U.panels()).items():
        mem = M.panel_members(t, w, h, c)
        horiz = sorted((z, p) for p, _, z in mem if not p.startswith("MUL"))
        assert horiz[0] == (0, "SILL")
        assert horiz[-1] == (h - c["TRANSOM_H"], "HEAD")
        assert all(L == w - 2 * c["MULLION_W"] for p, L, _ in mem if not p.startswith("MUL"))
        assert all(L == h for p, L, _ in mem if p.startswith("MUL"))


def test_zone_stack_sums_to_panel_height():
    c = U.config()
    for t, (w, h, _) in M.panel_types(U.panels()).items():
        assert sum(z for _, z in M.zones(t, h, c)) == h
