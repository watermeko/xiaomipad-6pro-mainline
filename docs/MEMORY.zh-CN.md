# 内存：占用在哪，这个产品砍掉什么

本文是 `device/configs/` 里几张裁剪清单的证据来源：

| 文件 | 作用对象 |
|---|---|
| `device/configs/liuqin-memory.config` | 内核（`CONFIG_ZRAM`、zstd、multi-comp） |
| `device/configs/liuqin-root-trim.txt` | rootfs 软件包（`[purge]` / `[keep]`） |
| `device/root-overlay/etc/systemd/zram-generator.conf` | 已安装系统的 swap 形状 |
| `device/root-overlay/etc/systemd/**` 指向 `/dev/null` 的软链 | 不删包、只屏蔽的单元 |

## 实测基线（GNOME Shell，迁移前）

桌面自 2026-10-30 起是 Plasma Mobile；本节是当初驱动裁剪的 GNOME Shell 实测，
保留是因为 `[purge]` 的取舍仍然引用它。Plasma 的数字见下文“Plasma Mobile 迁移”。

小米平板 6 Pro，8 GB 版本，`MemTotal` 6608256 kB（其余被固件保留），Ubuntu 26.04，
GNOME Shell 50.1，开机 10 分钟，单用户，额外开了「设置 → 电源」和终端。下表是把同名
进程的 **PSS** 相加，而不是 RSS，所以共享的 GTK/Mesa 页不会被每个进程重复计一次。

| 分组 | PSS | 说明 |
|---|---:|---|
| GNOME Shell + 会话 | 755 MB | `gnome-shell` 301、`gjs` 辅助进程 115、`mutter-x11-frames` 52、`Xwayland` 48、`gsd-*` 约 120 |
| Evolution / 日历 / 索引 | 244 MB | `evolution-alarm-notify` 43、EDS 通讯录 30、日历 28、source registry 26、`gnome-calendar` 53、`localsearch-3` 36 |
| 可裁守护进程 | 215 MB | `fwupd` 52、`update-notifier` 28、`unattended-upgrade-shutdown` 23、`networkd-dispatcher` 20、`ModemManager` 18、`colord` 16、CUPS 30、`switcheroo-control` 9 |
| snap | 158 MB | `snapd` 72、`snap userd` 50、`snapd-desktop-integration` 28 |
| gvfs | 106 MB | 十个按协议拆分的守护进程，每个 13–17 MB |
| xdg portal | 101 MB | 沙箱应用路径的必需品 |
| ibus（中文输入） | 98 MB | `ibus-x11` 26、`ibus-extension-gtk3` 30、守护进程 19 |
| 音频 | 67 MB | PipeWire、WirePlumber、filter-chain |
| 用户临时打开 | 275 MB | 设置 158 + 终端 117，不是基线成本 |
| **合计** | **2267 MB** | |

磁盘侧顺带一提：装完 6.41 GiB，其中 1.78 GB 是 stock HWE 内核（
`linux-modules-7.0.0-{14,38}-generic` 与 headers）加上这块板子根本用不到的
NVIDIA/AMD/Intel/Mellanox/QLogic `linux-firmware-*`，另有 820 MB 是 LibreOffice。

## 真正的问题不是数字，而是没有可回收的东西

`swapon --show` 为空、`/proc/swaps` 没有条目：安装布局把 UFS 尾部留给了 A/B 槽、
`linux_home` 和（双系统时的）Android，所以没有 swap 设备；产品内核此前
`CONFIG_ZRAM` 与 `CONFIG_ZSWAP` 都是关的。由此有两个实测后果：

- `systemd-oomd` 在跑（它被 `basic.target` 需要）却无事可做：PSI 编进内核了，
  但没有可换出的东西，它只剩「杀进程」一种手段。
- 任何一次浏览器标签量级的分配都会结束会话，而不是付出一点 CPU。

所以裁剪分两半：砍掉常驻的部分，再给内核一块压缩 swap 用来回收。

## 改了什么

**内核。** `device/configs/liuqin-memory.config` 加了 `ZRAM=y`（编译进内核而非模块：
生成器在 sysinit 阶段运行，而模块树被钉死在这个产品 release 上）、`ZSMALLOC=y`、
只保留 zstd 后端、`ZRAM_MULTI_COMP=y`（冷页二次压缩），并明确关掉 `ZSWAP`——那是给
本产品并不存在的 swap 设备做前置缓存。

`kernel/source.json` 里登记了这个 fragment 和新的配置标识。这个值是照着产品自己的流水线
重放出来的：`make defconfig`、`merge_config.sh` 按 fragment 列表合并、`make olddefconfig`，
用的是这个 release 使用的同一个编译器。**旧**列表的重放能逐字节复现上一版锁
（`29a4fd23…`），而新旧 `.config` 的差异正好是 zram 那一段，没有任何符号漂移。

**rootfs。** `device/configs/liuqin-root-trim.txt` 是镜像构建时在 ARM64 chroot 里执行的
清单（`tools/build-liuqin-native-root.sh` 的 `debs` 阶段）：purge、autoremove、
`apt-get check`，然后是一道闸门——只要有 `[keep]` 里的包消失、或有 `[purge]` 里的包
没被删掉，构建直接失败。同一份文件也会被装到设备的
`/usr/share/liuqin/root-trim.txt`，由 `/usr/local/sbin/liuqin-root-trim` 执行，这样
已安装的平板不重刷也能裁。

