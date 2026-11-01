# Ubuntu for Xiaomi Pad 6 Pro

在 Xiaomi Pad 6 Pro 上运行 Ubuntu 26.04 桌面，采用 Plasma Mobile 桌面环境与基于上游 Linux 的设备适配内核。[English](README.md)

## 最新版本与近期更新

**[v0.6.0 正式版](https://github.com/yzddmr6/xiaomipad-6pro-mainline/releases/tag/v0.6.0)** 已发布。指纹、DP 外屏和双系统修复已整合进完整安装包，并在已知 256 GB 开发机完成安装、首次设置与功能确认。

自首次开源以来，主要更新包括：

- **原生指纹登录**：用 `fprintd-enroll`（或 Plasma 系统设置的“用户”页）录入，支持锁屏解锁和开机登录；已验证同指通过、异指拒绝，目前限首个账号、一枚指纹。
- **DP 外接显示**：已验证外屏画面、拔线恢复内屏及接回电脑恢复 USB；其他转接器、DP 音频和高刷新率仍待验证。
- **双系统与相机**：提供保留 Android 的安装布局和返回 Ubuntu 的 KernelSU 模块，修复原厂固件导致的启动问题；加入后置摄像头实验支持并修复扬声器。双系统验证边界见下方安装说明，相机限制见支持表。
- **输入、录音与充电**：修复磁吸键盘触摸板，适配不同触摸面板，加入 USB OTG、单麦克风录音和充电认证；补齐 Waydroid 所需内核配置，Waydroid 整体运行仍属未验收的实验功能。

## 📮 关注与交流

最新进展动态、使用技巧和 AI 讨论会先在公众号和小红书更新；刷机遇到问题也欢迎反馈。

| 公众号：熵减矩阵 | 小红书：yzddmr6 |
|:---:|:---:|
| <img src="docs/assets/gzh-qr.png" width="200" alt="公众号：熵减矩阵"> | <img src="docs/assets/xhs-qr.jpg" width="200" alt="小红书：yzddmr6"> |
| 进展动态 · 使用技巧 · AI 讨论 | 使用分享 · 问题反馈 |

## ⚠️ 安装前请阅读

本项目仅适用于 **Xiaomi Pad 6 Pro（liuqin，SM8475）**。其他小米平板型号不适用。

- **数据清除**：解锁 Bootloader 和首次安装会清除用户数据，请提前备份。
- **容量与布局**：安装器已在已知的 **256 GB 分区布局**完成真机验证，并不代表所有 256 GB 设备均兼容。其他容量、改过分区的设备未验证，不支持安装。安装器会重新划分磁盘尾部：双系统布局下两个系统都从 A 槽启动，单系统布局把 Ubuntu 安装到 B 槽；不要绕过校验。
- **验证范围**：安装与首次设置、旋转、触摸、磁吸键盘（含触摸板）、扬声器、单麦克风录音、USB OTG 主机模式（有线鼠标）、原生指纹登录、DP 外屏与深度休眠已有真机验证。各功能的范围见下表，并非每次发版都重测全部组合；Android 恢复流程尚未完成独立真机验证。
- **安装方式**：安装器提供 Ubuntu 单系统布局与保留原厂 Android 的双系统布局。双系统都从 A 槽启动，切换时把另一系统的 boot 镜像写入 `boot_a`。已知 256 GB 开发机已验证 A 槽 Ubuntu、修复原厂固件后的 Android 首次启动，以及调试 Android 下 KernelSU 模块脚本返回 Ubuntu；管理器 WebUI 按钮、普通 Android 启动下的 KernelSU 自动加载和单系统布局仍未验收。详见[安装步骤](docs/INSTALL-TESTING.zh-CN.md)。
- **恢复准备**：安装前请准备对应的原厂固件，并阅读[数据与恢复说明](docs/FLASHING.zh-CN.md#数据与恢复)。
- **功能限制**：部分硬件功能尚不完整，请先查看下方硬件支持表。

误刷启动镜像或分区可能导致设备无法启动。请按安装指南操作，并保留备份。
出厂校准与设备地址必须来自本机，不可跨设备复制。

## 🚀 获取与安装

请从 [GitHub Releases](https://github.com/yzddmr6/xiaomipad-6pro-mainline/releases) 下载完整安装包，不要混用不同版本的文件。

| 我想要 | 入口 |
|---|---|
| 安装 Ubuntu | [安装指南](docs/FLASHING.zh-CN.md) |
| 自行编译内核和设备组件 | [构建指南](docs/BUILD.zh-CN.md) |
| 恢复 Android | [数据与恢复说明](docs/FLASHING.zh-CN.md#数据与恢复) |
| 精简内存（zram、裁剪软件包） | [内存调整](#内存调整)，详见[内存说明](docs/MEMORY.zh-CN.md) |
| 让平板睡着（并唤醒它） | [挂起与唤醒](docs/SUSPEND.zh-CN.md) |

预编译安装包包括匹配的启动镜像、根文件系统、安装工具与校验文件。

## 硬件支持

以下为 Xiaomi Pad 6 Pro（liuqin）的当前硬件支持与已知限制。
器件信息来自本项目已确认的板级资料和设备树；不代表其他批次、容量或配件组合均已验证。

✅ 可用 · 🟡 部分支持 · ❌ 不支持 · 🧪 未验证

已验证功能速览，具体范围见下表：

- ✅ CPU · ✅ GPU 桌面加速 · ✅ 内置存储 · ✅ 120 Hz 显示 · ✅ 触摸 · ✅ 手动亮度
- ✅ 磁吸键盘与触摸板 · ✅ 原生指纹登录 · ✅ 自动旋转 · ✅ 电源键与音量键
- ✅ Wi-Fi · ✅ 蓝牙 · ✅ USB 数据传输 · ✅ USB OTG（有线鼠标）· ✅ DP 外屏（已测组合）
- ✅ 四扬声器 · ✅ 单麦克风录音 · ✅ H.264 硬解（用户态）· ✅ 后摄预览（实验性）· ✅ 电量显示与基础充电
- 🟡 深度休眠（能进出，约每三次有一次莫名提前唤醒）· 🟡 合盖睡眠（已配置，未实测）

### 平台、显示与输入

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| SoC / CPU | Qualcomm Snapdragon 8+ Gen 1（SM8475），ARM64 | ✅ 可用 | 主线内核启动与 Ubuntu 桌面运行；不代表全部节能状态已验证 |
| GPU / 桌面合成 | Adreno 730 / Freedreno / Mesa | ✅ 可用 | 桌面硬件加速；部分应用仍需渲染兼容设置 |
| 内置存储 | UFS / ext4 | ✅ 可用 | 持久系统与软件包安装；安装器仅面向已知 256 GB 布局 |
| 内置显示 | Novatek NT36532 / 双 DSI / DSC | ✅ 可用 | 2880 x 1800，120 Hz；其他刷新率未逐项验证 |
| 手动亮度 | Kinetic KTZ8866 背光控制 | ✅ 可用 | 背光与手动亮度调节 |
| 触控 | Novatek NT36532 / SPI（CSOT 或 TM 面板） | ✅ 可用 | 驱动按面板模块选择固件；点击、滑动与触控手势 |
| 磁吸键盘 | Nanosic WN8030 | ✅ 可用 | 普通按键、音量键、触摸板与重新吸附输入；挂起后恢复未完整覆盖 |
| 指纹 | FPC1264 / libfprint TOD / fprintd | ✅ 可用 | 原生设置录入、同指通过/异指拒绝、锁屏和正常重启后指纹登录；目前限首个账号（UID 1000）、一枚指纹，见[指纹说明](docs/FINGERPRINT.zh-CN.md) |
| 手写笔 | NVTCapacitivePen 输入接口 | 🧪 未验证 | 坐标、压感、按键及唤醒后的笔输入未实测 |
| 霍尔开关 | GPIO / SW_LID / SW_TABLET_MODE | 🟡 部分支持 | 开关状态可读取，且合盖开关是唤醒源，所以打开保护套能唤醒平板；桌面的合盖动作（PowerDevil `LidAction=Sleep`）已配置，但没有保护套就无法实际触发验证 |

### 无线与 USB

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| Wi-Fi 2.4 GHz | Qualcomm QCA6490 / ath11k | ✅ 可用 | 无线连接与日常联网 |
| Wi-Fi 5 GHz | QCA6490，按 WCN6855 系列适配 | ✅ 可用 | 5 GHz 连接已验证；不承诺特定峰值速率 |
| Wi-Fi 热点 / AP | NetworkManager / ath11k | 🧪 未验证 | 当前已确认的联网场景为客户端模式 |
| 蓝牙 | QCA6490 / hci_qca / BlueZ | ✅ 可用 | 日常蓝牙功能可用 |
| USB 2.0 设备模式 | Synopsys DWC3 / NXP eUSB2 repeater | ✅ 可用 | USB NCM 网络与数据传输；当前为 High-Speed 设备模式 |
| USB 充电器切换后重连 | USB-C / USB gadget | 🟡 部分支持 | v0.1.1 起由 UCSI typec 自动协商，可靠性预期改善；专项复测待做 |
| USB 3.x SuperSpeed | USB 控制器 / PHY | 🧪 未验证 | v0.1.1 起 SM8475 PHY 表与控制器已就绪；SuperSpeed 外设枚举未实测 |
| USB OTG / 主机模式 | USB-C 数据角色切换 | ✅ 可用 | v0.1.1 起 UCSI 自动角色协商；有线鼠标实测可用，U 盘/扩展坞待测 |
| USB-C 外接显示 | DisplayPort Alt Mode / FSA4480 | ✅ 可用 | 已测显示器/转接器组合下，真实外屏、拔出恢复内屏、接回电脑恢复 USB 已验证；其他扩展坞、DP 音频和高刷未逐项验收 |

### 音视频与传感器

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 四扬声器 | 4 × Cirrus Logic CS35L41 / AudioReach | ✅ 可用 | 立体声播放与音量控制，读取本机校准；音质仍在调校 |
| 内置麦克风 | WCD938x AMIC1 经 SoundWire → LPASS TX macro → ADSP codec DMA | ✅ 可用 | v0.3.0 起提供单声道 48 kHz 录音，已通过真机验证；其余三颗麦克风与降噪尚未接入 |
| H.264 视频硬解 | Qualcomm Iris2 / V4L2 | ✅ 可用 | 已验证用户态硬件解码，不等于浏览器已经接入 |
| 其他视频解码格式 | Iris / V4L2 | 🧪 未验证 | HEVC、VP9 等未完成逐项验证 |
| 浏览器视频硬解 | 浏览器 / V4L2 接入 | 🧪 未验证 | 浏览器能播放视频不等于使用硬件解码 |
| 硬件视频编码 | Qualcomm 视频引擎 | 🧪 未验证 | 尚未验证硬件编码工作流 |
| 后置摄像头 | S5KJN1 / Qualcomm CAMSS / libcamera 软件图像处理 | 🟡 部分支持 | 「相机」应用可预览、拍照、录像；软件图像处理，无自动对焦，录像有卡顿，见[相机](docs/CAMERA.zh-CN.md) |
| 前置摄像头 | 相机传感器 / CAMSS | ❌ 不支持 | 尚未启用或验证 |
| 加速度计 / 自动旋转 | SLPI / SSC / iio-sensor-proxy | ✅ 可用 | 首次启动、登录界面、桌面横竖旋转与磁吸键盘横屏 |
| 陀螺仪 / 磁力计 | SSC 传感器链路 | 🧪 未验证 | 未确认应用可用的测量链路，不随自动旋转标为可用 |
| 环境光传感器 | SSC 光感路径 | 🧪 未验证 | 尚未完成真实光照测量验收 |
| 自动亮度 | 桌面亮度策略 | ❌ 不支持 | 尚未接通自动亮度控制 |

### 电源与时间

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 电源键 / 音量键 | Qualcomm PMIC / GPIO 输入 | ✅ 可用 | 灭屏、亮屏、电源菜单与音量调整；已验证原生锁屏认证 |
| 电池状态 / 基础充电 | qcom_battmgr / UPower | ✅ 可用 | 电量、充电状态与基础墙充 |
| 电脑 USB 供电 | USB 供电路径 | 🟡 部分支持 | 供电功率有限，高负载时可能仍净放电 |
| 小米私有快充 | 厂商充电协议 | 🟡 部分支持 | 已集成充电器认证；电池认证已验证，PD 适配器可达 9 V / 2 A。MiPPS 与标准 PPS 快充尚待适配器验收 |
| 关机充电 | 启动阶段充电保持 | 🟡 部分支持 | 无完整充电显示界面；关机充电时开机需长按电源键 |
| 挂起 / 唤醒 | PSCI 深度睡眠 / PowerDevil | 🟡 部分支持 | 选中的睡眠状态是 `deep`：挂起会让非引导 CPU 下线并把 SoC 交给固件，唤醒后触摸、手写笔、键盘、触控板、Wi-Fi 与屏幕都回来。`liuqin-sleep-guard` 会把无人唤醒的平板重新睡回去，所以它不会在第一次睡眠之后就一直醒着。电池上实测：随镜像发布的策略下 **102 mA（1.36 %/h）**，清醒熄屏是 **216 mA（2.88 %/h）**。标为部分支持是因为平台仍止步 APSS 睡眠层——每次挂起后 `cxsd`、`ddr`、`aosd` 都是 0，而能解释这一点的五条 Linux 侧原因（子系统全停、USB PHY、AOP prevent 投票、SMP2P sleep state 位、CX 的 sleep-set 投票）都已被实测排除，真正的深睡需要固件侧工作。另外约每三次挂起会有一次提前结束，且内核归不到任何中断上。详见[挂起与唤醒](docs/SUSPEND.zh-CN.md) |
| RTC / 离线时间保持 | Qualcomm PMK8350 RTC | 🧪 未验证 | 联网校时可用；不保证离线写入及断电后的时间保持 |

## 内存调整

发布页上的 v0.6.0 安装包早于这部分工作：照原样安装，它会把整个 Ubuntu 桌面常驻在内存里，
跑着 `snapd`、`fwupd`、CUPS 和 Evolution 一组守护进程，而且**完全没有 swap**——安装布局
没有给 swap 分区留位置，产品内核又没开 `CONFIG_ZRAM`，于是 `systemd-oomd` 只剩「杀进程」
一种手段。在 8 GB 版本上实测，那是 2267 MB 的空闲 PSS，却没有任何可回收的东西。

两件事解决它，现在都在仓库里：

| 组成 | 作用 |
|---|---|
| 用 `kernel/source.json` 加上 `device/configs/liuqin-memory.config` 重编内核得到的 boot 镜像 | 让内核具备 zram + zstd，从而有 3 GiB 压缩 swap |
| `liuqin-memory-tweaks` 包 | 装 zram 配置、经评审的裁剪清单、`liuqin-root-trim` 和单元屏蔽 |

两者都应用后实测：完整会话下的总 PSS 1406 MB，且一个分配 6720 MiB（超过 `MemTotal`）的
进程能以 19.24:1 的压缩比跑完，而不是结束会话。逐分组的数据和清单里每一条的理由见
[docs/MEMORY.zh-CN.md](docs/MEMORY.zh-CN.md)。

### 全新安装

一旦发布包含这些改动的安装包，就不需要额外操作：安装器会在首次开机前对解包出的 root 执行
`device/tweaks/apply-root-tweaks.sh`，内核也按锁定的配置构建。某个安装包到底带了哪些特性，
记录在它 `bundle.json` 的 `features` 字段（`zram_swap`、`rootfs_trim`、`unit_masks`），
`install-liuqin.py` 会在写入任何东西之前打印出来。

**已发布的 v0.6.0 安装包不包含这些。** 下结论前先确认：

```sh
python3 install.py --bundle . --check    # 会打印这三行特性
```

### 已经装了 v0.6.0

取得这两个组成部分并按顺序应用——先内核，因为没有它 zram 配置没有驱动可绑定：

```sh
# 1. 只写入 boot_a；boot_b 保留引导程序的回退副本
sudo blockdev --setrw /dev/sde && sudo blockdev --setrw /dev/sde14
sudo dd if=boot-*-zram.img of=/dev/disk/by-partlabel/boot_a bs=1M conv=notrunc,fsync
sync && sudo reboot

# 2. root 文件系统一侧
sudo apt-get install -y ./liuqin-memory-tweaks_*_arm64.deb

# 3. 先看裁剪会删什么，再执行，然后重启
sudo liuqin-root-trim --dry-run
sudo liuqin-root-trim
```

第 1 步用 `tools/deploy-liuqin-boot.py` 更稳妥：它会回读比对、在所有退出路径上恢复分区与其
所在磁盘的只读标志，并先把现行 `boot_a` 存到 `backups/` 下。优先用它而不是上面的 `dd`。

自己重新构建这两个组成部分：

```sh
python3 tools/build-liuqin-kernel.py --source ../linux-sm8450-liuqin --out out/kernel
python3 tools/build-liuqin-memory-tweaks.py --kernel-out out/kernel
```

它拒绝已存在的输出目录，所以重新构建前要先 `rm -rf out/memory-tweaks`，或用
`--out` 指到新目录。产物是可复现的：同一个内核构建、同一棵树，产出的两个哈希每次都一致。

### 验证是否生效

```sh
adb -s liuqin push tests/memory-features.py /tmp/
adb -s liuqin shell 'python3 /tmp/memory-features.py --config /proc/config.gz --root / --packages'
```

它逐项报告每个定制是否到位，有任一缺失就以非零状态退出。同一个文件也是镜像构建的
`--stage features` 闸门，所以安装包不可能发布一个「定制没落地」的系统。

### 回退

每一步都只是包名加一个 boot 镜像。

```sh
sudo apt-get install snapd firefox                                    # 装回 snap
sudo apt-get install fwupd cups cups-browsed modemmanager rsyslog \
    networkd-dispatcher switcheroo-control evolution-data-server gnome-calendar
sudo apt-get install gnome-shell gdm3 ubuntu-session                 # 装回 GNOME 会话
sudo rm /etc/systemd/zram-generator.conf                              # 去掉 zram swap
```

内核一侧无法在运行时回退：需要重编并刷 boot 镜像，或用 `backups/liuqin-boot/` 下的
`boot_a` 副本。

## 挂起与睡眠

直到 v0.6.0，这台平板其实从不睡觉：PowerDevil 被固定为
`AutoSuspendIdleTimeoutSec=0`，因为本板的唤醒还没有验证过，所以空闲时只是熄灭屏幕，SoC 和 Wi-Fi 射频照旧运行。睡眠路径现在已经验证，本仓库发布的默认值开始使用它：

| 组成 | 作用 |
|---|---|
| 内核锁里的 `device/configs/liuqin-*.config` | 保留 `CONFIG_SUSPEND`、PSCI 系统挂起与 debugfs 的挂起计数 |
| `device/root-overlay/etc/xdg/powerdevilrc` | `AutoSuspendAction=1`，电池下 5 分钟、充电器下 15 分钟空闲超时，以及针对翻盖保护套的 `LidAction=1` |
| `device/root-overlay/etc/systemd/logind.conf.d/90-liuqin.conf` | `HandleLidSwitch=suspend`，作为会话出现之前的兜底 |

`/sys/power/mem_sleep` 选的是 `deep`，所以挂起走 `psci_system_suspend`，SoC 交给固件。RTC 闹钟、电源键和两个霍尔开关在设备树里就是唤醒源，所以能否唤醒不取决于会话是否还在监听。电源键短按默认仍是熄屏并锁屏；想让电源键挂起，执行 `gsettings set io.github.liuqin.power short-press-action suspend`。

**尚未验证的部分**：约每三次挂起有一次提前结束，既没有唤醒源计数也没有归因到任何中断（是固件层把 AP 拉起来的）；保护套的合盖动作没有在真实开关上触发过（虚拟 `SW_LID` 设备到不了 PowerDevil 监听的源）；接外接显示器时挂起未测试。睡眠功耗本身已经量出来了：2.5 小时窗口下 121 mA（1.6 %/h），清醒熄屏是 227 mA——固件自己的计数说明了它为什么不再低。数据、唤醒源表与缺口都在 `docs/SUSPEND.zh-CN.md`；`tests/suspend-resume.py` 是必须持续通过的检查。

已经装好的平板要让上面的默认值生效，必须把启动契约和文件一起重新绑定：`/etc/xdg/powerdevilrc` 属于 ramdisk 准入契约锁定的文件，直接拷进去会让下一次启动停在 initramfs 诊断 shell。根镜像构建会自动完成这一步；手工做法见 `docs/SUSPEND.zh-CN.md`。

回到旧行为只需要改一个键并重新加载：

```sh
sudo sed -i 's/^AutoSuspendIdleTimeoutSec=.*/AutoSuspendIdleTimeoutSec=0/' /etc/xdg/powerdevilrc
systemctl --user restart plasma-powerdevil
```

## 使用与维护

Ubuntu 软件包通过 APT 管理。项目内核与设备组件的更新方式将随安装版本说明，
不要混用不同版本的启动镜像和系统组件。

如需在 Ubuntu 中运行 Android 应用，可使用 Waydroid；所需内核配置已内置，
见 [Waydroid 支持](docs/WAYDROID.zh-CN.md)。

充电功率由厂商充电器认证路径协商，见 [快充](docs/FASTCHARGE.zh-CN.md)。

遇到问题时，请提供设备型号、系统版本、复现步骤和相关日志，并通过 GitHub Issues 反馈。
提交日志前，请移除密码、网络凭据和个人信息。使用交流也可通过顶部的公众号与小红书进行。

## 开发与贡献

| 仓库 | 内容 |
|---|---|
| xiaomipad-6pro-mainline | 设备配置、用户态适配、构建与安装工具、文档 |
| [linux-sm8450-liuqin](https://github.com/yzddmr6/linux-sm8450-liuqin) | 完整 Linux 内核源码与设备适配提交 |

构建使用的内核提交记录在 [kernel/source.json](kernel/source.json)。
内核分支为 `liuqin-6.17`。欢迎改进驱动、构建工具与文档，提交方式见
[参与贡献](CONTRIBUTING.md)。

## 致谢与许可证

本项目基于 [sm8450-mainline](https://github.com/sm8450-mainline/linux) 的内核工作，
并使用 Ubuntu、KDE、GNOME 和 Linux Qualcomm 社区的成果。

除文件另有声明外，项目原创代码采用 MIT 许可证。Linux 内核及第三方组件保留各自许可证；
固件适用其权利人的授权条款。详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
