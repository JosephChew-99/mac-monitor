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


# append to tests/test_metrics.py

def test_rate_calc_first_sample_returns_zero():
    rc = metrics.RateCalc()
    # first observation has no previous frame
    assert rc.update(read=1000, write=2000, now=10.0) == (0.0, 0.0)


def test_rate_calc_second_sample_divides_by_interval():
    rc = metrics.RateCalc()
    rc.update(read=1000, write=2000, now=10.0)
    # 1 second later: +500 read, +1000 write
    assert rc.update(read=1500, write=3000, now=11.0) == (500.0, 1000.0)


def test_rate_calc_handles_zero_interval():
    rc = metrics.RateCalc()
    rc.update(read=1000, write=2000, now=10.0)
    # same timestamp -> avoid divide-by-zero, return 0
    assert rc.update(read=1500, write=3000, now=10.0) == (0.0, 0.0)


# append to tests/test_metrics.py

def test_sample_cpu_ram_returns_expected_keys():
    s = metrics.sample_cpu_ram()
    assert set(s.keys()) == {"cpu_pct", "ram_used", "ram_total", "ram_pct"}
    assert 0.0 <= s["cpu_pct"] <= 100.0 * (psutil_cpu_count() or 1)
    assert s["ram_used"] <= s["ram_total"]


def test_raw_net_counters_returns_two_ints():
    recv, sent = metrics.raw_net_counters()
    assert isinstance(recv, int) and isinstance(sent, int)
    assert recv >= 0 and sent >= 0


def test_raw_disk_counters_returns_two_ints():
    read, write = metrics.raw_disk_counters()
    assert isinstance(read, int) and isinstance(write, int)
    assert read >= 0 and write >= 0


def psutil_cpu_count():
    import psutil
    return psutil.cpu_count()
