# 挂起与唤醒

平板会挂起到 PSCI 深度睡眠，唤醒后一切恢复。它**没有**做到的是让平台真正进入低功耗状态：固件只让应用处理器睡下就停手了，所以挂着的时候整机仍有约 121 mA。下面两部分都有实测数据，因为第二半决定这个功能到底值不值。

## 现在的行为

`/sys/power/mem_sleep` 选的是 `deep`，一次挂起会走 `psci_system_suspend`：所有非引导 CPU 下线、应用处理器交给固件、PMIC 继续数时间，唤醒约需半秒。`s2idle` 仍可选来调试，但随镜像发布的策略不用它。

"什么时候睡"由两个文件决定：

| 路径 | 由谁决定 |
| --- | --- |
| `device/root-overlay/etc/xdg/powerdevilrc` | PowerDevil：电池下空闲 5 分钟、充电器下 15 分钟就睡（`AutoSuspendAction=1`）；翻盖保护套用 `LidAction=1`；`PowerButtonAction=0` 是因为电源键归 `liuqin-power-keyd` |
| `device/root-overlay/etc/systemd/logind.conf.d/90-liuqin.conf` | logind：`HandleLidSwitch=suspend`，作为会话出现之前（PowerDevil 的 lid 抑制器还不存在时）的兜底 |

接外接显示器时 PowerDevil 保持默认的 `InhibitLidActionWhenExternalMonitorPresent=true`，桌面场景合盖不会让平板睡着。电源键短按默认仍是熄屏锁屏；`gsettings set io.github.liuqin.power short-press-action suspend` 可以让它改为挂起。

唤醒源来自设备树而不是用户态，所以不依赖"睡下去时谁在监听"：

| 唤醒源 | 注册名 | 是否实测 |
| --- | --- | --- |
| PMIC RTC 闹钟 | `c400000.spmi:pmic@0:rtc@6100`、`alarmtimer.0.auto` | 是——下文每次测量都是它唤醒的 |
| 电源键 | `...pmic@0:pon@1300:pwrkey` | 是——2026-09-17 一次短按结束了一次数小时的睡眠 |
| 翻盖保护套 | `gpio-keys` 的 `SW_LID`，设备树里带 `wakeup-source` | 否（需要保护套） |
| 音量加、resin | `gpio-keys`、`...pon@1300:resin` | 否 |
| 磁吸键盘 | `4-004c`，`wake-gpios = <&tlmm 42>` | 否 |

充电器的 UCSI 端口、电池管理、MHI 和三个 remoteproc 同样是唤醒源。正是 `qcom-battmgr-bat` 每几分钟把 AP 叫醒，让一次 25 分钟的挂起在 5 分 45 秒后结束，所以 `liuqin-wakeup-sources` 解除了电池与无线充的唤醒权限，只保留 VBUS 与 Type-C 端口——插充电器仍然能唤醒平板。

## 已验证的内容

| 结论 | 证据 |
| --- | --- |
| 进的是 `deep` 而不是 `s2idle` | `PM: suspend entry (deep)`、`psci: CPU1..7 killed`、单调时钟停走 |
| 睡满了请求的时长 | 40 s → 43 s、45 s → 48 s、90 s → 94 s、420 s → 422 s、900 s → 902 s（RTC 秒） |
| 唤醒后一切恢复 | 每次运行后触摸、手写笔、键盘、触控板、Wi-Fi（含地址）与屏幕都回来；`suspend_stats` 每次计 1 次成功、0 次失败 |
| 空闲策略会触发 | 装好随镜像发布的文件后，开机 900 s 时 PowerDevil 请求睡眠，随后 `PM: suspend entry (deep)` |
| 无人打扰的唤醒会重新睡回去 | 2026-11-01 连续 12 次无人唤醒里 `liuqin-sleep-guard` 都先把锁屏的背光熄掉再让平板睡回去，每轮睡 113–162 s |
| 深度睡眠在分钟尺度稳定 | 四种配置下共 12 次 240 s 挂起，全部睡了 233–244 s |
| 可以累积 | 19 次串联挂起在 9126 s 窗口里睡了 9087 s |

`tests/suspend-resume.py` 是必须持续通过的检查：

```sh
python3 tests/suspend-resume.py --policy                  # 离线检查，CI 也跑
python3 tests/suspend-resume.py --cycle 60                # 一次完整往返
python3 tests/suspend-resume.py --drain 1200              # 睡眠功耗
```

