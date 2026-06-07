# macmonitor — 设计文档 (Design Spec)

日期: 2026-06-07
状态: 已批准 (Approved)

## 1. 目标 (Goal)

做一个 macOS **菜单栏 (menu bar)** 小工具，实时显示电脑的：
- **CPU 使用率 (%)**
- **RAM 已用 (GB / 总量)**
- **网络速率 (下载 / 上传, MB/s)**
- **磁盘 I/O 速率 (读 / 写, MB/s)**

数据来源与「活动监视器 (Activity Monitor)」一致（底层都是 macOS 内核的系统指标）。

App 名称: **macmonitor**

## 2. 技术栈 (Tech Stack)

| 用途 | 选型 |
|------|------|
| 菜单栏 UI | [rumps](https://github.com/jaredks/rumps) |
| 系统指标 | [psutil](https://github.com/giampaolo/psutil) |
| 打包成 .app | [py2app](https://py2app.readthedocs.io/) |
| 开机自启 | macOS `launchd` + LaunchAgent plist |
| 语言 | Python 3 |

## 3. 显示设计 (UI)

### 菜单栏标题（一直可见）
```
CPU 23% · RAM 8.1G · ↓1.2M ↑0.3M
```
（↓ = 网络下载，↑ = 网络上传，单位自适应 K/M）

### 点击后的下拉菜单
```
CPU 使用率        23.4%
─────────────────────
RAM 已用          8.1 GB / 16 GB (51%)
─────────────────────
网络 下载         1.2 MB/s
网络 上传         0.3 MB/s
─────────────────────
磁盘 读取         1.2 MB/s
磁盘 写入         0.4 MB/s
─────────────────────
刷新间隔: 2 秒
☑ 开机自启           ← 可点击切换 (toggle)
退出
```

## 4. 数据计算方式 (Metrics)

| 指标 | 方法 |
|------|------|
| CPU % | `psutil.cpu_percent()`（两次采样间平均使用率，非阻塞模式） |
| RAM 已用 | `psutil.virtual_memory().used` 与 `.total`，换算成 GB 与百分比 |
| 网络速率 | `psutil.net_io_counters()` 取 `bytes_recv`/`bytes_sent`，**两次采样做差再除以时间间隔** → 下载/上传 速率 |
| 磁盘 I/O | `psutil.disk_io_counters()` 取 `read_bytes`/`write_bytes`，**两次采样做差再除以时间间隔** → MB/s 实时速率 |

注意：网络项与磁盘项都是**速率 (MB/s)**，不是累计总量。
单位自适应：< 1 MB/s 显示成 KB/s（如 `820K`），≥ 1 MB/s 显示成 MB/s（如 `1.2M`）。

## 5. 运行机制 (Runtime)

- 主类继承 `rumps.App`
- 用 `@rumps.timer(2)` 每 **2 秒** 回调一次，重新采样并刷新标题与菜单文字
- 网络与磁盘速率需要在回调间保存上一次的计数器与时间戳，做差值
- 入口: `python3 macmonitor.py` 即可运行

## 6. 开机自启 (Auto-launch)

- 菜单里有一个 **「开机自启」** 勾选项 (toggle)
- 点击 → 程序自动在 `~/Library/LaunchAgents/com.macmonitor.plist` 写入/删除 LaunchAgent 配置，并 `launchctl load/unload`
- 勾选状态由「该 plist 文件是否存在」决定
- plist 指向打包后的 `macmonitor.app`（或开发期指向 python 脚本）

## 7. 打包成 .app (Packaging)

- 用 `setup.py` + py2app：`python3 setup.py py2app`
- 产出 `dist/macmonitor.app`，拖进「应用程序」即可双击运行
- 设为 `LSUIElement`（agent app，不在 Dock 显示图标，只在菜单栏）

## 8. 项目结构 (Structure)

```
~/macmonitor/
├── macmonitor.py             # 主程序
├── requirements.txt          # rumps, psutil
├── setup.py                  # py2app 打包配置
├── README.md                 # 安装/运行/打包/自启说明
└── docs/superpowers/specs/   # 本设计文档
```

(`com.macmonitor.plist` 由程序在运行时动态生成，不手写进仓库。)

## 9. 错误处理 (Error Handling)

- psutil 取数失败 → 该项显示 `--`，不崩溃
- 首次启动网络/磁盘没有上一帧数据 → 显示 `0.0 MB/s`
- 开机自启写 plist 失败（权限等）→ 弹 `rumps.alert` 提示，不影响主功能

## 10. 验证 (Testing / Verification)

- 手动运行脚本，菜单栏出现 `CPU.. · RAM.. · ↓.. ↑..`，数字随负载变化
- 与「活动监视器」对照，CPU/RAM 数量级一致
- 跑个大文件复制，看磁盘读/写 MB/s 跳动
- 下载/上传东西，看网络 ↓/↑ 速率跳动
- 切换「开机自启」开关，确认 plist 被正确创建/删除

## 11. 交付步骤 (Build Order)

1. `macmonitor.py` 核心脚本 → `python3` 跑通、验证数字
2. 「开机自启」菜单开关 + plist 读写逻辑
3. `setup.py` + py2app 打包出 `macmonitor.app`
4. `README.md` 写清每步操作
5. 最终验证

## 12. 范围之外 (Out of Scope, YAGNI)

- 历史曲线图 / 图表
- 分网卡 / 分进程的网络流量明细（先合并所有网卡）
- 多磁盘分别显示（先合并所有磁盘）
- 自定义刷新频率 UI（先固定 2 秒）
