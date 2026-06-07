# tests/test_autostart.py
import plistlib
import autostart


def test_plist_path_is_in_launchagents():
    p = autostart.plist_path()
    assert p.name == "com.macmonitor.plist"
    assert "LaunchAgents" in str(p)


def test_build_plist_bytes_is_valid_and_runs_target():
    data = autostart.build_plist_bytes("/Applications/macmonitor.app")
    parsed = plistlib.loads(data)
    assert parsed["Label"] == "com.macmonitor"
    assert parsed["RunAtLoad"] is True
    # the program arguments should reference the target
    assert any("macmonitor" in str(a) for a in parsed["ProgramArguments"])


def test_is_enabled_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "plist_path", lambda: tmp_path / "com.macmonitor.plist")
    assert autostart.is_enabled() is False
