<div align="center">

<img src="assets/icon.png" width="120" alt="Fan Hub Icon"/>

# Fan Hub
### Linux Fan Control & RGB Management

**Beta Release** · PyQt6 · Ubuntu/Debian · Python 3.10+

*The Windows fan curve experience, brought to Linux.*

---

</div>

> **⚠ Beta Notice**
> Fan Hub is currently in beta. It is a **monitoring and control tool only** — it does not write any configuration files to your system, does not modify your BIOS, and does not persist any changes between reboots unless you explicitly save a profile. Fan speeds return to motherboard auto-control when you close the application (you are asked). Your hardware is safe.

---

## What Is Fan Hub?

If you have ever used **Argus Monitor**, **FanControl**, **NZXT CAM**, or **SpeedFan** on Windows, Fan Hub is the Linux equivalent. It gives you a real graphical interface to:

- **See your temperatures** — CPU, GPU, chipset, NVMe, and more, all live
- **Control your fan speeds** — manually or with smooth custom curves tied to temperature
- **Control RGB lighting** — through OpenRGB, for any compatible device
- **Manage AIO coolers** — pump speed, radiator fans, and liquid cooling RGB

Most Linux systems have no easy way to do any of this without editing config files or running terminal commands. Fan Hub wraps all of that into a single application that any desktop user can operate.

---

## What Fan Hub Does (and Does Not Do)

### ✅ What it does

- Reads live temperatures from your CPU, GPU, motherboard sensors, NVMe drives, and more
- Shows fan speeds (RPM) for every fan connected to a motherboard header
- Lets you set fan speeds manually with a slider, or draw custom temperature-to-speed curves
- Applies those curves automatically in the background, adjusting fan speed as temperatures change
- Saves your settings as named profiles (Silent, Gaming, Work, etc.) that you can switch between instantly
- Controls RGB lighting on compatible devices through OpenRGB
- Controls AIO liquid coolers (NZXT Kraken, Corsair Hydro, and others) through liquidctl
- Warns you on startup if any fans are showing 0 RPM, and explains why that might be happening

### ❌ What it does not do

- **Does not write any files to your system** outside of its own config folder (`~/.config/fanhub/`)
- **Does not modify your BIOS** or UEFI settings
- **Does not persist fan speed changes** after the app closes — fans return to auto when you exit
- **Does not control fans that are not connected to a motherboard header** (see the Fan Compatibility section)
- **Cannot control generic/budget RGB fans** that have their own internal controller (Apevia, most no-name case fans) — those require proprietary software that does not exist for Linux

---

## Screenshots / Interface Overview

Fan Hub has seven tabs across the top:

| Tab | What it shows |
|---|---|
| **Dashboard** | Live temperature gauges, fan RPM cards, scrolling history chart, liquid cooling summary |
| **Fan Control** | Per-fan speed sliders, mode selection, curve assignment |
| **Fan Curves** | Visual curve editor — draw your own temperature-to-speed curves |
| **RGB Lighting** | OpenRGB device control, color pickers, effects, temperature-reactive mode |
| **Liquid / AIO** | AIO cooler fan and pump control via liquidctl |
| **Profiles** | Save and load complete configurations |
| **Settings** | Poll interval, safety thresholds, OpenRGB connection, permissions |

---

## Getting Started

### Step 1 — Install Fan Hub

```bash
tar -xzf fanhub_v1.3.tar.gz
cd fanhub
sudo ./install.sh
```

The installer handles everything: system packages, Python environment, udev rules so you can write fan speeds without root, kernel module loading, and a desktop entry so Fan Hub appears in your app menu.

### Step 2 — Run it

```bash
sudo fanhub
```

> **Why sudo?** Writing fan speeds to the hardware requires root access on most systems. After the installer runs and you log out and back in, you may be able to run it without sudo — it depends on your motherboard and udev configuration. The Settings tab has a button to copy the correct udev rule to your clipboard.

### Step 3 — Check your fans

On first launch, Fan Hub shows a **Fan Check** dialog. This lists every fan it can see and flags any that are reading 0 RPM. Read it — it tells you whether your fans are wired in a way Fan Hub can control them.

### Step 4 — Set up RGB (optional)

RGB control requires OpenRGB to be installed and its server to be running. See the **OpenRGB Setup** section below.

---

## Fan Compatibility

Not all fans can be controlled. Here is a plain-English guide:

### Fans Fan Hub CAN control

