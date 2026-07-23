from decimal import Decimal

from scs.money import parse_amount, round_amount


def test_parse_number():
    assert parse_amount(120.0) == Decimal("120.0")
    assert parse_amount(88) == Decimal("88")


def test_parse_string_with_commas_and_currency():
    assert parse_amount("1,234.50") == Decimal("1234.50")
    assert parse_amount("¥88.5") == Decimal("88.5")
    assert parse_amount("￥ 1,000") == Decimal("1000")
    assert parse_amount("$2,000.10") == Decimal("2000.10")


def test_parse_fullwidth():
    assert parse_amount("８８．５") == Decimal("88.5")


def test_parse_invalid():
    for v in (None, "", "待定", "-", "abc", "nan"):
        assert parse_amount(v) is None


def test_parse_float_precision_preserved():
    # 0.1+0.2 的 float 尾巴被 str() 原样保留，交给舍入环节处理
    d = parse_amount(0.1 + 0.2)
    assert d is not None
    assert round_amount(d, 2) == Decimal("0.30")


def test_round_half_up():
    assert round_amount(Decimal("0.125"), 2) == Decimal("0.13")
    assert round_amount(Decimal("2.675"), 2) == Decimal("2.68")
    assert round_amount(Decimal("1234.567"), 2) == Decimal("1234.57")
    assert round_amount(Decimal("120"), 2) == Decimal("120.00")


def test_round_half_even():
    assert round_amount(Decimal("0.125"), 2, "half_even") == Decimal("0.12")


def test_round_places():
    assert round_amount(Decimal("1.2345"), 3) == Decimal("1.235")
    assert round_amount(Decimal("1.2345"), 0) == Decimal("1")
