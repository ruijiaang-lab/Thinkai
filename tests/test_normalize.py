from scs.normalize import normalize_status, normalize_uid

PREFIXES = ["UID:", "UID", "用户", "账号"]


def test_plain_uid():
    assert normalize_uid("10001") == "10001"


def test_strip_spaces():
    assert normalize_uid("  10001 \t") == "10001"


def test_inner_spaces_removed():
    assert normalize_uid("10 00 1") == "10001"


def test_fullwidth_to_halfwidth():
    assert normalize_uid("Ｕ10086", prefixes=PREFIXES) == "U10086"
    assert normalize_uid("１００８６") == "10086"


def test_float_uid_from_excel():
    assert normalize_uid(10002.0) == "10002"


def test_int_uid():
    assert normalize_uid(10001) == "10001"


def test_prefix_strip():
    assert normalize_uid("UID:10006", prefixes=PREFIXES) == "10006"
    assert normalize_uid("uid:10006", prefixes=PREFIXES) == "10006"
    # 即使前缀列表里 "UID" 在 "UID:" 之前，残留分隔符也应被清掉
    assert normalize_uid("UID:10006", prefixes=["UID"]) == "10006"
    assert normalize_uid("用户10007", prefixes=PREFIXES) == "10007"


def test_uppercase():
    assert normalize_uid("abc123") == "ABC123"


def test_empty_variants():
    for v in (None, "", "   ", "nan", "None", "null"):
        assert normalize_uid(v) is None


def test_bool_rejected():
    assert normalize_uid(True) is None


def test_regex_validation():
    assert normalize_uid("10001", uid_regex=r"\d+") == "10001"
    assert normalize_uid("A10001", uid_regex=r"\d+") is None


def test_status_mapping():
    assert normalize_status("已结算") == "settled"
    assert normalize_status("待定") == "pending"
    assert normalize_status("报价") == "quote"
    assert normalize_status("SETTLED") == "settled"
    assert normalize_status(None) == "settled"          # 默认
    assert normalize_status(None, default="pending") == "pending"
    assert normalize_status("随便什么", default="pending") == "pending"
