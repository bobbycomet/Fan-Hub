---

## What's New in 1.6.0

Fan Hub 1.6.0 is a stability and polish release. If you used 1.5.5, here's what's different:

### The daemon bug is fixed

In 1.5.5, the background daemon (the part that keeps your fan curves running even when the app isn't open) could get into a fight with the app itself over who was controlling a fan. This showed up as fans randomly jumping speed, or fake "emergency overheating" warnings popping up when nothing was actually wrong. That's fixed. The app and the daemon now always agree on which fan is being controlled and how, so this can't happen anymore.

### No more random resets

On some systems, Fan Hub would occasionally rebuild its whole fan list out of nowhere, interrupting whatever you were doing on the Dashboard, Fan Control, or Fan Curves screens. This was caused by Fan Hub mistaking normal background USB activity for your computer waking up from sleep. It now only rescans when the computer has actually been asleep, so this false trigger is gone.

### Backwards fans fix themselves

A small number of motherboards report fan speed backwards: 0% is actually full speed, and 100% is actually silent. I tried a manual "Invert" checkbox that most people didn't know they needed, but decided that could easily be overlooked. In 1.6.0, there's a **Calibrate** button instead. Click it, wait about 7 seconds while it spins the fan up and down to test itself, and it corrects the problem automatically. You never have to know or care that the issue existed.

### Cleaner sensor names

Some boards report the same physical temperature sensor twice under two different names, and NVIDIA graphics cards sometimes showed up with a doubled-up name like "NVIDIA NVIDIA GeForce...". Both of these are cleaned up now, so what you see in the Dashboard and Fan Control tabs matches your actual hardware, once each.

### New System Overview

The Dashboard now includes a live overview panel showing overall CPU, GPU, RAM, network, and storage activity, not just temperatures and fan speeds. This feature is still under development. Depending on your drivers, GPU or network activity may not always display correctly. These issues will be addressed in a future update.

### Smoother Fan Curves editor

The Fan Curves screen no longer breaks or clips content when the window is resized small; the panel now scrolls and resizes properly.

### Diagnostics show everything

The one-click diagnostics dialog used to cut off the sensor list after 12 entries with a dead-end "and N more" message. It now shows the full list, since the dialog already scrolls.

### Broader Linux support

1.6.0 adds a proper installer for far more distributions, and support for computers that don't use systemd.

---