- Any **3-pin or 4-pin fan** plugged directly into a **SYS_FAN**, **CHA_FAN**, or **CPU_FAN** header on your motherboard
- Fans connected through a **Corsair Commander Pro** or **Commander Core** (via the Liquid/AIO tab)
- Fans connected through an **NZXT Smart Device** or **Grid+** (via the Liquid/AIO tab)
- **AIO cooler radiator fans** and **pump** (NZXT Kraken, Corsair Hydro H-series, EVGA CLC, and others)
- **Laptop fans** on supported models (ThinkPad, some ASUS, some Dell)
- **Molex fans** if they use a Molex-to-3pin or Molex-to-4pin adapter plugged into a SYS_FAN header

### Fans Fan Hub CANNOT control

- **Generic budget fans** (Apevia Cosmos, Rosewill, most no-name RGB case fans) that have their own internal hub/controller. These fans plug into a USB header or proprietary connector — not SYS_FAN — and use software that has no Linux equivalent. Fan Hub will detect that they exist on the RGB side through OpenRGB if they are supported, but cannot adjust their speed.
- **2-pin Molex-only fans** — these run at full voltage always, there is no speed control
- **Fans connected only to an RGB/ARGB header** — Fan Hub can control their color but not their speed
- **Daisy-chained fans** plugged into a single header act as one channel — Fan Hub controls them all together at the same speed, which is the correct behavior

### What to do if your fan shows 0 RPM

1. Make sure the fan is physically spinning (open the case and look)
2. Check that the speed cable (3-pin or 4-pin connector) is plugged into a SYS_FAN header — not just a power connector
3. Try loading a kernel module: `sudo modprobe nct6775` or `sudo modprobe it87`
4. Some fan headers only show RPM when the fan is actually moving — if a fan is stopped because temperatures are low, 0 RPM is correct

---

## OpenRGB Setup

OpenRGB is a separate application that Fan Hub uses for RGB control. It is not built into Fan Hub.

### Installing OpenRGB

**Option A — AppImage (recommended, no install required):**
```bash
# Download from https://openrgb.org
# Fan Hub will find it automatically in ~/Downloads, ~/Applications, or ~/bin
# Any version name works — you don't need to rename it
chmod +x OpenRGB*.AppImage
```

**Option B — .deb package:**
```bash
# Download .deb from https://openrgb.org
sudo dpkg -i openrgb_*.deb
```

### Starting the OpenRGB server

Fan Hub connects to the OpenRGB SDK server. You need to start it before opening Fan Hub (or click Reconnect in the RGB tab after starting it):

```bash
# AppImage:
./OpenRGB*.AppImage --server --server-port 6742 &

# System install (deb):
openrgb --server --server-port 6742 &
```

### Connecting in Fan Hub

Go to the **RGB Lighting** tab. The status bar at the top shows whether Fan Hub is connected to OpenRGB. If it is not:

1. Make sure the server is running (command above)
2. If the binary is not auto-detected, use the **Browse…** button to point to your AppImage
3. Click **Reconnect**

The tab auto-checks the connection every 5 seconds, so once the server starts, it will connect on its own without needing a manual reconnect.

### What OpenRGB can control

