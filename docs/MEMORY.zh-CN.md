# 内存：占用在哪，这个产品砍掉什么

本文是 `device/configs/` 里几张裁剪清单的证据来源：

| 文件 | 作用对象 |
|---|---|
| `device/configs/liuqin-memory.config` | 内核（`CONFIG_ZRAM`、zstd、multi-comp） |
| `device/configs/liuqin-root-trim.txt` | rootfs 软件包（`[purge]` / `[keep]`） |
| `device/gnome-overlay/etc/systemd/zram-generator.conf` | 已安装系统的 swap 形状 |
| `device/gnome-overlay/etc/systemd/**` 指向 `/dev/null` 的软链 | 不删包、只屏蔽的单元 |

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
之前的拷贝循环只走 `-type f`，所以 `device/gnome-overlay` 里每一个 `… -> /dev/null`
都被静默丢掉，`unattended-upgrades`、`update-notifier-download.timer` 和两个
`apt-daily` 定时器一直在跑，而 git 里写着「已屏蔽」。现在循环会同时枚举文件与软链、
记录链接目标，native-root 构建器还会在组装后的树里断言这些屏蔽和
`zram-generator.conf` 都在。

## 8 GB 机器上的预期

| 之后 | 空闲 | 变化 |
|---|---:|---:|
| 仅裁剪 | ~1.7 GB | 常驻 −580 MB |
| 裁剪 + zram | ~1.7 GB + 3 GiB 压缩 swap | 浏览器量级的分配不再触发 OOM |

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

26.04 的 `firefox` 和 `chromium-browser` 都是 snap 转接包，`snapd` 一旦删掉，
软件源里就没有可装的浏览器了。按代价从小到大：装 `resolute` 里真实存在的 deb 浏览器
（`epiphany-browser` 是 WebKitGTK，无 snap，常驻约 60 MB）、或加 Mozilla 官方 APT 源
装真 `.deb` Firefox、或干脆不带浏览器让用户自己选。本仓库不替用户做这个决定——决定点
就在裁剪清单里。

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

- 配置重放与 `.config` 差异：已在开发机上复现，见上文。
- 裁剪清单在设备上按单包、按整组用 `apt-get -s purge` 核对过；
  `liuqin-root-trim --dry-run` 能在平板上解析安装包内附的清单。
- 常驻内存数字来自正在运行的 0.6.0 rootfs；裁剪后的数字是各分组实测 PSS 的算术结果，
  还不是裁剪镜像的验收测量。
