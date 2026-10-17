# watchgoose 1.1.0

Restart your Pi **before** it freezes. watchgoose is a fullscreen terminal monitor that watches load, memory, swap and temperature, and - if trouble holds long enough - cleanly reboots the Pi while it can still reboot cleanly. It can also feed the Raspberry Pi hardware watchdog, which is the only thing that catches a *hard* kernel freeze. Zero dependencies: Python 3 and curses.

## Run at boot (systemd service, v1.1.0)

Install the service once, as root, from the unpacked app folder:

```
sudo bash app-store.sh service
```

This copies the app to `/usr/local/share/watchgoose`, puts a `watchgoose` command on PATH, writes `/etc/watchgoose.conf` (only if you do not have one), installs `watchgoose.service`, and enables + starts it. The service runs the same core loop headlessly (`watchgoose --service`, no curses) and logs to the journal: `journalctl -u watchgoose -f`.

Defaults are safe: reboot-on-sustained-critical is ON (a breach must hold for its whole window; boot grace 5 min, 30 min cooldown, max 3 reboots/day), and the `/dev/watchdog` hardware watchdog is NOT armed unless you set `watchdog_arm=true` in `/etc/watchgoose.conf` (that is what catches a hard kernel freeze). Edit thresholds in the same file, then `sudo systemctl restart watchgoose`.

Easy off switch: `sudo bash app-store.sh service-off` (or `sudo systemctl disable --now watchgoose`). A clean stop disarms the hardware watchdog with the magic close, so stopping the service never reboots the Pi. The reboot path itself was never exercised on a real Pi; the decision logic is unit-tested.

## Run interactively

```
python3 watchgoose.py          # monitor any Linux box
sudo python3 watchgoose.py     # root: can arm /dev/watchdog and reboot
```

Keys: `q` quit, `w` arm/disarm the hardware watchdog, `d` dry-run on/off (watch and log, never reboot).

## How it decides

- Four gauges: 1-minute load, memory available %, swap used %, SoC temperature.
- A breach must be **sustained** (default: load >= 8 for 5 min, memory available <= 5% for 2 min, swap >= 90% for 2 min, temp >= 80 C for 1 min). A brief spike never reboots.
- When a threshold holds, watchgoose reboots via `systemctl reboot` (clean, services stop properly).

## Changelog

1.1.0: `--service` headless mode (same loop, journal logging), shipped systemd unit, `app-store.sh service` / `service-off` installer actions, `/etc/watchgoose.conf` with safe defaults, hardware watchdog off unless `watchdog_arm=true`, boolean config keys now parse correctly. 1.0.0: first release.

## Honest limits

- If the kernel is **hard frozen**, no userspace app can run - watchgoose's own reboot path cannot fire. That is what the hardware watchdog (`w`) is for: while armed, watchgoose feeds `/dev/watchdog` every check; if the machine freezes, feeding stops and the hardware reboots the Pi. This needs root and the `bcm2835_wdt` module (`sudo modprobe bcm2835_wdt`).
- Arming the watchdog is a real commitment: if watchgoose is killed (not clean `q` exit), feeding stops and the Pi reboots. On a clean quit it writes the magic close (`V`) first.

## Anti reboot-loop protection

- Boot grace: no action in the first 5 minutes after boot.
- Cooldown: at most one watchgoose reboot per 30 minutes.
- Daily cap: at most 3 watchgoose reboots per day.
- Everything is logged to `/var/log/watchgoose.log` (root) or `~/.local/state/watchgoose/watchgoose.log`.

## Configuration

Optional `/etc/watchgoose.conf`, one `key = value` per line, e.g.:

```
load1_max = 6.0
temp_max_c = 75
reboot_enabled = true
```

See `DEFAULTS` in `core.py` for every key. No config file is needed to start.

## Status

Unit tests and the terminal (PTY) checks pass on x86-64 Linux. It has NOT yet run on a real Raspberry Pi; the first launch on your Pi is the first real test there. Thresholds default to conservative values on purpose - tune `/etc/watchgoose.conf` once you see it run.

## License

MIT - Greenisus1. Original app; not affiliated with Raspberry Pi Ltd.

Built with AI assistance from my design.