`--cycle` 会在这些情况下失败：内核没进请求的状态、RTC 睡的时间短于请求、`suspend_stats` 记了失败、或者触摸/手写笔/键盘/触控板/Wi-Fi/屏幕没回来。`--drain` 会先固定被测状态（`--drain-state deep|s2idle`），打印这个窗口能分辨的分辨率，并在没有睡满或功耗超预算时失败。

功耗要测数小时，而启动它的会话会随 USB gadget 一起消失，所以可以先在充电状态下布好、让它拔线后自己开始：

```sh
adb -s liuqin push tests/suspend-resume.py /tmp/
adb -s liuqin shell 'systemd-run --unit=liuqin-drain --collect /usr/bin/python3 \
    /tmp/suspend-resume.py --drain 10800 --wait-for-battery 3600'
# 拔掉线：它自己设闹钟、挂起，日志进 journal
adb -s liuqin shell 'journalctl -u liuqin-drain --no-pager'
```

## 成本

| 状态 | 电流 | 折算 |
| --- | --- | --- |
| 清醒、屏幕熄灭、Wi-Fi 关联 | 223.6 / 226.9 mA | 3.0 %/h |
| `deep` 睡眠（2.54 h 窗口，睡了 9087 s） | **121 mA** | **1.6 %/h** |
| `s2idle`，同样方法（5 × 604 s） | 131 mA | 1.7 %/h |

`deep` 的数字来自 19 次串联挂起：9126 s 的窗口里累积睡了 9087 s，电量计走了 307 mAh（6952 → 6645，92 % → 88 %）。按电量计学到的 7519 mAh 折算就是 121 mA。

也就是说挂起只省了大约一半，而不是一台真正睡着的平板该有的十倍；而"让 SoC 继续跑"的 `s2idle` 代价一样。电量计每步约 30 mAh，所以任何单次窗口都得跨几个小时才有意义；`--drain` 会打印它能分辨到什么程度。

整个电流里唯一被归因的是 USB 块：在电池上把 `a6f8800.usb` 从 `dwc3-qcom-legacy` 解绑，电流从 465 mA 掉到 439 mA，重新绑定回到 459 mA——glue、xHCI 主机控制器与 HS PHY 值 **26 mA**。但它不能变成省电：解绑之后 UCSI 固件不再接受角色设置（`failed to set usb role`），端口卡在 host，UDC 不再出现，必须重启平板才会回来。没插线时端口为什么在 host 模式，是因为设备树的 `role-switch-default-mode = "host"`（扩展坞需要它）；`dwc3-qcom-legacy` 还会在挂起时打出 `port-1 HS-PHY not in L2`，说明 PHY 从未进入低功耗态。

## 为什么不能再低

`/sys/kernel/debug/qcom_stats/` 每个睡眠等级一块，数据来自固件本身。做完上面所有挂起后：

```
apss:        Count 229, accumulated 2758368719   （APSS 睡眠态，约 2758 s）
cxsd:        Count 0                              （CX shutdown）
ddr:         Count 0                              （DDR 低功耗态）
aosd:        Count 0                              （AOSS sleep）
adsp:        Count 8,      accumulated 6.4 s      （ADSP 几乎从不睡）
adsp_island: Count 0                              （island 模式从未进入）
slpi:        Count 5460,   accumulated 2634 s     （传感器 DSP 睡得很正常）
cdsp:        Count 34,     accumulated 3480 s
```

AP 睡了；CX 从未关断、DDR 从未离开活动态、always-on 子系统从未睡、ADSP 几乎一直醒着。这就是那 121 mA——量出来的，不是猜的。

Linux 能撤的票全部撤过一遍，每种配置挂起一次：

| 配置 | cxsd | ddr | aosd |
| --- | --- | --- | --- |
| 原样 | 0 | 0 | 0 |
| Wi-Fi 驱动从 PCI 解绑（`0000:01:00.0`） | 0 | 0 | 0 |
| 停掉 SLPI 与 CDSP remoteproc | 0 | 0 | 0 |
| 解绑 AP 的电池管理客户端 | 0 | 0 | 0 |
| 连 ADSP remoteproc 也停掉 | 0 | 0 | 0 |

Wi-Fi 解绑、所有 DSP 停掉之后，平台依然不离开 APSS 睡眠层。所以这不是 Linux 能撤销的某张投票：固件的 `SYSTEM_SUSPEND` 只让应用处理器睡，别的什么都不做。RSC 的 sleep set 是在最后一个 CPU 进入 CPU_PM 时由 `rpmh_flush()` 写下的，而 mainline 没有导出这份缓存，所以固件拿它做了什么，从这里也看不到。

