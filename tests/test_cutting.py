import pytest

from fsd import cutting as X


def test_ffd_is_suboptimal_on_classic_instance_and_ilp_is_not():
    d = {500: 2, 400: 2, 300: 4}               # total 3000 = exactly three 1000 bars
    f = X.ffd(d, stock=(1000,), kerf=0, trim=0)
    o, info = X.ilp(d, stock=(1000,), kerf=0, trim=0)
    X.validate(f, d, (1000,), 0, 0)
    X.validate(o, d, (1000,), 0, 0)
    assert len(f) == 4
    assert len(o) == 3 and info["status"] == "Optimal"


def test_kerf_and_trim_limit_pieces_per_bar():
    # 4 x (1460 + 5) = 5860 <= 6000 - 20, a fifth piece would not fit
    assert X.fits((1460,) * 4, 6000)
    assert not X.fits((1460,) * 5, 6500)
    assert not X.fits((5990,), 6000)                 # trim eats 20 mm
    assert X.fits((5975,), 6000)                     # 5975 + 5 kerf = 5980 exactly
    assert not X.fits((5976,), 6000)                 # 1 mm over: both ends are trimmed


def test_ffd_shrinks_bars_to_shortest_stock():
    bars = X.ffd({3880: 3})
    assert [L for L, _ in bars] == [6000, 6000, 6000]


def test_ilp_prefers_less_material_then_fewer_bars():
    # one 6200 piece needs a 6500 bar; the 1180 pieces fill one 6000 bar
    bars, _ = X.ilp({6200: 1, 1180: 5})
    s = X.score(bars)
    assert s["purchased_mm"] == 12500 and s["bars"] == 2


def test_score_balances():
    bars = X.ffd({4480: 3, 1180: 7, 3880: 2})
    s = X.score(bars)
    assert s["net_mm"] + s["kerf_mm"] + s["trim_mm"] + s["offcut_mm"] == s["purchased_mm"]
    assert s["offcut_mm"] >= 0
    assert s["pieces"] == 12 and s["kerf_mm"] == 60


def test_validate_rejects_overfill_and_wrong_demand():
    with pytest.raises(ValueError):
        X.validate([(6000, (3000, 3000))], {3000: 2})
    with pytest.raises(ValueError):
        X.validate([(6000, (3000,))], {3000: 2})
    with pytest.raises(ValueError):
        X.validate([(7000, (3000,))], {3000: 1})


def test_piece_longer_than_any_bar_is_rejected():
    with pytest.raises(ValueError):
        X.ffd({6490: 1})
