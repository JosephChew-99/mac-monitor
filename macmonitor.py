# macmonitor.py
"""macmonitor — a macOS menu bar system monitor."""
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
        super().__init__("macmonitor", title="macmonitor …", quit_button=None)

        # menu items (kept as attributes so the timer can mutate their titles)
        self.cpu_item = rumps.MenuItem("CPU 使用率  —")
        self.ram_item = rumps.MenuItem("RAM 已用  —")
        self.net_down_item = rumps.MenuItem("网络 下载  —")
        self.net_up_item = rumps.MenuItem("网络 上传  —")
        self.link_item = rumps.MenuItem("连接速率  —")
        self.disk_read_item = rumps.MenuItem("磁盘 读取  —")
        self.disk_write_item = rumps.MenuItem("磁盘 写入  —")
        self.speedtest_item = rumps.MenuItem("⚡ 立即测速 (fast.com 式)", callback=self.on_speed_test)
        self.speedtest_result = rumps.MenuItem("上次结果: 未测试")
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
            None,
            self.speedtest_item,
            self.speedtest_result,
            None,
            self.autostart_item,
            rumps.MenuItem("退出", callback=rumps.quit_application),
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

        # link speed is slow to read; refresh at most every 30s
        if now - self._last_link_read > LINK_SPEED_REFRESH_SECS or self._link_label is None:
            self._link_label = metrics.read_link_speed()
            self._last_link_read = now
        link_title = self._link_label or "Net --"

        # menu bar title: CPU · RAM · link speed
        self.title = (
            f"CPU {s['cpu_pct']:.0f}% · "
            f"RAM {metrics.fmt_gb(s['ram_used'])}G · "
            f"{link_title}"
        )

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
        self.speedtest_result.title = "测速中…"

        def worker():
            try:
                result = metrics.run_speed_test()
                if result["ok"]:
                    self.speedtest_result.title = (
                        f"上次结果: ↓{result['down_mbps']} / ↑{result['up_mbps']} Mbps"
                    )
                else:
                    self.speedtest_result.title = "测速失败（检查网络）"
            finally:
                self._speedtest_running = False

        threading.Thread(target=worker, daemon=True).start()

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