OpenRGB works with most major RGB brands: ASUS Aura Sync, Gigabyte RGB Fusion, MSI Mystic Light, ASRock Polychrome, Corsair iCUE-compatible devices, NZXT HUE 2, and hundreds of others. Check the OpenRGB device compatibility list at [openrgb.org](https://openrgb.org) for your specific hardware.

---

## Fan Curves

Fan curves let you define exactly how fast each fan should spin at each temperature. Instead of a single fixed speed, the fan gradually speeds up as things get hotter and slows down as they cool off.

### Built-in presets

| Preset | What it does |
|---|---|
| **Silent** | Fans stop below 35°C, very quiet up to ~55°C, ramps up after that |
| **Balanced** | Moderate speeds across the range, good for everyday use |
| **Performance** | Fans start faster and ramp up earlier |
| **Gaming** | Higher baseline, aggressive ramp at 70°C+ |
| **Full Speed** | 100% always — maximum cooling, maximum noise |
| **Fixed 30% / 50%** | Constant speed regardless of temperature |

### Drawing your own curve

Go to the **Fan Curves** tab. Click anywhere on the graph to add a point. Drag points to adjust them. Right-click a point to remove it. You can also set:

- **Which temperature sensor drives the curve** — CPU temp, GPU temp, or "use the highest reading"
- **Hysteresis** — how many degrees the temperature must change before the fan speed changes. Prevents the fan from rapidly oscillating when temperature bounces around
- **Minimum speed** — the fan will never go below this percentage, even at low temperatures
- **Fan stop temperature** — below this temperature the fan turns off completely (zero RPM)

### Assigning a curve to a fan

Go to **Fan Control**, find the fan you want, and choose a curve from the **Curve** dropdown. The curve runs in the background automatically.

---

## Profiles

Profiles save your entire configuration — which curves are assigned to which fans, fixed speeds, and RGB settings — under a name. Switch between them instantly.

**Example profiles you might create:**
- **Silent Night** — everything at minimum, fan stop enabled
- **Work** — balanced, quiet enough to focus
- **Gaming** — aggressive cooling, RGB at full color
- **Rendering** — maximum cooling for long CPU/GPU jobs

Profiles are saved to `~/.config/fanhub/profiles/`. They are plain JSON files — you can back them up, share them, or edit them manually if you want.

---

## Laptop Support

Fan Hub works on laptops for temperature monitoring and fan reading on many models. Full fan speed control depends on the laptop and kernel driver:

- **ThinkPad** — good support via `thinkpad_acpi` kernel module
- **ASUS** — partial support via `asus-nb-wmi`
- **Dell** — partial support via `dell_smm`
- **HP** — limited support
- **Most others** — temperature reading works; fan control may not

If your laptop fans show up but cannot be controlled, the motherboard firmware likely manages them directly and does not expose PWM control through the kernel. This is very common on laptops and is a hardware/firmware limitation, not a Fan Hub limitation.

---

---

# Technical Reference

*Everything below is for advanced users, developers, and people who want to understand exactly how Fan Hub works.*

---

## Architecture

```
fanhub/
├── main.py                      Entry point, icon loading, stylesheet
├── core/
│   ├── app_state.py             Config persistence (~/.config/fanhub/)
│   ├── hardware_monitor.py      hwmon sysfs reader/writer + GPU temp backends
│   ├── fan_curves.py            Curve interpolation, hysteresis, presets, engine
│   ├── rgb_manager.py           OpenRGB SDK + CLI integration, binary discovery
│   ├── liquidctl_manager.py     liquidctl AIO/hub control
│   └── polling_worker.py        QThread background loop, curve application
└── ui/
    ├── main_window.py           Main window, tab host, tray, emergency controls
    ├── dashboard_tab.py         Live gauges (FlowLayout), history chart
    ├── fan_control_tab.py       Per-fan sliders, mode, curve assignment
    ├── fan_curves_tab.py        Interactive SVG-like canvas curve editor
    ├── fan_warning_dialog.py    Startup 0-RPM warning + compatibility guide
    ├── rgb_tab.py               OpenRGB tab with live status bar
    ├── liquid_tab.py            liquidctl device panels
    ├── profiles_tab.py          Profile save/load/manage
    └── settings_tab.py          App-wide settings
```

## Hardware Backends

### hwmon sysfs (`/sys/class/hwmon`)

The primary backend. Fan Hub reads every `hwmon*` directory and maps:

| sysfs file | Purpose |
|---|---|
| `fanN_input` | Current fan RPM |
| `pwmN` | PWM duty cycle (0–255) |
| `pwmN_enable` | `0`=DC, `1`=PWM manual, `2`=PWM auto |
| `tempN_input` | Temperature in millidegrees C |
| `tempN_crit` | Critical threshold |
| `tempN_max` | High threshold |
| `fanN_label` | Human-readable name |

Fan paths are stored at discovery time and read directly — no path reconstruction at runtime.

### NVIDIA GPU temperatures

Reads via `nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits`. Called every poll cycle. Requires the NVIDIA proprietary driver.

### AMD GPU temperatures

Reads via `rocm-smi --showtemp --json`. Requires ROCm. AMD GPU temperature is also available through hwmon via the `amdgpu` kernel driver without ROCm.

### liquidctl

Used for USB-connected fan controllers and AIO coolers. Fan Hub calls the `liquidctl` CLI (JSON output mode with text fallback) to read status and send control commands. Devices are auto-discovered via `liquidctl list`.

**Supported device families (partial list):**

| Device | Fan | Pump | RGB |
|---|---|---|---|
| NZXT Kraken X/Z/Elite | ✓ | ✓ | ✓ |
| Corsair Hydro H60/H100/H115/H150 | ✓ | — | ✓ |
| Corsair Commander Pro | ✓ | — | ✓ |
| NZXT Smart Device 2 / Grid+ | ✓ | — | ✓ |
| EVGA CLC | ✓ | — | — |
| Aqua Computer devices | ✓ | ✓ | ✓ |

Full list: [liquidctl supported devices](https://github.com/liquidctl/liquidctl#supported-devices)

### OpenRGB

Fan Hub connects to the OpenRGB SDK server over TCP (default: `localhost:6742`). It uses the `openrgb-python` SDK when available, falling back to the CLI with `--server-host` and `--server-port` flags.

**Binary discovery order:**
1. System `PATH` (deb install → `/usr/bin/openrgb`)
2. `dpkg -L openrgb` (deb installed but not on PATH)
3. Any file containing `openrgb` (case-insensitive) in: `~/Downloads`, `~/Applications`, `~/.local/bin`, `~/bin`, `~/Desktop`, `/opt`, `/usr/local/bin`
4. Flatpak (`org.openrgb.OpenRGB`)
5. Snap (`/snap/bin/openrgb`)

The AppImage filename does not matter — `OpenRGB_1.0rc2_x86_64_0fca93e.AppImage` and `openrgb-latest.AppImage` are both found automatically.

## Fan Curve Engine

### Interpolation

Curves are piecewise linear between control points, sorted by temperature. For a given temperature:

```
ratio = (temp - point[i].temp) / (point[i+1].temp - point[i].temp)
speed = point[i].speed + ratio * (point[i+1].speed - point[i].speed)
```

Speed is clamped to `[min_speed, max_speed]`. If `stop_below` is set and `temp < stop_below`, speed is forced to 0.

### Hysteresis

Prevents rapid fan oscillation when temperature fluctuates around a boundary:

- If `|target - last| < hysteresis × 0.5` → hold current speed (no change)
- If `target > last` → apply fully (respond quickly to heating)
- If `target < last` and `(last - target) < hysteresis` → hold current speed (slow to cool down)

### Application loop

The `PollingWorker` QThread runs every `poll_interval_ms` (default 1000 ms):
1. Read all hwmon temperatures
2. Emit `sensors_updated` signal to UI
3. For each fan with a curve assignment: compute target speed → write to `pwmN` sysfs
4. Read all fan RPMs → emit `fans_updated`
5. Read liquidctl device status → emit `liquid_updated`
6. If max temp ≥ emergency threshold → emit `emergency_triggered` → set all fans to 100%

## PWM vs DC Mode Detection

Fan Hub reads `pwmN_enable` to determine mode:

| Value | Mode | Control method |
|---|---|---|
| `0` | DC | Voltage control via PWM duty at DC enable |
| `1` | PWM manual | Direct PWM duty cycle write |
| `2` | PWM auto | Motherboard-controlled (no manual override active) |
| file absent | Unknown | Assume DC if no PWM file, assume PWM if PWM file present |

To enable manual control, Fan Hub writes `1` to `pwmN_enable` before writing the duty cycle. To restore auto, it writes `2`.

## Fan Type Classification

Each detected fan is classified by connection type using label and chip name heuristics:

| Type constant | Meaning |
|---|---|
| `sys_fan` | SYS_FAN / CHA_FAN motherboard header |
| `cpu_fan` | CPU_FAN header |
| `chassis_fan` | Chassis fan alias |
| `pump` | AIO pump header (W_PUMP+, AIO_PUMP) |
| `laptop` | Laptop internal fan (detected by chip name) |
| `usb_hub` | Corsair/NZXT USB hub channel (via liquidctl) |
| `generic` | Uncontrollable — own internal controller |

Laptop chips detected: `thinkpad_acpi`, `asus-nb-wmi`, `toshiba`, `dell_smm`, `applesmc`, `ideapad`, `hp-wmi`

## Permissions & udev

Fan Hub requires write access to `/sys/class/hwmon/hwmon*/pwm*` to control fan speeds.

**udev rule (installed automatically by `install.sh`):**
```
KERNEL=="hwmon*", SUBSYSTEM=="hwmon", ACTION=="add", RUN+="/bin/chmod -R a+w /sys%p"
```

Save to `/etc/udev/rules.d/99-fanhub.rules` and run:
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

For liquidctl USB devices, udev rules granting `uaccess` are installed for: Corsair (1b1c), NZXT (2433), Cooler Master (2516), EVGA (3842), Thermaltake (264a), Aqua Computer (0c70), MSI (0db0), ASUS (0b05).

## Kernel Modules

Loaded by the installer, persisted in `/etc/modules-load.d/fanhub.conf`:

| Module | Used for |
|---|---|
| `nct6775` | Most ASUS and Gigabyte boards (SuperIO) |
| `it87` | Most MSI and ASRock boards (ITE SuperIO) |
| `coretemp` | Intel CPU package temperature |
| `i2c-dev` | I2C bus access for some sensors |

If your fans are not detected, try loading the module manually:
```bash
sudo modprobe nct6775    # ASUS / Gigabyte
sudo modprobe it87       # MSI / ASRock
sudo modprobe nct6798    # Newer ASUS (Z790, X670)
```

## Config File Locations

| Path | Contents |
|---|---|
| `~/.config/fanhub/config.json` | Settings, active profile name |
| `~/.config/fanhub/profiles/` | Directory (profiles stored in config.json) |
| `~/.config/fanhub/fanhub.log` | Application log |
| `/opt/fanhub/` | Application files (installed by install.sh) |
| `/usr/local/bin/fanhub` | Launcher script |
| `/etc/udev/rules.d/99-fanhub.rules` | hwmon + USB udev rules |
| `/usr/share/applications/fanhub.desktop` | App menu entry |

## Dependencies

| Package | Required | Purpose |
|---|---|---|
| `PyQt6` | **Yes** | UI framework |
| `PyQt6-Charts` | Optional | Temperature history graph (tab shows message if missing) |
| `liquidctl` | Optional | AIO and USB hub control |
| `openrgb-python` | Optional | OpenRGB SDK (CLI fallback available) |
| `psutil` | Optional | Additional system info |
| `Pillow` | Optional | Icon resizing at install time |
| `lm-sensors` | Optional | Sensor detection (`sensors-detect`) |

Install all optional dependencies:
```bash
pip install PyQt6 PyQt6-Charts liquidctl openrgb-python psutil Pillow
```

## Known Limitations (Beta)

- **No autostart service** — Fan Hub must be running for curves to apply. Fans return to motherboard auto when it closes.
- **Laptop fan control** — Highly firmware-dependent. Many laptops do not expose PWM control through the kernel at all.
- **Generic RGB fans** — Apevia, Rosewill, and similar brands with internal controllers cannot be speed-controlled and may or may not appear in OpenRGB.
- **AMD GPU fan control** — Temperature reading works via ROCm or hwmon. Direct AMD GPU fan curve control is not yet implemented (would require `rocm-smi` or AMDGPU sysfs writes).
- **Wayland tray icon** — System tray icon may not appear on all Wayland compositors. The application itself works fine.
- **Multi-GPU** — Temperature reading works for all GPUs. Fan control for secondary GPUs depends on driver exposure through hwmon.

## Troubleshooting

**No fans detected**
```bash
ls /sys/class/hwmon/*/fan*_input   # should list files
sudo modprobe nct6775              # try loading the SuperIO module
sudo sensors-detect                # let lm-sensors find the right module
```

**Can't write fan speeds (Permission denied)**
```bash
# Option 1: install udev rule (Settings tab → copy to clipboard)
echo 'KERNEL=="hwmon*", SUBSYSTEM=="hwmon", ACTION=="add", RUN+="/bin/chmod -R a+w /sys%p"' \
  | sudo tee /etc/udev/rules.d/99-fanhub.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# Option 2: just run as root
sudo fanhub
```

**OpenRGB not connecting**
```bash
# Check server is running
ss -tlnp | grep 6742
# Start it
./OpenRGB*.AppImage --server --server-port 6742 &
# Check Fan Hub log
tail -f ~/.config/fanhub/fanhub.log
```

**liquidctl device not found**
```bash
sudo liquidctl list               # check if device is visible
sudo usermod -aG plugdev $USER    # add user to plugdev group, then log out/in
liquidctl initialize              # some devices need initialization
```

---

## License

MIT License — free for personal and commercial use.

## Contributing

Fan Hub is open for contributions. Areas that would benefit most from help:
- Testing on diverse hardware (different motherboard brands, chipsets)
- Laptop fan control improvement
- AMD GPU fan control
- Additional liquidctl device testing
- Translations

---

<div align="center">

*Fan Hub is not affiliated with NZXT, Corsair, OpenRGB, or any hardware manufacturer.*
*All product names are trademarks of their respective owners.*

</div>