**overlay。** `liuqin-device-support` 现在真的会装出它一直想装的 `/etc/systemd` 屏蔽软链：
之前的拷贝循环只走 `-type f`，所以 `device/root-overlay` 里每一个 `… -> /dev/null`
都被静默丢掉，`unattended-upgrades`、`update-notifier-download.timer` 和两个
`apt-daily` 定时器一直在跑，而 git 里写着「已屏蔽」。现在循环会同时枚举文件与软链、
记录链接目标，native-root 构建器还会在组装后的树里断言这些屏蔽和
`zram-generator.conf` 都在。

## 8 GB 机器上的结果

以下是手工施加清单后的实测，完整数据见「验证状态」。

| 之后 | 空闲 | 变化 |
|---|---:|---:|
| 仅裁剪 | 总 PSS 1406 MB | 常驻 −680 MB（开着一个登录会话：2267 → 1406） |
| 裁剪 + zram | 同上，另加 3 GiB 压缩 swap | 浏览器量级的分配不再触发 OOM |

逐项理由（均为实测）：

- 去掉 snap：150 MB，外加整层 `/snap` 挂载。26.04 的 `firefox`、`thunderbird` 都是
  snap 转接包，所以删 `snapd` 会一并带走，浏览器怎么办见下文。
- 去掉 Evolution 组：244 MB。`gnome-shell` 只是 **Recommends**
  `evolution-data-server`，所以 shell 不受影响；代价是日历下拉和通讯录不工作。
- 去掉守护进程：190 MB，逐个用 `apt-get -s purge` 确认过没有一个反向依赖会把桌面带走。
- 屏蔽 `localsearch` 索引器：36 MB。包本身留着，因为 `nautilus` **Depends** 它；
  删包会连带删掉文件管理器、`ubuntu-session` 和 `xdg-desktop-portal-gnome`。

## 刻意保留的部分

- **`colord`**：删它会带走 `gnome-control-center`，而这个包正是本项目替换成电源键策略
  版本的那个。于是只屏蔽它的单元，设置里的「颜色」页会报守护进程不可用。
- **`localsearch` 这个包**（只屏蔽单元）：理由同上。
- **ibus**：98 MB 是这台没有实体键盘的平板跑中文输入法的代价，overlay 里的
  `screen-keyboard-enabled=true` 依赖它。
- **xdg portal、gvfs、PipeWire、`gdm3`、`systemd-oomd`、`power-profiles-daemon`、
  `iio-sensor-proxy`、`upower`、`polkit`**：会话、沙箱、音频、旋转和电源策略都走它们。
- **`ssh.service` 与 adbd**：一台没法进底座的设备的调试命脉。

## snap 删掉之后的浏览器

26.04 的 `firefox` 和 `chromium-browser` 都是 snap 转接包，所以删掉 `snapd` 就等于
删掉默认浏览器，而软件源里没有 deb 版 Firefox 或 Chromium。这台机器上实测（加载一个
页面，把所有子进程的 PSS 相加）：

| 浏览器 | 进程数 | 1 个页面 | 5 个标签 | 安装 |
|---|---:|---:|---:|---|
| Chrome 156（arm64 deb） | 12–15 | **421–452 MB** | **532 MB** | 厂商 deb，磁盘 131 MB，依赖已满足 |
| GNOME Web / Epiphany 49.2（WebKitGTK） | 18 | **815 MB**（应用 184 + WebKit 子进程 631） | 未测 | `epiphany-browser`，2 个包，3.4 MB |

两者在同一个会话、同一个页面下测得。**Chrome 反而更小**，这和通常的直觉相反，原因
看每进程拆分就清楚：WebKitGTK 会起一个网络进程加每个页面一个 WebContent 进程，每个
都映射整份 WebKit 和 JavaScriptCore 堆，所以 5 个 WebKit 进程比 4 个 Chrome 渲染进程
更贵。

所以这台平板的建议是 **装 Google 的 arm64 deb 版 Chrome**——不是因为它抽象意义上
“轻”，而是因为它是「现有两个选项里更小的那个」，同时正好满足你要的同步：

```sh
# 在平板上，此时 snapd 已经删掉
curl -LO https://dl.google.com/linux/direct/google-chrome-stable_current_arm64.deb
sudo apt-get install -y ./google-chrome-stable_current_arm64.deb
```

用 `apt-get install ./file.deb`（而不是 `dpkg -i`），这样依赖会从软件源解析。实测那台
机器的依赖已全部满足：`cups` 守护进程被删了，但 `libcups2t64` 这个库还在，因为它是库
不是守护进程。

依赖它之前要知道两件事：

- Google 的 arm64 包**不在**它的 apt 仓库索引里，是直链下载，因此不会随 `apt upgrade`
  更新。要更新就重新下载；Google 的仓库只提供 amd64。
- 在这个合成器上 Chrome 需要走 ozone Wayland 后端。先启动一次确认；如果它跑在
  Xwayland 里，就在 `~/.config/chrome-flags.conf` 加 `--ozone-platform=wayland`
  （Ubuntu 的 `google-chrome-stable` 包装脚本会读这个文件）。

如果干脆不想在镜像里带浏览器，那就两个都不要装：裁剪清单只负责删 `snapd`，不规定之后
装什么，镜像就是不带浏览器，由用户自选。我**刻意没有**把任何浏览器写进 `[purge]` 或
`[keep]`——这是用户决定而不是产品决定，何况两个候选差了一倍包数和一倍内存。

## 还能再省多少：第二轮实测

上一轮裁剪把空闲会话降到 1406 MB。第二轮专门找剩下的部分，每一改动都在平板上实测过才保留。
全部写在 `device/configs/liuqin-root-trim.txt` 的 `[mask-user]` 段，由
`device/tweaks/apply-root-tweaks.sh --user <账户>` 应用。