## 为什么只会睡一次

PowerDevil 不是"定时器到点就睡"，而是"空闲时间**跨过**阈值时睡"。平板醒来时空闲时间早已越过阈值，于是在有人碰它之前不会再跨一次——而固件自己结束的睡眠不会有人碰它。所以随镜像发布的策略每个登录会话只会睡一次，之后就一直是醒着的。

2026-11-01 的实测（`AutoSuspendIdleTimeoutSec=60`）：

```
02:18:43  The system will suspend now!
02:18:54  Operation 'suspend' finished.        （只睡了 11 s，没人唤醒它）
02:26:30  什么都没有——醒了 7 分 36 秒，屏幕熄着，227 mA，
          直到手动重启 powerdevil；重启后 60 秒它又睡了，
          这正好排除了"超时值没生效"这个可能
```

每次唤醒还会把锁屏点亮，而且要等到 PowerDevil 的熄屏超时才会再次变黑，所以一次无人唤醒的代价是七分钟待机加五分钟亮屏。

于是"让平板重新睡回去"必须由 PowerDevil 以外的东西来做。而在平台本来就不断被叫醒的时候，无条件地每次唤醒都睡回去更糟：朴素的循环在 02:48 到 03:12 之间跑了 26 次挂起，每次只睡 5–48 s、中间醒着约 10 s，而且 Wi-Fi 重关联一直完不成，平板有几分钟完全不可达。

那些短睡眠其实是电池管理轮询。唤醒源策略一直只在开机时跑过一次：PMIC GLINK 的 supply 重新探测会把 `qcom-battmgr-bat` 重新打开，而解除它的那个 unit 是 `RemainAfterExit=yes` 且 `Before=sleep.target`，systemd-sleep 用 `replace-irreversibly` 启动 `sleep.target` 时并不会把它再拉进来一遍。它就一直停在开机那次启动上，轮询于是每 5–50 s 叫醒一次 AP，而功耗测量里看到的 476–604 s 睡眠被切成了几秒。现在重新施加策略的是一个 `systemd-sleep` 钩子（`/usr/lib/systemd/system-sleep/liuqin-wakeup-sources`），同一台平板之后在充电器上能一次睡 113–162 s。`tests/suspend-resume.py` 会自己在挂起前施加策略，因为它直接写 `/sys/power/state`，systemd-sleep 根本不会跑。

`liuqin-sleep-guard` 同时解决这两件事。它读输入设备的中断计数——电源键、触摸屏、手写笔、指纹、磁吸键盘和平板本身的按键——所以"人按出来的唤醒"会重置它的宽限期；接着通过 `liuqin-power-key-action short` 把锁屏的背光熄掉（要调用两次：那个脚本按自己记录的背光状态做切换，而唤醒会让这份记录过期），最后才让平板睡。内核拒绝的挂起（唤醒后大约半分钟内会留下 pending 的唤醒事件）30 s 后重试；睡不到 `min_sleep`（60 s）的那次不值得再付一次唤醒的代价，于是让平板熄屏醒着 120 s，而不是反复抖动。

值多少，按 05:07–05:18 在 100% 充电器上的实测：

| | 没有守卫 | 有守卫 |
| --- | --- | --- |
| 睡眠次数 | 一次，之后再没睡 | 145、86、102、75 s |
| 两次之间的清醒 | 7 分 36 秒 | 约 60 s，熄屏 |
| 睡着的墙钟占比 | ~0 % | **~63 %** |
| 等效电流 | 227 mA | **约 160 mA** |

电池上同样的守卫更好，因为固件在电池上能让平板一次睡 476–604 s：每轮 20–90 s 的开销就是 85–90% 的时间在睡，约 135 mA。天花板仍然是平台自己的 121 mA，它为什么不再低见下一节。

所以"墙钟里有多少时间在睡"取决于固件的状态，而不是守卫。同一台平板、同一个镜像，相隔一小时：

| 窗口 | 睡眠 | 睡着 | 醒着 | 睡着占比 | 等效电流 |
| --- | --- | --- | --- | --- | --- |
| 05:07–05:18，充电器 | 145、86、102、75 s | ~408 s | ~250 s | 63% | ~160 mA |
| 06:24–06:44，充电器 | 5–40 s，共 14 次 | ~250 s | ~950 s | 21% | ~200 mA |
| 06:44–07:03，充电器 | 32 次，6–38 s | 668 s | 476 s | 42% | ~182 mA |
| 12:32–12:55，充电器 | 167、400、406 s 及若干短的 | 1214 s | 174 s | **87%** | **~135 mA** |

