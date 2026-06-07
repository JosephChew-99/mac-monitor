import metrics


def test_fmt_rate_below_one_mb_shows_kb():
    # 820 KB/s -> "820K"
    assert metrics.fmt_rate(820 * 1024) == "820K"


def test_fmt_rate_at_or_above_one_mb_shows_mb_one_decimal():
    # 1.2 MB/s -> "1.2M"
    assert metrics.fmt_rate(int(1.2 * 1024 * 1024)) == "1.2M"


def test_fmt_rate_zero():
    assert metrics.fmt_rate(0) == "0K"


def test_fmt_gb_one_decimal():
    # 8.1 GiB
    assert metrics.fmt_gb(int(8.1 * 1024**3)) == "8.1"
