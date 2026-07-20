<div align="center">

<img src="icon.png" width="140" alt="Fan Hub"/>

</div>

# Fan Hub

**Linux fan control, the way it should work.**

v1.6.0 · Python 3.10+ · PyQt6 · Ubuntu · Arch · Fedora · Any systemd, runit, or OpenRC distro

## Why Fan Hub Exists

On Windows, fan control is solved. **Argus Monitor**, **FanControl**, **HWiNFO**, and **NZXT CAM** give you a graphical interface where you draw a temperature-to-speed curve, assign it to a fan, save it as a profile, and forget about it. The software runs in the background, the curves stay active at boot, and everything just works.

On Linux, none of that existed. The traditional answer has been to edit `/etc/fancontrol` and run `pwmconfig` in a terminal, a tool with no graphical interface, no GPU or AIO support, and no profiles.

Fan Hub is the Windows fan control experience, rebuilt for Linux:

- Draw fan curves visually, and watch the current temperature move along them in real time
- One background daemon keeps your curves active at boot and when the app is closed
- GPU fans, AIO pumps, USB hubs, and motherboard headers all in one place
- Profiles you can save, load, export, and share
- A guided setup wizard on first launch
- One-click diagnostics with "Fix It" buttons that handle permissions and modules
- Update checker for Fan Hub, and links to OpenRGB

---

<img width="1920" height="1080" alt="Screenshot_20260720_141221" src="https://github.com/user-attachments/assets/09c3860f-a418-439b-b72e-9e2ca25c627e" />
<img width="1920" height="1080" alt="Screenshot_20260720_141231" src="https://github.com/user-attachments/assets/75ad92f3-4a63-45ca-8671-2937a48c51bc" />
<img width="1920" height="1080" alt="Screenshot_20260720_141251" src="https://github.com/user-attachments/assets/525e48e2-fd0e-40a6-a98b-582ae1803c4b" />
<img width="1920" height="1080" alt="Screenshot_20260720_141259" src="https://github.com/user-attachments/assets/4d4698c0-57bd-44da-9c36-988c2f95d67f" />
<img width="1920" height="1080" alt="Screenshot_20260720_141321" src="https://github.com/user-attachments/assets/77761251-b3b8-4c81-8a80-02b2608a74ab" />


| Feature           |     Supported    |
| ----------------- | :--------------: |
| Motherboard Fans  |         ✅        |
| AMD GPUs          |         ✅        |
| NVIDIA GPUs       |         ✅        |
| Intel GPUs        | Temperature Only |
| AIO Coolers       |         ✅        |
| Profiles          |         ✅        |
| Background Daemon |         ✅        |
| RGB Integration   |         ✅        |

---

## What's New