这些唤醒的 `pm_wakeup_irq` 全是空：固件把应用处理器叫醒却不归属任何中断，和"提前结束睡眠"的是同一类不计数唤醒。电池上同一个守卫能一次睡 476–604 s，所以差别在充电器而不在守卫——而守卫至少让平板会重新睡回去。

还有一条是用一小时失联换来的：无人唤醒之后 WLAN 需要重新关联，若在关联完成前就睡下去，平板就彻底离线，直到有东西把它叫醒。2026-11-01 就出现了四十分钟 SSH 与 adb 都进不去——每个循环都在链路恢复前又睡了，最后只能靠人按电源键。现在守卫在每次唤醒后先给链路 `link_wait`（25 s），离线时照样睡，在线时不会把自己睡成失联。

## 还有哪些情况会提前结束睡眠

自己醒来的平板会把省下来的电又花回去，所以唤醒侧和睡眠侧一样重要。

1. **ADSP 的电池管理轮询。** 一次 25 分钟的挂起在 5 分 45 秒后结束，唤醒源计数里是 `qcom-battmgr-bat`。现在每次睡眠前都由 `liuqin-wakeup-sources` 解除（`/usr/lib/systemd/system-sleep/liuqin-wakeup-sources`），而不只是开机时跑一次：只跑开机那次的话，一次 PMIC GLINK 重新探测就会悄悄把它重新打开，睡眠掉到 5–50 s。钩子到位后同一条路径能睡满 420 s、900 s，当晚稍后也是 113–162 s。
2. **RTC 闹钟。** 上面所有测量都由 `/sys/class/rtc/rtc0/wakealarm` 唤醒；`pm8xxx_rtc_alarm` 每个闹钟计一次中断，实际睡眠与请求相差几秒以内。
3. **一种既没有唤醒源计数、也没有唤醒中断的莫名唤醒。** 一次 300 s 的挂起在 87 s 结束，一次 1500 s 的在 635 s 结束，一次 20 s 的在 15 s 结束，一次 10800 s 的在 481 s 结束；每次 `/sys/kernel/debug/wakeup_sources` 计数都是零、RTC 闹钟仍待触发。在 481 s 那次上 `CONFIG_PM_DEBUG` 与 `pm_debug_messages=1` 都开着，`/sys/power/pm_wakeup_irq` 读出来是**空**：内核根本没有把这次唤醒归到任何中断上。
4. **开机后第一次 `systemctl suspend` 可能在开始前就中止**，日志是 `Wakeup pending. Abort CPU freeze`（`suspend_stats` 记一次失败，`-EBUSY`），几分钟后重试就能进去；这一次的唤醒源计数同样没有变化，属于同一个不计数的事件。

大约每三次挂起有一次会因为 (3) 提前结束。`CONFIG_PM_DEBUG` 与 `CONFIG_PM_SLEEP_DEBUG` 已经在内核锁里（`device/configs/liuqin-suspend.config`），有中断可归因时 `/sys/power/pm_wakeup_irq` 和 `PM: Triggering wakeup from IRQ N` 能给出它，`tests/suspend-resume.py --cycle` 两个都会打印。

## 电池上的端到端实测

2026-11-01 两个窗口，拔线、无人触碰，用电量计差值（`charge_counter`，分辨率约 30 mAh）除以墙钟时间：

| 窗口 | 运行状态 | 消耗 | 电流 | 百分比 |
| --- | --- | --- | --- | --- |
| 1.59 h | 随镜像发布的策略 + `liuqin-sleep-guard` 接力（`success` 6，单次睡 453 s 与 4772 s，窗口内约 85% 在睡） | 162 mAh | **102 mA** | **1.36 %/h** |
| 0.84 h | 完全不挂起：熄屏、Wi-Fi 关联、空闲 | 181 mAh | **216 mA** | **2.88 %/h** |

也就是说实际使用中挂起能省一半，而第二个窗口与早先"清醒熄屏 3.0 %/h"的测量互相印证。挂起这一项还比早先 121 mA 的串联挂起测量更好，因为守卫现在会让平板尽量一次睡到底（该窗口里一次就睡了 4772 s），而不是反复循环。

