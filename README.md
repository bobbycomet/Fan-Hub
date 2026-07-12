<div align="center">

<img src="icon.png" width="140" alt="Fan Hub"/>

# Fan Hub

**Linux fan control, the way it should work.**

v1.5.5 · Python 3.10+ · PyQt6 · Ubuntu · Arch · Fedora · Any systemd distro

</div>

## **NOTICE!** If you are on anything other than Ubuntu, the AppImage may not work. Looking over the install.sh, I missed a few things. I will upload the fix soon. I do apologize. A proper `.deb` is also coming soon. For other distros other than Ubuntu, you will get a tar.gz file. I wish there was an easier way, but I will make the install.sh to detect your current distro that uses systemd, as it only works if systemd is available. I will look into getting the AppImage working for the other distros at a later date. 

Distros the install.sh I will include:

| Package Manager | Distributions |
|:---|:---|
| `apt` | Ubuntu, Debian, Linux Mint, Pop!_OS, elementary, Kali, Raspberry Pi OS, Armbian, Zorin, and any ID_LIKE=debian/ubuntu derivative |
| `pacman` | Arch, Manjaro, EndeavourOS, Garuda, Artix, CachyOS |
| `dnf` | Fedora, RHEL, CentOS Stream, Rocky, AlmaLinux, Nobara, Ultramarine |
| `zypper` | openSUSE Tumbleweed, openSUSE Leap, SLES |
| `emerge` | Gentoo (prints instructions, doesn't auto-emerge) |
| `nix` | NixOS (prints instructions to use the AppImage instead) |
| Unknown | Any other distro — prints a warning listing what to install manually, then continues |

I will be looking into runit and OpenRC as well. 

**Update:** If this is still up, I am still working on it. My other updates are on hold until I have tested that the issues are fixed. I have run into some issues, but once I get that sorted, trying to add `runi` and `OpenRC`, changing names in the temperature cards (better clarity on what the temps represent instead of Motherboard 1), and building and installing the `deb` file introduced some regressions that are now being worked on. To explain how it works now, the `install.sh` file will check what init system you run, and if it is not `systemd`, `runit`, or `OpenRC`, then it falls into the unknown category. A new checking system to see if there is an update for `OpenRGB` and `Fan Hub`. I am also looking into a polkit install button in the `appimage` because it may work on my system, but if it fails on yours, there is a fallback. A newer mode feature lets you know if you are in `Normal` or `Emergency` mode, and the emergency 100% button became `Activate Emergency mode` for more clarity on what that button does. Since newer features were added, the version will be bumped to 1.6.0 due to multiple updates to the workflow, better clarity, upgrade support for `OpenRGB` and `FanHub`, init system check in the tar.gz's `install.sh`, and dashboard errors after the temp card updates.

---

## Why Fan Hub Exists

On Windows, fan control is solved. **Argus Monitor**, **FanControl**, **HWiNFO**, and **NZXT CAM** give you a graphical interface where you draw a temperature-to-speed curve, assign it to a fan, save it as a profile, and forget about it. The software runs in the background, the curves stay active at boot, and everything just works.

On Linux, none of that existed.

The traditional Linux answer has been to edit `/etc/fancontrol`, run `pwmconfig` in a terminal, and restart a service. That tool hasn't had a graphical interface in decades. It doesn't support GPU fans, AIO coolers, USB fan hubs, or modern SuperIO chips out of the box. It requires root for every write. There is no profile system, no live temperature display, and no curve editor.

Fan Hub is the Windows fan control experience, rebuilt for Linux from the ground up:

- Draw fan curves visually, see the current temperature moving along them in real time
- One background daemon keeps your curves active at boot and when the app is closed
- GPU fans, AIO pumps, USB hubs, and motherboard headers all in one place
- Profiles you can save, load, export as JSON, and share
- A guided setup wizard on first launch, so nothing requires reading documentation
- One-click diagnostics with "Fix It" buttons that handle permissions and modules

---

<img width="1920" height="1080" alt="Screenshot_20260705_115419" src="https://github.com/user-attachments/assets/52cb3457-8406-43e8-bd5b-8ab0d6717b97" />
<img width="1920" height="1080" alt="Screenshot_20260705_115337" src="https://github.com/user-attachments/assets/22a7720f-2e10-4bb9-a916-13c832eb1824" />
<img width="1920" height="1080" alt="Screenshot_20260705_115327" src="https://github.com/user-attachments/assets/ca12ff13-07af-49e6-b4af-236e48d566bb" />
<img width="1920" height="1080" alt="Screenshot_20260705_115319" src="https://github.com/user-attachments/assets/0d9a04bb-4fda-4cc3-8c77-2a3808e90f5d" />
<img width="1920" height="1080" alt="Screenshot_20260705_115216" src="https://github.com/user-attachments/assets/de1cbca4-1105-44b8-9dcf-b742cd0e54f6" />

## What Fan Hub Can Control

### Motherboard fan headers

Any 3-pin or 4-pin fan plugged into a SYS\_FAN, CHA\_FAN, CPU\_FAN, or PUMP header is controllable if the board's SuperIO chip is supported by the kernel. Common chips:

| Chip family | Boards |
|---|---|
| Nuvoton NCT6775/NCT6798 and variants | Most ASUS, Gigabyte |
| ITE IT87xx and variants | Most MSI, ASRock |
| Fintek F71xxx | Some older boards |

If your fans appear in `sensors` output, Fan Hub can control them.

### GPU fans

| Vendor | Temperature | RPM | Speed control |
|---|---|---|---|
| AMD (amdgpu) | ✓ | ✓ | ✓ Full PWM via hwmon |
| NVIDIA | ✓ | ✓ via fan_input | ✓ via CoolBits or nvidia-settings |
| Intel Arc (xe) | ✓ | — | — Driver managed |
| Intel iGPU (i915) | ✓ | — | — Firmware managed |

NVIDIA GPU fans default to the **Performance** curve automatically. If CoolBits is not enabled, Fan Hub reads the fan percentage from nvidia-smi and shows it honestly as a percentage rather than pretending it has RPM data.

### AIO coolers and USB hubs (via LiquidCtl)

This feature should work, but it is untested, as I do not own any AIO coolers or such to test this with. 

Fan Hub uses the **liquidctl Python API** directly, not the CLI, for lower latency and type-safe status reads. Supported families include:

- NZXT Kraken X/Z (all generations), Kraken 2023/2024
- Corsair Hydro Platinum, Pro XT, Elite RGB, iCUE Elite Capellix
- EVGA CLC
- Aquacomputer D5 Next, Octo, Quadro, Farbwerk 360
- Corsair Commander Pro, Commander Core/Core XT/ST
- NZXT Smart Device V1/V2, Grid+ V3, RGB & Fan Controller
- Lian Li GA II LCD, Uni SL/AL/SL-Infinity
- NZXT E-series PSUs (monitoring only)

### What Fan Hub cannot control

- **Fans with internal controllers** — budget RGB fans (Apevia, Rosewill, no-name) that plug into a Molex or SATA power connector and manage their own speed internally have no connection to the motherboard's PWM system
- **2-pin Molex fans** — always full voltage, no tachometer, no control
- **Daisy-chained fans on a single header** — appear as one channel, all spin together; this is hardware behaviour
- **Intel integrated GPU fans** — managed entirely by the driver and firmware stack

Every uncontrollable fan in the Fan Control tab has a **?** button that explains the specific reason for that fan and what (if anything) can be done about it.

---

## Interface

### Dashboard

Live temperature gauges for every sensor on the system — CPU cores, GPU edge and junction, NVMe composite, chipset, ambient. Each gauge has a configurable warning threshold (yellow) and critical threshold (red). A scrolling history chart shows the last 60 seconds. Fan RPM cards show current speed and a percentage bar.

### Fan Control

One card per detected fan. Each card shows the fan label, chip source, current RPM (or percentage for fans without a tachometer), a live speed bar, and a mode selector:

- **Auto** — restore the hardware's built-in automatic control
- **Curve** — drive from a named fan curve based on temperature
- **Fixed %** — set a constant duty cycle and leave it
- **Manual slider** — drag to any speed for immediate testing

GPU fans show a coloured badge: green for NVIDIA, red for AMD, blue for Intel.

### Fan Curves

A canvas editor where you click to add control points, drag to reshape the curve, and right-click to remove points. The canvas shows:

- The curve line from 0°C to 100°C on the X axis, 0–100% speed on the Y axis
- A **live vertical temperature marker** — a line at the current temperature with a dot on the curve showing the speed being commanded right now, updated every poll cycle
- Dragged points are tracked by identity before sorting, so the drag never jumps to the wrong point

Each curve has a sensor selector (specific sensor, highest of all, or average), a blend mode (Highest / Average / Weighted), hysteresis, minimum speed, and fan-stop threshold. Fan-stop bypasses the minimum speed clamp, so the fan actually reaches zero.

Six built-in presets: **Silent**, **Balanced**, **Performance**, **Gaming**, **Full Speed**, **Fixed 30%**.

### Profiles

Named configurations that save the complete curve assignment and fixed speed state. The Profiles tab has:

- Save, Load, Delete, Duplicate
- **Export** — saves the selected profile as a `.json` file
- **Import** — reads a `.json` profile, prompting to overwrite if the name exists
- Quick-apply preset buttons that apply a curve family to all fans in one click

Profiles are plain JSON and are human-readable and shareable.

### RGB Lighting

OpenRGB SDK integration. Connects to a running OpenRGB server, lists all detected devices with their LED count and type, and lets you set colours and effects. Temperature-reactive mode changes colour based on the hottest sensor, from blue at cool, through yellow, to red at the warning threshold.

### Liquid / AIO

Per-device panels for every LiquidCtl device show pump speed, fan speeds, liquid temperature, and controls for pump mode and fan speed. Initialise and re-initialise without leaving the app.

### Settings

Poll interval (250ms–10s), temperature unit (°C/°F), safe mode (never command below rated minimum RPM), emergency temperature (all fans jump to 100% with a tray alert), global hysteresis, system tray enable/disable, start minimised, OpenRGB host and port, and the background daemon toggle.

The **daemon section** shows live status from systemd (`● Running — enabled at startup`, `◑ Enabled but stopped`, `○ Stopped`, `⚠ Not installed`) and has Start / Stop / Reload Curves buttons for immediate control without saving settings.

---

## Background Daemon

The daemon (`fanhub-daemon`) is a headless `QCoreApplication` — not the full GUI — that loads config, starts the polling worker, and applies fan curves continuously. It has no windows and uses no display.

Enable it in **Settings → Background Daemon**. Once enabled:

- It starts immediately and at every boot via systemd
- It applies to whichever profile was active when you last saved
- When you change curves or load a profile in the GUI, Fan Hub saves the new state to config and sends `SIGHUP` to the daemon — it reloads within one poll cycle without restarting
- When you close the app to the tray, curves are saved first so the daemon stays current
- When you quit the app entirely, curves are saved before exit

The daemon restores all fans to automatic mode on `SIGTERM` (clean shutdown or `systemctl stop`).

---

## Permissions

Fan Hub uses a **dedicated `fanhub` group** rather than world-writable sysfs entries or always-on root. The installer creates the group, adds your user to it, and writes targeted udev rules:

```
KERNEL=="pwm[0-9]*",        SUBSYSTEM=="hwmon", GROUP="fanhub", MODE="0660"
KERNEL=="pwm[0-9]*_enable", SUBSYSTEM=="hwmon", GROUP="fanhub", MODE="0660"
```

Only PWM and PWM-enable files get group write access. Temperature inputs, voltage readings, and everything else in hwmon stay read-only for normal users.

After installation, log out and back in for group membership to take effect. If you need fan control immediately without logging out: `sudo fanhub` or `newgrp fanhub` in the current shell.

The AppImage version shows a setup dialog on first launch and runs the installer via `pkexec` — GUI password prompt, no terminal.

---

## Installation

### From the tarball (recommended)

```bash
tar -xzf fanhub_v1.5.5.tar.gz
cd fanhub
sudo ./install.sh
```

Log out and back in, then run `fanhub`.

### From the AppImage

```bash
chmod +x FanHub-1.5.5-x86_64.AppImage
./FanHub-1.5.5-x86_64.AppImage
```

On first launch, a setup dialog detects missing system components and installs them via `pkexec`. The AppImage bundles Python, PyQt6, and all dependencies — nothing needs to be installed system-wide to run the app.

### Build the AppImage yourself

```bash
cd fanhub
./build_appimage.sh
```

Requires `python3`, `rsync`, and `curl`. Downloads `appimagetool` automatically. Produces `FanHub-1.5.5-x86_64.AppImage`.

---

## First Run

Fan Hub shows a **four-step guided setup wizard** the first time it opens:

1. **Welcome** — explains what's about to happen
2. **Hardware scan** — shows every detected fan with ✓ controllable / ○ read-only status and current RPM
3. **Choose a curve** — four preset cards with descriptions; selecting one assigns it to all controllable fans immediately
4. **Done** — confirms what was applied, shows tips for next steps

The wizard is skippable. It sets `first_run_done: true` in the config so it never appears again.

---

## Running Tests

```bash
cd /opt/fanhub
python3 -m unittest tests.test_fan_curves tests.test_app_state tests.test_hardware_monitor -v
```

90 tests, all pure logic — no real hardware, no display, no network. Fast enough to run on every code change.

---

---

# Technical Reference

## Architecture overview

```
fanhub/
├── main.py                         Entry point, QApplication, stylesheet, platform detection
├── fanhub_daemon.py                Headless daemon — QCoreApplication, no windows
├── build_appimage.sh               AppImage builder (bundles Python venv + source)
├── install.sh                      System installer (group, udev, modules, systemd, venv)
├── core/
│   ├── app_state.py                Config persistence, atomic write
│   ├── app_context.py              Shared context object injected into all tabs
│   ├── daemon_controller.py        All systemd interactions for fanhub-daemon
│   ├── fan_curves.py               FanCurve, CurveEngine, BlendMode, presets
│   ├── hardware_monitor.py         hwmon reader/writer, GPU backends
│   ├── liquidctl_manager.py        liquidctl Python API with CLI fallback
│   ├── rgb_manager.py              OpenRGB SDK + CLI
│   ├── polling_worker.py           QThread background loop, staggered polling
│   └── sleep_monitor.py            D-Bus PrepareForSleep listener
└── ui/
    ├── main_window.py              Main window, tray, first-run trigger, daemon wiring
    ├── appimage_setup_dialog.py    AppImage system integration dialog (pkexec install)
    ├── first_run_wizard.py         Four-step guided setup wizard
    ├── hardware_summary_dialog.py  Live diagnostics + Fix It buttons
    ├── dashboard_tab.py            Gauges, history chart, fan RPM cards
    ├── fan_control_tab.py          Per-fan cards, mode selector, Why? button
    ├── fan_curves_tab.py           Canvas curve editor, live temp/speed overlay
    ├── fan_warning_dialog.py       Startup 0-RPM warning (motherboard fans only)
    ├── profiles_tab.py             Profile CRUD, import/export
    ├── settings_tab.py             Settings form, daemon toggle
    ├── rgb_tab.py                  OpenRGB device list and controls
    └── liquid_tab.py               liquidctl device panels
```

## Core subsystems

### HardwareMonitor (`core/hardware_monitor.py`)

Discovers and reads all hwmon nodes under `/sys/class/hwmon/hwmon*`. For each node it reads the `name` file to identify the chip, then discovers fan inputs (`fan*_input`), PWM outputs (`pwm*`), PWM enable files (`pwm*_enable`), and temperature inputs (`temp*_input`).

Fan classification uses the chip name against known chip sets:

```python
_AMD_GPU_CHIPS    = {'amdgpu', 'radeon'}
_NVIDIA_GPU_CHIPS = {'nvidia'}
_INTEL_GPU_CHIPS  = {'i915', 'xe'}
```

For NVIDIA fans, the monitor checks whether `pwm1` is writable (CoolBits path) and whether `nvidia-settings` is available. It reads RPM from `fan*_input` when the file exists, regardless of the PWM control path — `nvidia_use_hwmon` controls writing only, not reading.

For AMD GPU temperatures not exposed via hwmon, `_refresh_amd_rocm_temps()` calls `rocm-smi --showtemp --json` on every poll cycle.

PWM auto-mode values differ by chip family:
- `nct6775` and related: `pwm*_enable = 2` for auto, `1` for manual
- `it87` family: `pwm*_enable = 0` for auto (SmartGuardian), `1` for manual

All sysfs writes use `_write_file()` which catches permission errors and logs them without crashing.

### FanCurve and CurveEngine (`core/fan_curves.py`)

`FanCurve` stores a list of `CurvePoint(temp, speed)` objects and interpolates linearly between them. Key behaviour:

- `stop_below` returns `0.0` **before** the `max(min_speed, ...)` clamp, so the fan actually reaches zero rather than being clamped back up to `min_speed`
- `_drive_temp(temps_dict)` selects the driving temperature based on `blend_mode`:
  - `HIGHEST` — max of all values (or filtered by `sensor_ids`)
  - `AVERAGE` — mean of all values
  - `WEIGHTED` — dot product of values and `sensor_weights`
  - Falls back to highest if the specified `sensor_id` is missing

`CurveEngine` maintains the mapping from fan IDs to curve names or fixed speeds. `compute_speed(fan_id, temps)` applies hysteresis: if the temperature change from last cycle is less than `hysteresis_global`, the last commanded speed is returned unchanged. The emergency path bypasses curves entirely and returns 100.0 when any sensor exceeds `emergency_temp`.

`load_dict()` updates `fan_assignments` and `fixed_speeds` **in place** using `.clear()` + `.update()` rather than replacing the dict objects. This preserves external references held by other code.

### PollingWorker (`core/polling_worker.py`)

A `QThread` that runs a polling loop at the configured interval. Staggered schedule:

| Backend | Interval | Reason |
|---|---|---|
| hwmon sysfs | Every cycle | Pure file reads, ~microseconds |
| nvidia-smi subprocess | Every 3 cycles | ~50ms subprocess overhead |
| liquidctl | Every 5 cycles | USB HID round-trip latency |

The worker holds a `threading.Lock` (`_fan_lock`) that guards all `FanEntry` attribute mutations. The UI reads fan data from the same objects on the main thread, so the lock prevents torn reads.

After reading the hardware state, the worker calls `CurveEngine.compute_speed()` for every fan that has a curve assignment and writes the result via `HardwareMonitor.set_fan_pwm()`. Emergency override runs before curve computation and bypasses it.

### DaemonController (`core/daemon_controller.py`)

All `systemctl` interactions for `fanhub-daemon` in one class. Every method is safe to call on non-systemd systems — `FileNotFoundError` is caught and returns a sensible default.

`DaemonStatus` is a value object with `(installed, active, enabled, no_systemd)` fields and a `summary() -> (text, css_color)` method. The Settings tab uses this directly for its status label — no status string construction in the UI layer.

`DaemonController.reload()` sends `SIGHUP` via `systemctl kill --signal=SIGHUP fanhub-daemon`. The daemon's `SIGHUP` handler reloads config from disk and calls `ProfileManager.load_profile()` for the active profile without restarting the process or interrupting fan control.

### AppContext (`core/app_context.py`)

A `@dataclass` passed to every tab at construction time, replacing the previous pattern of walking the widget tree to find `MainWindow`:

```python
@dataclass
class AppContext:
    state:            AppState
    hw_monitor:       HardwareMonitor
    curve_engine:     CurveEngine
    profile_manager:  ProfileManager
    on_curves_changed:    Callable[[], None]
    on_profile_loaded:    Callable[[str], None]
    on_tray_menu_refresh: Callable[[], None]
```

Tabs call `ctx.on_curves_changed()` after modifying curves. `MainWindow` wires this to `_save_curves_to_config()` which serialises the engine state, writes `config.json` atomically, and sends `SIGHUP` to the daemon.

### AppState (`core/app_state.py`)

Reads and writes `~/.config/fanhub/config.json`. All saves use `tempfile.mkstemp` + `os.replace` (atomic rename) so a crash mid-write cannot corrupt the config file. If the config is missing or unparseable, all defaults are used and a fresh config is written on next save. Unknown keys in a loaded config are preserved across saves.

### LiquidctlManager (`core/liquidctl_manager.py`)

Uses the **liquidctl Python API** as the primary backend:

```python
from liquidctl import find_liquidctl_devices

for dev in find_liquidctl_devices():
    with dev.connect():
        status = dev.get_status()   # returns [(key, value, unit), ...]
```

Status tuples are parsed into structured `fans`, `temps`, and `pump` fields without regex or JSON parsing. If the Python library is not installed or raises on import, the manager falls back to the CLI transparently — all callers see the same `LiquidDevice` interface.

Device capabilities (fan control, pump control, RGB) are looked up by keyword match against `KNOWN_DEVICES` — a table covering all liquidctl-supported families.

## UI patterns

### Tray icon

`self._tray_icon` is a plain instance attribute on `MainWindow`, not a module-level global. It is parented to the `QApplication` instance so it survives the window being hidden. A `_quitting` flag prevents the close event from showing the quit dialog twice when the tray's Quit action is used.

### Curve canvas

`CurveEditorCanvas` (in `fan_curves_tab.py`) subclasses `QWidget` and implements `paintEvent`, `mousePressEvent`, `mouseMoveEvent`, and `mouseReleaseEvent`. Dragged points are identified by `(temp, speed)` value before the point list is sorted, then located again by closest temperature after sorting. This prevents the drag jumping to a different point when the mouse moves during a slow frame.

The live temperature marker is set by `set_current_temp(temp)` called from the polling worker signal. It draws a vertical line at the current temperature and a filled circle on the curve at the interpolated speed.

### FlowLayout

`DashboardTab` uses a custom `FlowLayout` that wraps gauge widgets like CSS `flex-wrap`. Its `takeAt()` calls `widget.setParent(None)` before returning the item so removed widgets don't remain as invisible children of the container.

### First-run and AppImage detection

`main.py` checks `os.environ.get('FANHUB_APPIMAGE')` to detect AppImage execution, then checks for the udev rule and fanhub group membership. If both conditions are true, `AppImageSetupDialog` is shown before `MainWindow`. After the dialog (or if it is skipped), `MainWindow` opens and checks `state.settings.get('first_run_done')` to decide whether to show the wizard.

## Config file format

```json
{
  "settings": {
    "poll_interval_ms": 1000,
    "temp_unit": "C",
    "safe_mode": true,
    "emergency_temp": 90.0,
    "hysteresis": 2.0,
    "tray_icon": true,
    "start_minimized": false,
    "openrgb_host": "localhost",
    "openrgb_port": 6742,
    "daemon_enabled": false,
    "first_run_done": true
  },
  "profiles": {
    "Gaming": {
      "name": "Gaming",
      "curves": {
        "fan_assignments": { "hwmon2_fan1": "gaming", "hwmon3_fan1": "performance" },
        "fixed_speeds":    { "hwmon2_fan2": 45.0 },
        "custom_curves": {}
      }
    }
  },
  "active_profile": "Gaming"
}
```

## udev rules

```
# /etc/udev/rules.d/99-fanhub.rules

# Grant fanhub group write access to PWM control files only
KERNEL=="pwm[0-9]*",        SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"
KERNEL=="pwm[0-9]*_enable", SUBSYSTEM=="hwmon", ACTION=="add", GROUP="fanhub", MODE="0660"

# Fallback: set ownership on hwmon node add (handles kernels where
# attribute-level udev matching does not fire for sysfs sub-entries)
KERNEL=="hwmon[0-9]*", SUBSYSTEM=="hwmon", ACTION=="add", \
    RUN+="/bin/sh -c 'chown root:fanhub /sys%p/pwm* 2>/dev/null; \
                      chmod 660 /sys%p/pwm* 2>/dev/null || true'"

# liquidctl USB device access
SUBSYSTEM=="usb", MODE="0666", GROUP="plugdev"
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", MODE="0666", GROUP="plugdev"

# I2C bus access (for Corsair Vengeance RGB and similar)
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
```

## systemd service

```ini
# /etc/systemd/system/fanhub-daemon.service

[Unit]
Description=Fan Hub headless fan curve daemon
After=multi-user.target
Wants=multi-user.target

[Service]
Type=simple
User=root
ExecStart=/opt/fanhub/venv/bin/python3 /opt/fanhub/fanhub_daemon.py
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

The daemon runs as root because it writes to hwmon sysfs files. `ExecReload` sends `SIGHUP`, which the daemon catches and uses to reload config without restarting. `KillMode=process` ensures `SIGTERM` reaches the main Python process directly so the `_shutdown` handler can restore fans to auto before exiting.

## Test suite

Three test modules, 90 tests total, all run without hardware, display, or network:

**`tests/test_fan_curves.py`** — 45 tests
- `FanCurve.interpolate()`: below/above/exact/midpoint, unsorted points, single point, empty curve
- `stop_below` bypasses `min_speed` clamp (regression test for the v1.5.4 fix)
- All preset curves are monotone (non-decreasing speed as temperature rises)
- `BlendMode`: highest, average, weighted, sensor ID filtering, missing sensor fallback
- `CurveEngine`: fixed speed, curve assignment, emergency override, hysteresis gates, round-trip serialisation, `load_dict` in-place update

**`tests/test_app_state.py`** — 27 tests
- All defaults are present on fresh state
- Save/reload settings and profiles
- Profile CRUD (create, read, update, delete)
- Atomic write produces valid JSON with no stray `.tmp` files
- Corrupted config does not crash — defaults used
- `DaemonController` via mocks: status parsing, SIGHUP only sent when active, reload skipped when inactive, `DaemonStatus.summary()` return values

**`tests/test_hardware_monitor.py`** — 18 tests
- `_friendly_temp_label()` for all chip families: SuperIO, k10temp, coretemp, nvme, amdgpu
- GPU chip classification: AMD/NVIDIA/Intel/unknown, case-insensitive
- it87 auto-value is `'0'`, nct6775 auto-value is `'2'`
- PWM enable is written before PWM value (order matters for some chips)
- Safe-mode minimum PWM clamping

---

## Dependencies

| Package | Required | Purpose |
|---|---|---|
| `PyQt6` | Yes | UI framework |
| `PyQt6-Charts` | Optional | Temperature history graph |
| `liquidctl` | Optional | AIO and USB hub control |
| `openrgb-python` | Optional | OpenRGB SDK |
| `psutil` | Optional | Additional system info |

```bash
pip install PyQt6 PyQt6-Charts liquidctl openrgb-python psutil
```

---

Fan Hub is licensed under the GPLv3, and forks and derivative projects are welcome.

If you build on Fan Hub, please:

- Keep the GPLv3 license terms intact.
- Give appropriate credit to the original Fan Hub project.
- Include a link back to this repository where practical.

If you're building something cool with it, I'd love to hear about it!

## Community and Support

- **Discord:** [Join Here](https://discord.gg/7fEt5W7DPh)
- **Patreon (Beta Builds):** [Patreon](https://www.patreon.com/c/BobbyComet/membership)
- **Support the Griffin Project:** [Ko-fi](https://ko-fi.com/bobby60908)

<div align="center">
  <img src="https://raw.githubusercontent.com/bobbycomet/Appify/main/Griffin-G.png" alt="Griffin Linux" width="15%"/>
  <p><strong>Griffin Linux. Where power meets simplicity.</strong><br/>
  Made with Windows switchers in mind. Built for everyone who wants a better PC.</p>
</div>

The Fan Hub and Griffin Linux names, logos, and branding are not covered by the GPL license and may not be used to imply endorsement 
or official affiliation without permission. Forks are encouraged, but please rename and rebrand modified versions unless you've 
received permission to use the original branding.

Fan Hub is an independent project and is not affiliated with, authorized, or endorsed by NZXT, Corsair, Argus Monitor, HWiNFO, OpenRGB, or any other hardware manufacturer. All product names, logos, and brands are the property of their respective owners.

</div>
