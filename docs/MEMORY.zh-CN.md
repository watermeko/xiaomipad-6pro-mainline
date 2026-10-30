# 内存：占用在哪，这个产品砍掉什么

本文是 `device/configs/` 里几张裁剪清单的证据来源：

| 文件 | 作用对象 |
|---|---|
| `device/configs/liuqin-memory.config` | 内核（`CONFIG_ZRAM`、zstd、multi-comp） |
| `device/configs/liuqin-root-trim.txt` | rootfs 软件包（`[purge]` / `[keep]`） |
| `device/root-overlay/etc/systemd/zram-generator.conf` | 已安装系统的 swap 形状 |
| `device/root-overlay/etc/systemd/**` 指向 `/dev/null` 的软链 | 不删包、只屏蔽的单元 |

## 实测基线

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

## 换掉 GNOME 值不值

在这台机器上实测，内核之上的整个 GNOME 栈约 755 MB。wlroots 一类会话
（labwc 或 niri + waybar + foot）空载约 100–150 MB，天花板也就是 ~600 MB——比 zram
单独带来的收益还少，而且它会作废本项目长在 GNOME 里面的那几块：`gdm3` + 指纹登录、
`gnome-initial-setup` 首次开机、dconf 电源策略、打过补丁的 `gnome-control-center`
电源面板、屏幕键盘和 2× 缩放策略。连发行版一起换则是另一个量级的工作：rootfs 流水线
是从 Ubuntu casper 镜像构建的（`tools/build-liuqin-ubuntu-desktop-rootfs.sh`）。

如果以后还是要放弃 GNOME，成本更低的顺序是：留着 `gdm3` 与 PAM 栈（它们与具体桌面无关），
加一个 wlroots 会话并设为默认，GNOME 会话仍可切换。那是「换会话」，不是「换发行版」，
既不动内核也不动 rootfs 流水线。

## 回退

每一步都只是包名。

```sh
sudo liuqin-root-trim --dry-run     # 先看会删什么
sudo liuqin-root-trim               # 执行，然后重启
sudo apt-get install snapd firefox  # 装回某个组件
sudo rm /etc/systemd/user/localsearch-3.service   # 解除对索引器的屏蔽
```

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
