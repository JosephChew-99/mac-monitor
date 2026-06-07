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


SP_SAMPLE = """
      Interfaces:
        en0:
          Card Type: Wi-Fi
          Status: Connected
          Current Network Information:
            MyNetwork:
              PHY Mode: 802.11ax
              Channel: 36 (5GHz, 80MHz)
              Tx Rate: 1200
"""


def test_parse_airport_tx_rate_extracts_mbps():
    assert metrics.parse_airport_tx_rate(SP_SAMPLE) == 1200


def test_parse_airport_tx_rate_missing_returns_none():
    assert metrics.parse_airport_tx_rate("no rate here") is None


def test_read_link_speed_does_not_crash():
    # On CI/headless this may be None; we only require it not to raise.
    result = metrics.read_link_speed()
    assert result is None or isinstance(result, str)


def test_mbps_from_bytes_and_time():
    # 12.5 MB in 1.0s = 100 Mbps
    assert metrics.mbps(12_500_000, 1.0) == 100.0


def test_run_speed_test_uses_injected_io(monkeypatch):
    # Fake: 25 MB downloaded in 2s, 5 MB uploaded in 1s
    monkeypatch.setattr(metrics, "_http_download_bytes", lambda nbytes, t: (25_000_000, 2.0))
    monkeypatch.setattr(metrics, "_http_upload_bytes", lambda nbytes, t: (5_000_000, 1.0))
    result = metrics.run_speed_test()
    assert result["ok"] is True
    assert result["down_mbps"] == 100.0
    assert result["up_mbps"] == 40.0


def test_run_speed_test_failure_returns_not_ok(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(metrics, "_http_download_bytes", boom)
    result = metrics.run_speed_test()
    assert result["ok"] is False
    assert "error" in result


def test_rate_calc_clamps_negative_on_counter_reset():
    rc = metrics.RateCalc()
    rc.update(read=5000, write=9000, now=10.0)
    # counters reset DOWN (e.g. interface restart): must not return negatives
    assert rc.update(read=100, write=200, now=11.0) == (0.0, 0.0)