| 改动 | 省下 | 代价 |
|---|---:|---|
| 屏蔽 `gsd-{wwan,smartcard,sharing,print-notifications,usb-protection}` | 72 MB | 这台平板没有对应硬件；它们都是 `Wants` 不是 `Requires` |
| 屏蔽 `gsd-xsettings` | （含在 72 里） | 只为 X11 客户端提供 XSETTINGS，而 X11 层本来就不用 |
| 屏蔽 `gvfs-{afc,gphoto2,mtp,goa}-volume-monitor` | 36 MB | 无法作为 iOS/PTP/MTP 主机；goa 的在线账户后端已随 EDS 一起删掉 |
| 关闭 `ding@rastersoft.com` | 77 MB | 桌面图标；文件管理器和 dock 不受影响 |
| 关闭 `ubuntu-appindicators@ubuntu.com` | 99 MB | StatusNotifier 托盘图标；这个镜像里没有任何应用使用该协议 |
| 关闭 `snapd-prompting`、`snapd-search-provider` | 很小 | 它们为已被删除的包管理器保持 ACTIVE |
| **合计** | **约 212 MB** | 1406 → **1194 MB**（关掉终端后） |

最后两行是在前几项应用**之后**才发现的：`ding` 会把它俩盖在同一个统计桶里。那个
99 MB 的托盘宿主是整个会话里最大的单个进程，比合成器自己的辅助进程还大——在以后假设
「小扩展就是小」之前，这个数据值得记住。

有两项调查过但**放弃**了，因为数据不支持那点风险：

- **`Xwayland` + `mutter-x11-frames`（合计 117 MB）**。杀掉 `mutter-x11-frames`
  有效且不会自启；但 `Xwayland` 会按需重启——它由 Mutter 在 X11 客户端连接时启动，
  而 `gsd-xsettings` 不是触发者（屏蔽它没有任何变化）。当前会话里没有 X11 客户端，
  说明它是被 Mutter 自己的启动路径拉起来的，不是按需。要关掉需要 Mutter 的实验特性，
  上游并未稳定，所以留着。
- **`ibus`（69 MB）**。这是中文输入法。一台 `screen-keyboard-enabled=true`、没有实体
  键盘的平板必须留着，所以根本不是候选。

剩下的部分及其保留理由：

| 分组 | MB | 理由 |
|---|---:|---|
| `other`（约 95 个进程） | 291 | udisksd、NetworkManager、polkitd、iio-sensor-proxy、adbd、journald、gdm3、systemd 自身 |
| `gnome-shell` | 311 | 合成器与桌面本身 |
| X11 兼容层 | 121 | 见上 |
| `gsd-*`（剩 11 个） | 111 | 电源、多媒体键、键盘、rfkill、声音、颜色、时间、无障碍、屏保、磁盘工具、清理 |
| `xdg-desktop-portal*` | 113 | Flatpak、Waydroid 和沙箱应用都走这些 |
| `ibus` | 71 | 中文输入法 |
| 音频 | 67 | 四扬声器需要的 PipeWire + WirePlumber |
| `gjs`（剩 2 个） | 56 | shell 的通知与屏保辅助进程 |
| `gvfs` | 54 | 回收站、udisks2 卷监视、fuse、元数据 |

### 第二轮的验证

屏蔽和 dconf 键都确认能扛过重启：`gsd-*` 从 18 个降到 11 个，
`gvfs-*-volume-monitor` 从 5 个降到 1 个（只剩 udisks2），四个扩展都报 `INITIALIZED`
（已安装未运行的状态），会话正常启动，电源键、音量键、磁吸键盘、rfkill、自动旋转和
磁盘挂载都仍然可用。

让扩展列表扛过重启花了两处修正，都是**靠重启**而不是靠读代码发现的：
`apply-root-tweaks.sh` 假定自己是 root，以普通账户身份运行会失败（会话单元必须跳过系统
那一半，这就是 `--user-only` 的用途）；而按账户运行无法写 `/etc/dconf`，所以系统级 key
仍归安装包负责，会话单元只做单元屏蔽。`liuqin-session-tweaks.service` 就是首次登录时
做按账户这一半的单元——它覆盖的正是全新安装后 `gnome-initial-setup` 才创建的账户。

### Dock 和文件管理器在列 Android 分区

把 gvfs 卷监视器砍到只剩 udisks2，去掉了网络和媒体来源，但恰恰漏掉了这台设备上
最要紧的那一个。出厂分区表在内置 UFS 上有十二个带真实文件系统的分区——`metadata`、
`persist`、`persistbak`、`dsp_a`、`dsp_b`、`vm-bootsys_a`、`vm-bootsys_b`（ext4）、
`logfs`、`modem_a`、`modem_b`、`bluetooth_a`、`bluetooth_b`（vfat）以及 `cust`
（erofs）——udisks2 把每一个都当成可挂载卷报了出去。于是 dock 和文件管理器里出现了
一堆匿名的 `31 MB Volume`、`67 MB Volume`、`275 MB Volume`、`4.2 MB Volume`、
`168 MB Volume`，外加两个有名字的 `dsp` 和 `LOGFS`。

这些是固件，不是存储：对其中一个做读写挂载，很容易弄丢引导需要的分区。
`90-liuqin-hide-android-volumes.rules` 给它们设上 `UDISKS_IGNORE=1`，udisks2 会
完全跳过该设备，于是它从 udisks 里、从 GVfs 卷监视器里、进而从 dock 和文件管理器
侧栏里一起消失。