- Fixed daemon synchronization
- Added calibration wizard
- Improved sensor names
- Added System Overview
- Better OpenRC/runit support
Read the full [CHANGELOG](https://github.com/bobbycomet/Fan-Hub/blob/main/CHANGELOG.md)
---

## What Fan Hub Can Control

### Motherboard fan headers

Any 3-pin or 4-pin fan plugged into a SYS_FAN, CHA_FAN, CPU_FAN, or PUMP header is controllable if your motherboard's sensor chip is supported by the kernel. This covers most ASUS and Gigabyte boards (Nuvoton chips) and most MSI and ASRock boards (ITE chips). If your fans show up in the `sensors` command, Fan Hub can control them.

### GPU fans

- **AMD** — full temperature, speed, and control support
- **NVIDIA** — temperature and speed always shown; direct speed control needs CoolBits enabled; otherwise Fan Hub reads and displays the fan's own percentage honestly instead of guessing
- **Intel** — temperature only; Intel manages its own GPU fan speed in the driver/firmware, so no external app can override it

### AIO coolers and USB hubs (via LiquidCtl)

Supports most NZXT Kraken, Corsair Hydro/iCUE, EVGA CLC, Aquacomputer, and Lian Li devices, among others. This feature is implemented but not personally tested on real hardware.

### What Fan Hub cannot control

- **Fans with their own built-in controller** — cheap RGB fans that plug into a Molex or SATA power connector manage their own speed and have no connection to the motherboard
- **2-pin fans** — always full speed, no way to read or control them
- **Daisy-chained fans on one header** — they all spin together as a group; this is a wiring limitation, not a Fan Hub limitation
- **Intel integrated GPU fans** — controlled entirely by Intel's own driver

Every fan that can't be controlled has a **?** button in the Fan Control tab explaining exactly why.

---

## Interface

### Dashboard

Live temperature readings for every sensor on your system, fan RPM cards, and (new in 1.6.0) a System Overview panel showing overall CPU, GPU, RAM, network, and storage activity.

### Fan Control

One card per fan, showing its name, current speed, and a mode selector: Auto (hardware default), Curve (follows a temperature curve), Fixed % (constant speed), or Manual slider (drag to any speed). Fans that read speed backwards can be fixed with one click of the Calibrate button.

### Fan Curves

Click to add points to a curve, drag to reshape it, right-click to remove a point. A live marker shows your current temperature and the speed being commanded right now. Comes with six built-in presets: Silent, Balanced, Performance, Gaming, Full Speed, and Fixed 30%.

### Profiles

Save named setups, load them back, duplicate them, or export/import them as shareable files.

### RGB Lighting

Connects to a running OpenRGB server and can shift lighting color based on temperature.

### Liquid / AIO

Panels for supported AIO coolers and USB hub devices, showing pump speed, fan speed, and liquid temperature.

### Settings

Poll rate, temperature units, safe mode, emergency shutoff temperature, tray icon behavior, and background daemon controls, including live status (Running/Enabled but stopped/Stopped/Not installed).

---

## Background Daemon

The daemon keeps your fan curves running even when Fan Hub's window is closed, and applies them automatically at every boot. Enable it from **Settings → Background Daemon**. When you change a curve or load a profile in the app, the daemon picks up the change within one poll cycle, no restart needed. It's the same daemon-and-app coordination fix described above that makes this reliable in 1.6.0.

---

## Installing and Uninstalling

### install.sh — installs or updates Fan Hub

Run this after extracting the Fan Hub tarball:

```
./FanHub-1.6.0-x86_64.AppImage --install 
# This runs the included install.sh embedded in the appimage
```

<details>
<summary><b>Click to expand: What the installer does under the hood</b></summary>

1. **Figures out your Linux distribution** and installs the handful of system packages Fan Hub needs (Python, sensor tools, USB/HID libraries) using whichever package manager your distro uses: `apt`, `pacman`, `dnf`, `zypper`, `xbps`, or `apk`. Arch, Debian, Ubuntu, Fedora, openSUSE, Void, and Alpine are all handled automatically; a few less common distros (Gentoo, NixOS) get instructions instead, since their package systems don't work well with an automatic installer.
2. **Runs hardware sensor detection** so your motherboard's temperature and fan chips are recognized by the system.
3. **Detects whether this is a fresh install or an update.** If Fan Hub is already installed, it stops the running app and daemon first, and your existing settings and profiles are left untouched.
4. **Sets up a private Python environment** for Fan Hub so it doesn't interfere with any other Python software on your system, and installs Fan Hub's own dependencies into it.
5. **Copies the application files** into `/opt/fanhub` and creates a desktop icon and launcher so Fan Hub shows up in your applications menu and can be run by typing `fanhub`.
6. **Sets up permissions safely.** Rather than making fan controls writable by everyone, or requiring the app to always run as root, it creates a dedicated `fanhub` group, adds your user account to it, and grants that group access to only the specific files needed to control fans; nothing else on your system is affected.
7. **Loads the necessary kernel modules** for your sensors and sets them to load automatically on every future boot.
8. **Detects your init system** (systemd, runit, or OpenRC, new in 1.6.0) and installs the background daemon the correct way for your system, so fan curves keep running after a reboot.
9. **Sets up OpenRGB's server** as a background service automatically, if OpenRGB is installed.

After it finishes, log out and back in once (so your new group permissions take effect), then run `fanhub`. If you don't want to log out right away, `sudo fanhub` works immediately.

Running `./FanHub-1.6.0-x86_64.AppImage --install` again later, for example, after downloading a newer version, safely updates Fan Hub in place without touching your saved profiles or settings.

</details>

### uninstall.sh — removes Fan Hub

```
./FanHub-1.6.0-x86_64.AppImage --uninstall
# This runs the included uninstall.sh embedded in the appimage
```

This asks for confirmation, then removes everything the `install.sh` put in place: the daemon service, the app files in `/opt/fanhub`, the desktop icon, the launcher commands, and the udev permission rules. It deliberately leaves two things behind:

- Your settings and saved profiles, at `~/.config/fanhub/`; delete this yourself with `rm -rf ~/.config/fanhub` if you want a completely clean slate
- The `fanhub` user group, harmless to leave; remove it yourself with `sudo groupdel fanhub` if you'd like

### update_icon.sh quick icon-only refresh

A small utility for pulling in a newer app icon without re-running the full installer. Copies the icon files from the extracted folder into the installed app and into your system's icon theme, then refreshes the icon cache. Only useful if you just want new icon artwork; a real version update should use `install.sh` instead.

---

## First Run

The first time Fan Hub opens, a short setup wizard walks you through: a welcome screen, a scan showing every fan it found on your system, a choice of starting curve (with plain-language descriptions), and a confirmation screen. It's skippable and only appears once. If the setup wizard is unable to detect your hardware correctly, the terminal installation commands above can be used instead.

---

## From source

All build scripts to build the `appimage, deb file` or to embed the `install.sh and uninstall.sh` are all included. Just download the tar.gz from releases. Code is GPLv3, but the icons and names belong to the Griffin Linux project.

---

## Dependencies for developers

| Package | Required | Purpose |
|---|---|---|
| `PyQt6` | Yes | UI framework |
| `PyQt6-Charts` | Optional | Temperature history graph |
| `liquidctl` | Optional | AIO and USB hub control |
| `openrgb-python` | Optional | OpenRGB SDK |
| `psutil` | Optional | System Overview stats |

```
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
