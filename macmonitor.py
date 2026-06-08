# macmonitor.py
"""macmonitor — a macOS menu bar system monitor."""
import subprocess
import sys
import threading
import time

import rumps

import metrics
import autostart

APP_PATH = "/Applications/macmonitor.app"  # used by the auto-start LaunchAgent
LINK_SPEED_REFRESH_SECS = 30


class MacMonitor(rumps.App):
    def __init__(self):
        # quit_button="退出" just adds a Chinese quit item to the dropdown.
        # (The status bar item itself shows regardless of quit_button; if it's
        # missing it's almost always menu-bar overflow on a notched Mac, not this.)
        super().__init__("macmonitor", title="…", quit_button="退出")

        # menu items (kept as attributes so the timer can mutate their titles)
        self.cpu_item = rumps.MenuItem("CPU 使用率  —")
        self.ram_item = rumps.MenuItem("RAM 已用  —")
        self.net_down_item = rumps.MenuItem("网络 下载  —")
        self.net_up_item = rumps.MenuItem("网络 上传  —")
        self.link_item = rumps.MenuItem("连接速率  —")
        self.disk_read_item = rumps.MenuItem("磁盘 读取  —")
        self.disk_write_item = rumps.MenuItem("磁盘 写入  —")
        self.storage_item = rumps.MenuItem("存储空间  —")
        self.speedtest_item = rumps.MenuItem("⚡ 立即测速 (fast.com 式)", callback=self.on_speed_test)
        self.speedtest_result = rumps.MenuItem("测速结果: 未测试")
        self.activity_item = rumps.MenuItem("打开活动监视器", callback=self.on_open_activity_monitor)
        self.autostart_item = rumps.MenuItem("开机自启", callback=self.on_toggle_autostart)
        self.autostart_item.state = 1 if autostart.is_enabled() else 0

        self.menu = [
            self.cpu_item,
            None,
            self.ram_item,
            None,
            self.net_down_item,
            self.net_up_item,
            self.link_item,
            None,
            self.disk_read_item,
            self.disk_write_item,
            self.storage_item,
            None,
            self.speedtest_item,
            self.speedtest_result,
            None,
            self.activity_item,
            self.autostart_item,
            # The "退出" quit button is added automatically via quit_button="退出".
        ]

        self._net_rate = metrics.RateCalc()
        self._disk_rate = metrics.RateCalc()
        self._link_label = None
        self._last_link_read = 0.0
        self._speedtest_running = False

    def _render(self):
        """Sample all metrics and update the title + dropdown. Called every 2s."""
        now = time.monotonic()
        s = metrics.sample_cpu_ram()

        recv, sent = metrics.raw_net_counters()
        dn, up = self._net_rate.update(recv, sent, now)
        read, write = metrics.raw_disk_counters()
        rd, wr = self._disk_rate.update(read, write, now)

        # link speed (CoreWLAN — instant, no subprocess) refreshed at most every 30s
        if now - self._last_link_read > LINK_SPEED_REFRESH_SECS or self._link_label is None:
            self._link_label = metrics.read_link_speed()
            self._last_link_read = now
        # menu bar title: spaced out for readability, e.g. "23% · 8.4G".
        self.title = f"{s['cpu_pct']:.0f}% · {metrics.fmt_gb(s['ram_used'])}G"

        # dropdown detail
        self.cpu_item.title = f"CPU 使用率  {s['cpu_pct']:.1f}%"
        self.ram_item.title = (
            f"RAM 已用  {metrics.fmt_gb(s['ram_used'])} GB / "
            f"{metrics.fmt_gb(s['ram_total'])} GB ({s['ram_pct']:.0f}%)"
        )
        self.net_down_item.title = f"网络 下载  {metrics.fmt_rate(dn)}/s"
        self.net_up_item.title = f"网络 上传  {metrics.fmt_rate(up)}/s"
        self.link_item.title = f"连接速率  {self._link_label or '--'}"
        self.disk_read_item.title = f"磁盘 读取  {metrics.fmt_rate(rd)}/s"
        self.disk_write_item.title = f"磁盘 写入  {metrics.fmt_rate(wr)}/s"
        ds = metrics.disk_space()
        self.storage_item.title = (
            f"存储空间  已用 {metrics.fmt_gb_decimal(ds['used'])} GB · "
            f"可用 {metrics.fmt_gb_decimal(ds['free'])} GB"
        )

    @rumps.timer(2)
    def refresh(self, _):
        try:
            self._render()
        except Exception as e:
            # A transient sampling error must not kill the timer; keep the
            # previous values and try again on the next tick.
            print(f"macmonitor: refresh error: {e}", file=sys.stderr)

    def on_speed_test(self, _):
        if self._speedtest_running:
            return
        self._speedtest_running = True
        # Clicking a menu item closes the menu, so the user can't watch this line
        # update live — they'd have to reopen the menu. We post a notification when
        # the run finishes so the result reaches them without reopening.
        self.speedtest_result.title = "测速中…（约 10 秒，完成会通知）"

        def worker():
            try:
                result = metrics.run_speed_test()
                if result["ok"]:
                    summary = f"↓{result['down_mbps']} / ↑{result['up_mbps']} Mbps"
                    self.speedtest_result.title = f"结果: {summary}"
                    self._notify("测速完成", summary)
                else:
                    self.speedtest_result.title = "测速失败（检查网络）"
                    self._notify("测速失败", "请检查网络连接")
            finally:
                self._speedtest_running = False

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _notify(title, message):
        """Post a macOS notification; no-ops if unavailable (e.g. run as a plain
        script rather than the bundled .app)."""
        try:
            rumps.notification(title, "", message)
        except Exception:
            pass

    def on_open_activity_monitor(self, _):
        try:
            subprocess.run(["open", "-a", "Activity Monitor"], check=True)
        except Exception as e:
            rumps.alert("无法打开活动监视器", str(e))

    def on_toggle_autostart(self, sender):
        try:
            if sender.state:
                autostart.disable()
                sender.state = 0
            else:
                autostart.enable(APP_PATH)
                sender.state = 1
        except Exception as e:
            rumps.alert("开机自启设置失败", str(e))


if __name__ == "__main__":
    MacMonitor().run()