绝对值仍然不是平板真正的深睡——原因见下面固件一节——但这是这个移植实际交付的效果，是量出来的而不是估出来的。

## 我们问过固件什么，它怎么回答

地板在固件侧，所以下一步就是直接针对固件：解包厂商镜像，找出厂商内核让平台睡眠所依赖的接口，再把同样的接口补进 mainline。找到三个候选，逐个实现并实测，**三个都是否定的**——而否定结果本身是有价值的证据。

**1. USB PHY（SM8550 上已知的 s2idle bug）。** `dwc3-qcom-legacy` 在挂起时打印 `port-1 HS-PHY not in L2`，mainline 又在 PHY 上多持有一份 `phy_init`，所以这一块从不进入低功耗态。电池上解绑 `a6f8800.usb` 能省 26 mA，问题是它是否也把 CX 顶住了——不是：解绑后 60 s 挂起，`cxsd`、`ddr`、`aosd` 仍然为零。

**2. AOP 自己的 prevent 投票。** `/sys/kernel/debug/aoss-qmp/` 下有 `prevent_cx_collapse`、`prevent_ddr_collapse`、`prevent_aoss_sleep`，是厂商 `aop_send_message` 的 mainline 对应物。三个全写 0 再挂起，计数依旧不动。

**3. SMP2P sleep state 位（厂商内核真正会写的那一个）。** 厂商 `smp2p_sleepstate.c` 在系统挂起前清掉 SMP2P "sleepstate" 条目的第 12 位、唤醒后再置上，这就是下游内核告诉 DSP"AP 要走了"的方式。该条目在 SLPI 这条边上（SMEM `<481>, <430>`，remote pid 3），厂商 DTS 里叫它 "sleepstate"、入向兄弟叫 "sleepstate_see"，而它们本来就存在于固件的 SMEM 条目里，不需要臆造。移植的驱动与两个 DT 节点在 `kernel/patches/` 与 `device/configs/liuqin-sleepstate.config`（内核构建会在锁定 commit 之上按名字顺序应用 `kernel/patches/*.patch`）。

绑定成功（`probe of smp2p-sleepstate returned 0`）后的实测：

```
之前  apss Count 227 acc 134834671   adsp Count 8 acc 6421810
      cxsd 0  ddr 0  aosd 0  adsp_island 0
挂起 60 s -> success=1, apss Count 228 acc 176492987（约 42 s 睡眠）
之后  cxsd 0  ddr 0  aosd 0  adsp_island 0   adsp Count 8 acc 6421810
```

也就是说这个固件同样不看这一位：`apss` 正常计数，更深的三层全零，ADSP 一动没动。驱动留在树里，因为它是文档里 DSP 该走的机制、固件更新后可能会生效，但在这颗固件上它不改变地板。

**4. 投票本身，而不只是那一位。** `rpmhpd` 把每个域的 *sleep* corner 写成当前 active corner 的副本（`to_active_sleep()`），所以 `cx.lvl` 到 AOP 手里永远是时钟/显示最后投过的那个 corner，而不是"off"。一个测试补丁（未留在树里）注册了 syscore_ops，在所有设备挂起之后把 `cx.lvl = 0` 写进 sleep set、唤醒时恢复，这是厂商 LPM 在 PSCI 调用前所做事情的最小版本。实测：`success=1`、`apss` 214 → 215 且累计增加 518 s，而 `cxsd`、`ddr`、`aosd` 仍然为零，`adsp` 一微秒没变。

过程中两条值得记住的经验：

- 这个条目的入向兄弟（"sleepstate_see"）**不能**当唤醒源用：它每几十秒就触发一次，每次都会让 `pm_wakeup_pending()` 为真，于是 `Wakeup pending. Abort CPU freeze` 连续一分钟让挂起失败。移植的驱动只写那一位。
- 启动镜像里的设备树必须是**合并后**的那份：引导程序按 bundle 构建产出的 DTB（内核 DTB + 厂商 overlay，224 KB）匹配板子，把 121 KB 的裸内核 DTB 塞进去会把平板打回 fastboot。`tools/deploy-liuqin-boot.py --dtb` 就是为此加的，正确的输入是合并树（`fdtoverlay -i <product dtb> -o <new> <overlay>`）。

至此，四个互相独立的 Linux 侧原因都已被测量排除（USB PHY、AOP prevent 投票、SMP2P sleep-state 位、CX 的 sleep-set 投票本身），再加上更早的那个（Linux 能停的子系统全部停掉）。