匹配范围是刻意收窄的：按 `DEVPATH` 里的内置 UFS 控制器（`*/1d84000.ufshc/*`）
匹配，而不是按 `sd*` 名字，因为内置磁盘在这里是 `sda`..`sdf`，一个笼统的
`sd[a-z][0-9]*` 会把插进接口的 U 盘也一起隐藏掉。`linux_root` 和 `linux_home`
被排除在外，系统自身的分区照常可见。设备节点没有任何改动——指纹运行时和启动工具
都是直接打开 `/dev/disk/by-partlabel/*`，从不经过 udisks。

用桌面读的同一个监视器实测：卷列表从 14 项变成 0 项。`tests/memory-features.py`
新增了 `volume-hiding` 特性，既检查规则内容，也在真实系统上检查全部十四个分区
加上两个必须保持可见的分区对应的 udev 数据库——规则文件只能证明意图，udev 数据库
才能证明它真的生效了。

### 唯一还能省更多的地方

这次测量里 `zram` 是空闲的（`mm_stat` 显示没有存储任何页），因为刚开机的系统还
没什么可回收。它的价值不在空闲数字——而在于浏览器量级的分配不再结束会话。再往后
真正能省的是换更轻的会话（用 wlroots 合成器替掉 `gnome-shell` + `gsd` + `gjs`），
[内存说明](MEMORY.zh-CN.md#换掉-gnome-值不值) 里已经估过约 600 MB——代价是作废
本项目长在 GNOME 里的那些集成。

## Plasma Mobile 迁移（2026-10-30）

会话曾是 GNOME Shell，后来 Plasma Mobile 与它并存，再之后 GNOME 与 Phosh 会话被移除。
8 GB 机器上的实测代价与收益：

| 指标 | 迁移前 | 迁移后 |
|---|---:|---:|
| 已安装包数（`dpkg-query -W`） | 2288 | 2098 |
| `/` 已用 / 可用（32 GB root） | 13 G / 19 G | 13 G / 20 G |
| 开机后 `free -m` 的 used | 1390–2267（见基线） | 2579 |

磁盘是净收益：一边装了 SDDM、Dolphin、Plasma 相机、Konsole、kcalc 和 kdialog，
一边删掉了 GNOME Shell 栈、Phosh、IBus 以及 GNOME 文档/语言包
（确切集合就是裁剪清单的 `[purge]`）。

内存没有变好。开机空载的每进程 RSS（`ps -eo rss,comm`，与上面用 PSS 的基线不可直接比较）：
`plasmashell` 464 MB、`kwin_wayland` 241、`kded6` 160、`org_kde_powerdevil` 147、
`polkit-kde-authentication-agent` 145、`kactivitymanagerd` 141、`xdg-desktop-portal` 138、
`ksecretd` 136、`gmenudbusmenuproxy` 132、`xembedsniproxy` 132、`ksmserver` 125、
`Xwayland` 98、`fcitx5` 77。下一步是补一次 PSS 测量并审查候选屏蔽项
（`kactivitymanagerd`、`gmenudbusmenuproxy`、`xembedsniproxy`、KWallet 与仍为
libsecret 保留的 gnome-keyring）；这些目前都没有写进
`device/configs/liuqin-root-trim.txt`，因为还没有按屏蔽后的空载基线测过。
那一轮现在做完了：数字见下面的「Plasma Mobile 的空载常驻」，其中包括
唯一一个会把会话搞死的屏蔽项。

有两处 GNOME 专属部件必须跟着会话一起搬，而不是删掉：

- 第一阶段准入契约把 `gdm3`、`gnome-shell` 和
  `display-manager.service -> gdm3.service` 当成桌面写死；现在钉的是 `sddm`、
  `kwin_wayland`、`plasmashell`、`startplasmamobile` 和
  `display-manager.service -> sddm.service`（`initramfs/init` 的 native 配置）；
- 电源键助手原来驱动 `org.gnome.ScreenSaver` 和 Mutter 的 DPMS，现在驱动
  `org.freedesktop.ScreenSaver`（KWin 拥有该名字）和 `kscreen-doctor --dpms`，
  并让 PowerDevil `PowerButtonAction=0`，避免它对同一个键再动作一次。
  真机验证：按下 → 上锁并关屏，再按 → 亮屏停在锁屏，再按 → 关屏，再按 → 亮屏。

## Plasma Mobile 的空载常驻（2026-10-30 实测）

迁移留下的问题是「空载的 Plasma Mobile 会话到底吃多少，还能再拿掉什么」。
本节就是那次测量。方法：从 `/proc/<pid>/smaps_rollup` 取每个进程的 PSS，按进程所属的
systemd 单元聚合，在不开任何应用的真机上取值。用 PSS 而不是 RSS，两个进程共享的库
不会被算两遍。

### 当时在跑、但不该在跑的东西

迁移换掉了 GNOME 会话，也顺手换掉了裁剪清单攒下来的全部按账号屏蔽项：
`[mask-user]` 只剩一条（`baloo_file.desktop`），而会话里又跑起了 X11 兼容层、
GNOME 时代的 gvfs 后端、两个 ssh agent、一个 SPICE guest agent 和 KDE 钱包解锁。
逐项单独停掉，记录总 PSS 的下降：

| 移除项 | MB | 为什么不需要 |
|---|---:|---|
| `plasma-xembedsniproxy` | 34 | X11 托盘协议；这里没有 X11 客户端 |
| `plasma-gmenudbusmenuproxy` | 29 | 把 GTK 应用菜单导出给 Plasma；Plasma Mobile 没有菜单栏 |
| `gvfs-{afc,gphoto2,goa,mtp}-volume-monitor` | 35 | iOS/PTP/MTP/在线账号宿主机，随 GNOME 会话一起没了 |
| `ksecretd` + `kwalletd6` | 51 + 31 | `org.freedesktop.secrets` 属于 `gnome-keyring`；钱包只是被登录解锁拉起来的 |
| `ssh-agent` + `gcr-ssh-agent` | 4 + 3 | 两个 agent，都没有客户端 |
| `obexd` | 15 | 蓝牙对象推送；`kill` 掉会立刻自激活重启 |
| `spice-vdagent` | 很小 | 物理机上的 QEMU guest agent；直接 purge，未单独测量 |
| `geoclue-demo-agent` | 11 | geoclue 的示例客户端，不是 geoclue 本体 |
| `ubuntu-insights-collect` | 峰值 116 | Ubuntu 遥测；该单元自己的日志里记着每次开机 116.2 MB 峰值 |

`ksecretd` 与 `kwalletd6` 值得单独说明，因为「停掉」和「从来不会启动」是两回事：

- `ksecretd` 由 `kwallet6` 的 portal 后端经 D-Bus 激活，没有对应的 unit。
  只 `kill` 它并不能说明它属于空载基线；真正把它移出空载的是屏蔽登录解锁
  （`pam_kwallet_init.desktop`、`plasma-kwallet-pam.service`）。它仍然可被激活，
  所以真要 KDE 钱包的应用照样拿得到。
- `xdg-document-portal` 与 `xdg-permission-store`（合计 26 MB）属于本项目特意保留的
  沙箱路径（Waydroid、flatpak），所以**留着**。不需要它们的机器再加两行
  `[mask-user]` 就能拿掉。

### 会把会话搞死的那一条屏蔽

`plasma-kactivitymanagerd.service` 原本是最大的单个候选（43 MB，而且这台平板在界面上
根本没有「活动」概念），而在运行中的会话里 `systemctl stop` 它看不出任何后果。
屏蔽就不一样了：

```
plasmashell[8269]: Aborting shell load: The activity manager daemon
                   (kactivitymanagerd) is not running.
```

plasmashell 随后只占 50 MB、黑屏，屏幕上只剩屏幕键盘的开关按钮。
所以它**不在**裁剪清单里，而且 `tests/memory-features.py` 现在反过来断言：
裁剪清单不得屏蔽它 —— 免得下一次照着进程表抄的时候，又把这 43 MB 抄进去。

### 屏幕键盘每小时漏 30 MB

`mytouchinput` 开机跑五小时后常驻 250 MB，而刚启动时只有 48 MB；空载下实测以 8.4 KB/s
稳定增长。原因是主循环每 20 ms 做一次 `wl_display.sync` 往返（50 次/秒），
Go 的 Wayland 客户端每次 sync 都在对象表里注册一个新的 callback 代理，而没有任何地方
注销它。`GODEBUG=gctrace=1` 显示存活堆涨过了它本该持有的两张 7.8 MB 帧图：

| | GC 后的存活堆 | +200 s 时 RSS | +5.5 h 时 RSS |
|---|---:|---:|---:|
| 修复前（`roundtrip` 从不销毁） | 120 s 内 15 MB → 16 MB | 53.7 MB | 267 MB |
| 修复后（每条路径都 `callback.Destroy()`） | 稳定在 15 MB | 47.8 MB | （不再增长） |

修复只是一次调用，外加把轮询频率按实测调低：这个循环 idle 时还烧掉 2.7% 的一个核，
所以空转间隔从 20 ms 改成 50 ms。改完实测：**每 60 s 66 个 CPU tick，原来 163**（单核 1.1%），
RSS 稳定在 36–48 MB。`device/touchinput/README.md` 里描述的帧回调架构能彻底去掉轮询，
但那是重写，不是修漏 —— 而漏才是无界增长的那一半。

### 透明大页把整个会话向上取整了

`kernel/source.json` 的 fragment 列表里带着发行版默认的
`CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS=y`：它给每个匿名映射都配 2 MiB 页，不管对方要不要。
在 6.3 GiB `MemTotal` 的机器上这在每个进程上都看得见
（`gvfs-mtp-volume-monitor`：8.5 MB 匿名内存里有 8 MB 是大页；`polkitd`：12.9 MB 里 12 MB），
整个会话有 1360 MB 是大页支撑的。

同一次开机内交替切换 sysfs 策略、连续重启四次 `plasmashell` 的 A/B：

| `transparent_hugepage/enabled` | plasmashell PSS | RSS | 其中大页 |
|---|---:|---:|---:|
| `always`，第 1 次 | 309 MB | 426 MB | 206 MB |
| `madvise`，第 1 次 | 263 MB | 380 MB | 126 MB |
| `always`，第 2 次 | 311 MB | 429 MB | 208 MB |
| `madvise`，第 2 次 | 264 MB | 381 MB | 126 MB |

`device/root-overlay/etc/tmpfiles.d/90-liuqin-thp.conf` 在每次开机时把策略钉成 `madvise`，
并关掉 khugepaged 的 defrag。内核默认值没有动，因为改它要重编钉住的內核；
tmpfiles 的写入发生在会话之前，而那是唯一有意义的窗口。
KWin 同理跟着降，只是它自己的数字会随会话画过什么而变（刚启动 134 MB，
开过启动器和任务切换器后 220 MB）。

### 端到端

同一台平板、同一批单元、不开应用，两行都是整个会话所有进程求和：

| | 这轮之前 | 之后 |
|---|---:|---:|
| 总 PSS（只算桌面，排除用户自带服务） | 1849 MB | 1340–1375 MB |
| `mytouchinput` | 250 MB，以 8.4 KB/s 增长 | 37 MB，不再增长 |
| `plasmashell` | 362 MB | 263–272 MB |
| `kwin_wayland` | 194 MB | 134–220 MB |
| 会话内进程数 | 100 | 70 |

剩下的部分与理由（空载会话 PSS 前列）：

| 单元 | MB | 为什么留着 |
|---|---:|---|
| `plasmashell` | 263–272 | 外壳本体；`kactivitymanagerd` 才让它起得来 |
| `kwin_wayland` | 134–220 | 合成器 |
| `fcitx5` | 63 | 屏幕键盘打中文要走它 |
| `kded6` | 60 | kscreen、自动挂载、网络状态、mpris、托盘监视 |
| `org_kde_powerdevil` | 57 | 亮度、闲置策略、电池 |
| `polkit-kde-agent` | 54 | 授权弹窗 |
| `xdg-desktop-portal*` | 79 | 为沙箱应用保留的 portal 路径 |
| `kactivitymanagerd` | 51 | plasmashell 硬性要求，见上 |
| `ksmserver` | 44 | 会话管理 |
| `Xwayland` | 44 | KWin 自己拉起的，不是按需（此前已否决，结论仍然成立） |
| `wireplumber` + `pipewire` | 57 | 四扬声器 |
| `mytouchinput` | 37 | 键盘：两张 7.8 MB 帧图加运行时 |
| `udisks2`、`NetworkManager`、`adbd`、`upowerd`、journald | 100 | 机器本身 |

### 精简 Plasma 自身：什么动得了，什么动不了

会话级屏蔽做完之后，把剩下的 Plasma 进程逐个看过。三个结论，没有一个是大的：

- **kded6 模块。** 登录时加载 18 个模块，其中七个服务于这个镜像没有的硬件或行为
  （为裁剪清单已删的 modem 猜 APN、捐款提示、被存储守护替换的低磁盘提醒、发行版升级才动的
  look-and-feel 切换器）。`/etc/xdg/kdedrc` 把它们关掉，模块集降到 11 个，但 kded6 自身的
  PSS 并没有跑出它重启间的波动范围（全加载 64 MB，11 个模块时 55–75 MB）：
  这个守护的大部分是它与整个会话共享的 Qt/KIO/Framework 库。发它是因为行为，不是为了字节。
- **KWin 特效。** 这里根本没加载 blur（Plasma Mobile 不用），而 KWin 已加载的 29 个特效里
  只有 `mobiletaskswitcher` 会变成 active。没有一堆闲置特效可以关。
- **KWin 插件。** 合成器映射了键盘无障碍插件（`MouseKeys`、`StickyKeys`、`SlowKeys`、
  `BounceKeys`）、`krunnerintegration`、`TouchpadShortcuts`、`nightlight`、`screenshot`、
  `screencast`。其中三个服务于这台平板没有的硬件（触摸板、物理键盘 krunner 快捷键），
  但它们很小、拉进来的代码又与 `libkwin` 共享，所以没动。

测量同时说明了**压力不在哪里**：外壳（`plasmashell`）加合成器一共 400–490 MB，而这是会话
必须要的；`fcitx5` 是 47–63 MB，是中文输入法；其余都是 10–50 MB 的守护。
这正是下面那轮 zram 回收的理由：在这个桌面上，剩下的空间在“有多少是**常驻**的”，
而不在“加载了什么”。

有三样识别出来了但选择不动：`at-spi`（16 MB，无障碍不是内存 bug）、
`packagekitd`（16 MB，D-Bus 按需激活，Plasma 的更新界面要和它说话），
以及上面的 document portal 一对。`adb` 留着，因为这台设备就是靠它调试的。

开机后连续几次 `free -m` 会往上飘，因为外壳在预渲染（2 分钟时 `used` 1493 MB，
17 分钟、且开过一次启动器和任务切换器后 2156 MB）。有意义的是上面的 PSS 表；
`free` 把共享缓冲和 slab 都算进去了。

### 内核不会自己把页交出来：把空载会话“圆整”进 zram

即使做了上面所有事，内核仍然什么都不还：整整一次开机 `zram` 的已存字节都是 **0**，
因为“把页交给 swap”是对内存压力的反应，而空载平板没有压力。内核里已经有现成机制
（`memory.reclaim` 进主线于 5.19）：按 cgroup、按需触发，不需要桌面配合。
Android 解决同一个问题用的是对后台进程 `madvise(MADV_PAGEOUT)`。

这个写操作可以带一个 swap 提示，而提示才是关键：
`echo "516M swappiness=200" > /sys/fs/cgroup/user.slice/memory.reclaim`
让内核优先选择匿名页而不是 page cache。

| 轮次 | 请求量 | 会话 `memory.current` | 其中匿名 | 其中 page cache | 之后 zram |
|---|---:|---:|---:|---:|---:|
| 首次，开机 3 分钟 | 516 MB (8 %) | 2320 → 1779 MB | −116 MB | −306 MB | 17 MB |
| 周期，2 % | 129 MB | 1795 → 1666 MB | −125 MB | −1 MB | 26 MB |

首次那一轮主要吃 page cache：开机时它持有的一切都是几秒前刚碰过的，而 page cache 本来
就算在 `MemAvailable` 里 —— 所以它真实收益是匿名页那一部分。因此策略是 `MemTotal` 的
**4 % / 2 %**：匿名收益相同，丢弃的缓存减半。真正把长会话圆整起来的是周期性轮次，
到那时目标里已经没有热页，内核几乎只拿匿名页（上表第三列：一次写入、−125 MB、零缓存）。

那一次开机总 PSS 从 **1484 → 1224 MB**（第二轮后到 1094 MB），`MemAvailable`
4116 → 4332 MB，代价是 17–26 MB 的 zram，桌面完全不参与。

能挖到多深（在同一会话中手工写更大目标）：累计回收 840 MB 后，同一会话降到
**660 MB PSS、4856 MB `MemAvailable`，711 MB 匿名内存装在 52 MB 的 zram 里（13.6:1）**。
这是天花板而不是策略：越过拐点多余轮次就找不到匿名页、开始丢 page cache，
而那买不到任何东西（缓存本来就是 `MemAvailable`），回来时还要多一次 UFS 读。

代价实测（回收前后做同样的事）：

| 交互 | 回收前 | 回收后 |
|---|---|---|
| 连续开启动器 ×4，plasmashell CPU tick | 56 / 41 / 40 / 47 | 45 / 45 / 39 / 42 |

100 tick 是一秒 CPU，也就是启动器每次 ~0.4–0.5 s 的 plasmashell CPU，回收没有带来可测量
的差别。越界就是另一回事了：同一会话里的第三轮 200 MB 只给 zram 加了 3 MB，却掉了
116 MB PSS —— 那是在拿 page cache。

`liuqin-memory-reclaim` 就是这套机制：一个 oneshot 服务加一个 timer
（`OnBootSec=180s`，之后每 30 分钟）。它刻意保守 —— `swappiness=200` 偏向匿名页、
目标按 `MemTotal` 比例算、CPU 压力高于 20 % 就跳过、目标完不成时用 `EAGAIN` 二分回退
（内核会先把能拿的拿完再返回失败）、没有 swap 的内核或布局静默退出。每轮把拿走的量
按匿名/缓存两半记进 journal，所以 journal 本身就是测量：

```
rounded first: session 2320 -> 1779 MB (took 541 MB of 516 asked;
  anon 885 -> 769, file 1390 -> 1084), zram 0 -> 17 MB
rounded later: session 1795 -> 1666 MB (took 129 MB of 129 asked;
  anon 683 -> 558, file 1077 -> 1073), zram 17 -> 26 MB
```

## 回退

每一步都只是包名。

```sh
sudo liuqin-root-trim --dry-run     # 先看会删什么
sudo liuqin-root-trim               # 执行，然后重启
sudo apt-get install snapd firefox  # 装回某个组件
sudo rm /etc/systemd/user/localsearch-3.service   # 解除对索引器的屏蔽
```

按账号的条目不过是账号自己目录下的符号链接和一行 desktop 文件，所以撤销一条就是一个 `rm`，
被删掉的服务下一次启动时会自己把缓存写回来：

```sh
sudo rm /etc/tmpfiles.d/90-liuqin-thp.conf   # 让内核默认值重新生效
rm ~/.config/systemd/user/plasma-xembedsniproxy.service   # 撤销一条屏蔽
rm ~/.config/autostart/pam_kwallet_init.desktop           # 撤销一条自启动隐藏
systemctl --user daemon-reload                           # 改完任一目录后执行
```

`/sys/kernel/mm/transparent_hugepage/enabled` 可以不重启就改回 `always` 做 A/B；
重启之后由 tmpfiles 那个文件决定。

内核侧没法在运行时回退：需要重新构建（`tools/build-liuqin-kernel.py`）并刷 boot 镜像。
没有这一步时 rootfs 照样能裁，`/usr/local/sbin/liuqin-root-trim` 会如实报告
`/sys/block/zram0` 不存在，而不是假装有 swap。

## 验证状态

以下数据来自平板实测（8 GB 版本）。裁剪是手工施加的（`liuqin-root-trim` 加上下面提到的
四个传感器库），重启进入用户会话、不开任何应用、开机约 2 分钟：

| | 裁剪前 | 裁剪后 |
|---|---:|---:|
| 总 PSS | 2267 MB（开了设置和终端）/ 空闲登录界面 1420 MB | 1406 MB |
| `free -m` available | 4625 MB | 4348 MB，同时相同运行时长下 `buff/cache` 多了约 2 GiB |
| 运行中的服务 | 42 个系统 + 55 个用户 | 25 个系统 + 31 个用户 |
| swap | 无，`CONFIG_ZRAM` 关闭 | `systemd-zram-generator` 能生成 `dev-zram0.swap`；内核重编前设备建不出来 |

裁剪后的分组：GNOME shell 与会话 553 MB、`gsd-*` 199 MB、ibus 99 MB、
xdg portal 97 MB、gvfs 94 MB、音频 69 MB、evolution 29 MB、可裁守护进程 7 MB。

手工跑一遍才发现两个清单本身看不出来的问题：

- **`liuqin-sensors` 少声明了依赖库。** `ssccli` 和 SSC 版 `iio-sensor-proxy` 还链接
  `libqmi-glib5` 与 `libqrtr-glib0`，这两个库此前只是作为 `modemmanager`/`fwupd`
  的残留存在。把这两个包删掉之后，两个二进制都 exit 127，加速度计采样闸门 fail-closed，
  `iio-sensor-proxy` 再也起不来，自动旋转消失、指纹启动闸门跟着失败。已在
  `tools/build-liuqin-debs.sh` 修正（Depends 加上 `ldd` 完备性闸门），并把四个库写进
  裁剪清单的 `[keep]`。
- **`evolution-data-server-common` 不能删。** `libedataserver` 客户端库在这个包里，
  `gnome-shell`、`gdm3`、`ubuntu-session` 都链接它；删包会连带删掉这三个。
  `[purge]` 里只留 `evolution-data-server` 本身。

### 内核重编与部署

内核已经重编并刷入，zram 在真机上就是活的：

| | 结果 |
|---|---|
| 构建 | `tools/build-liuqin-kernel.py` 对齐锁定 commit，`aarch64-linux-gnu-gcc-13`，`.config` 哈希 `fa931ca5…` 与锁一致 |
| 模块集 | 481 个模块，与运行系统完全一致，只有 build-id 字节不同 |
| release | 仍是 `6.17.0-rc1-gfe81794b5e1b`，所以 rootfs 与内核仍然匹配 |
| 部署 | `tools/deploy-liuqin-boot.py`：复用设备已验证 bundle 的 ramdisk 与 DTB，只替换内核，整分区写入后回读比对 |
| `/sys/block/zram0` | 存在，3221225472 字节（3 GiB），`comp_algorithm` = `[zstd]`，swap 优先级 100 |
| 回收 | 一个 Python 进程分配 6720 MiB 匿名内存（超过 `MemTotal`）并正常跑完；`zram0` 里 320 MB swap、压缩比 19.24:1，会话没有被杀 |
| `systemd-oomd` | active，而且现在有可回收的东西，不再只剩「杀」这一种手段 |

内核侧的配置重放与 `.config` 差异已在开发机上复现。上面的裁剪后数据是「在已安装的
0.6.0 root 上手工裁剪」的实测，不是重出镜像的验收；zram 的数据来自重编并刷入的内核。

### 重新安装一遍，这些定制是不是都有？

这正是这道闸门要回答的问题，而且现在它是被**校验**的，不是被假设的。
`tests/memory-features.py` 把每个定制项和它的证据列在一起，跨三个层面：

| 特性 | 证据 |
|---|---|
| `zram-swap` | 生成的 `.config` 里有 `CONFIG_ZRAM`/`ZSMALLOC`/`ZRAM_BACKEND_ZSTD`/`ZRAM_DEF_COMP_ZSTD`，`CONFIG_ZSWAP` 关闭，`/etc/systemd/zram-generator.conf` 选 zstd，装了 `systemd-zram-generator` |
| `rootfs-trim` | 裁剪清单与 `liuqin-root-trim` 已安装，`/snap`、`/var/lib/snapd`、`snap-confine` 不存在，`[purge]` 里的包确实没装，`[keep]` 里的包和四个传感器库都在 |
| `unit-masks` | 凡 `usr/lib/systemd` 里还有对应单元的，`etc/systemd` 必须有指向 `/dev/null` 的软链。这是**条件式**的：包都删了还去断言屏蔽毫无意义 |
| `session-trim` | 裁剪清单里点名了每一条 `[mask-user]` 单元与自启动项；在真机上每个账号的 `~/.config/systemd/user` 有 `/dev/null` 屏蔽、`~/.config/autostart` 有 `Hidden=true` 覆盖，并且反过来断言 `kactivitymanagerd` **没有**被屏蔽——屏蔽它会让外壳黑屏 |
| `hugepage-policy` | `/etc/tmpfiles.d/90-liuqin-thp.conf` 把策略钉成 `madvise`；在真机上 `/sys/kernel/mm/transparent_hugepage/enabled` 报告 `[madvise]`，这一半才能证明写入真的跑了，而不是只存在一个文件 |
| `idle-reclaim` | helper、service、timer 都已安装，**并且** `timers.target.wants` 里有链接：只装上 timer 不等于它会跑。每轮把拿走的量按匿名/缓存两半记进 journal |
| `kded-modules` | `/etc/xdg/kdedrc` 关掉服务于本镜像没有的硬件/行为的模块；门禁断言文件存在以及 APN 模块的 id——写错的模块 id 会被静默忽略而不是报错 |

它在三个地方跑：

- **作为构建阶段。** `tools/build-liuqin-image.py` 把它作为 `--stage features`，排在
  `manifest` 与 `boot` 之间，对着组装好的 root 和它真实的 dpkg 数据库跑。某个定制
  不再落地时，失败的是镜像构建，而不是发布。
- **在 CI 里。** `.github/workflows/checks.yml` 读同一张特性表：谁改内核 fragment 或
  裁剪清单、把某个特性符号或某个 `[keep]` 包弄丢了，PR 直接失败。
- **在平板上。** 这个文件是可移植的，推上去对着 `/` 跑即可：
  `adb -s liuqin push tests/memory-features.py /tmp/`，然后
  `adb -s liuqin shell 'python3 /tmp/memory-features.py --config /proc/config.gz --root / --packages'`。
  要用 root 跑。指纹固件缓存是 `0700` 目录里的 `0600` 文件，普通账号 stat 不到；门禁
  现在会报 `cannot be inspected without root`，而不是把文件说成缺失——它以前就是这么说
  的，于是权限问题看起来像回归。
  在本次实测的那台机器上，五项特性全部通过，包括 `volume-hiding`；它的 udev 部分只在
  `--root` 指向正在运行的系统时才会检查。
  被直接删掉的。这两项都来自仓库里的清单，所以**用当前这棵树构建的 bundle 里都有**；
  眼前这台机器是拿旧镜像手工裁的。

`bundle.json` 里带 `zram_swap`、`rootfs_trim`、`unit_masks` 三个字段，`install-liuqin.py`
在写盘之前就会打印这个 bundle 到底有什么——发布页上那个 0.6.0 bundle 没有这三个字段，
而旧 bundle 不应该看起来像是有的。

以后任何内核改动，重新部署：

```sh
python3 tools/build-liuqin-kernel.py --source ../linux-sm8450-liuqin --out out/kernel
python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel --dry-run   # 只构建并校验
python3 tools/deploy-liuqin-boot.py --kernel-out out/kernel             # 写入、校验、重启
```

`deploy-liuqin-boot.py` 在写入前会把现行 `boot_a` 存到 `backups/liuqin-boot/`；当内核构建
与 `kernel/source.json` 不匹配时它会拒绝执行。它只写 `boot_a`：`boot_b` 保留引导程序的
回退副本，那是镜像加载失败时的退路。