剩下唯一与所有测量都相容的解释：这颗 AOP 固件对 mainline 发出的投票不会执行 CX/DDR/AOSS 的塌陷序列。下一步该比的是厂商内核的 RPMh 用法（`rpmhpd` 的 sleep corner、cpufreq 的 sleep set、interconnect 留下的投票路径），而最省事的判定是：让平板进一次 Android 槽，读那里的 `/sys/kernel/debug/qcom_stats`——如果 Android 自己的计数也是零，那么任何内核改动都抬不动这个地板。

## 要修掉这个功耗地板，需要改什么

上面所有内容都是 Linux 侧的挂起流程，已经做完并验证。功耗地板不在其中，而且用户态无法触及：

1. **固件必须比 APSS 更深。** 在 Linux 能停的子系统全部停掉的情况下，每次挂起后 `cxsd`、`ddr`、`aosd` 仍是 0。究竟是 RSC 的 sleep set 里还留着一张投票，还是固件根本不会更深——Linux 无法判断。
2. **ADSP 必须能睡。** 传感器 DSP 睡了五千多次，ADSP 几乎从不睡。它承载充电、电量计、Type-C 与音频固件，用户态不可能让它整夜停着。
3. **island 模式根本没有建模。** `adsp_island` 从不增加，mainline 的 `qcom_q6v5_pas` 没有 island 支持，设备树里也没有 island carveout，所以厂商固件用做音频 offload 的 ADSP 低功耗模式目前完全不可达。

测量手段已经留给后人：一次挂起 + 读 `qcom_stats/{apss,cxsd,ddr,aosd,adsp}`（计数跨重启保留），毫安数用 `tests/suspend-resume.py --drain`。

## 操作陷阱

- **启动镜像锁定了根文件系统。** ramdisk 里带着一份覆盖 46 个文件的准入契约，`/etc/xdg/powerdevilrc` 正是其中之一。把随镜像发布的文件直接拷进运行中的平板，下一次启动就会 fail-closed 进 initramfs 诊断 shell（`native root rejected: hash differs from the contract`）。重新绑定要成对做：改契约里的哈希 → 用 `tools/patch-native-admission.py --boot-img <线上 boot_a> --contract <更新后的>` 给**线上**启动镜像打补丁 → 把文件写进根文件系统 → 刷写 → 重启。同时必须把用户级 `~/.config/powerdevilrc` 挪开，否则它会继续用 `AutoSuspendIdleTimeoutSec=0` 覆盖默认值。
- **`liuqin-usb-gadget-watch` 默认关闭。** 它在 `adbd` 放弃 FunctionFS 传输后重建 gadget，而插着主机时重建会和角色切换打架：日志最后停在 `FUNCTIONFS_SUSPEND`、`Set phy mode to usb host`、xHCI 在还插着线的端口上探测，然后平板重启——已经发生两次。要启用就自己建 `/etc/liuqin-usb-gadget-watch-enabled`；无论如何，长 `adb` 传输前先停掉它。
- **插着线挂起之后，`adb` 通常会死掉**：在平板上 `systemctl restart liuqin-usb-gadget` 即可恢复。
- **解绑平台模块并不总是可逆。** dwc3 glue（`a6f8800.usb`）解绑后端口卡在 host、没有 UDC、Type-C 角色写入返回 `I/O error`，只有重启才能恢复 USB（复现两次）。PMIC GLINK 客户端同理：解绑电池管理之后平板一度 USB 与 Wi-Fi 双双不可达。
- **停掉 ADSP 再拔插线会把平板卡死**（pstore 无记录，只能长按电源键）。而**不涉及电缆事件**的停/启是安全的——上面那条"只到 APSS"的结论就是这么测出来的。
- **drain 循环必须在电缆插回时退出。** 插着充电器、又有电源键的情况下，每次挂起几秒就会被唤醒，循环会一直挂起，屏幕不停点亮-黑屏直到重启。

## 回退

睡眠策略是两个文件加一次重新加载：

```sh
sudo sed -i 's/^AutoSuspendIdleTimeoutSec=.*/AutoSuspendIdleTimeoutSec=0/' \
    /etc/xdg/powerdevilrc
systemctl --user restart plasma-powerdevil
```

把 `AutoSuspendAction=0` 也改掉，就回到 0.6.0 镜像的行为：屏幕会熄灭，SoC 继续跑。只想临时恢复旧行为（单次启动有效）：

```sh
echo s2idle | sudo tee /sys/power/mem_sleep
```
