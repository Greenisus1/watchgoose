#!/bin/bash
# pi-app-store: 1
# pi-app-store-category: tools
# pi-app-store-description: Restarts your Pi before it freezes: watches load, memory, swap and temperature, feeds the hardware watchdog, and cleanly reboots on sustained trouble.
set -eu
cd -- "$(dirname -- "$0")"
ready() { python3 -c 'import curses' >/dev/null 2>&1; }
action=${1:-run}
case "${action,,}" in
 install)
  if ! ready; then
   [ "$(id -u)" -eq 0 ] || { echo 'Install through the Store with sudo to add Python.';exit 1; }
   if command -v apt-get >/dev/null;then apt-get update;apt-get install -y python3
   elif command -v apk >/dev/null;then apk add --no-cache python3
   elif command -v pacman >/dev/null;then echo 'Arch may upgrade the whole system; review pacman prompt.';pacman -Syu --needed python
   else echo 'Install Python 3 with curses using your distro tools.';exit 1;fi
  fi
  ready
  python3 -c 'from pathlib import Path;[compile(p.read_bytes(),str(p),"exec") for p in Path(".").glob("*.py")]' ;;
 status) ready ;;
 service)
  [ "$(id -u)" -eq 0 ] || { echo 'Run the service step with sudo: sudo bash app-store.sh service';exit 1; }
  ready
  install -d /usr/local/share/watchgoose
  install -m 0644 watchgoose.py core.py service.py /usr/local/share/watchgoose/
  printf '#!/bin/sh\nexec python3 /usr/local/share/watchgoose/watchgoose.py "$@"\n' > /usr/local/bin/watchgoose
  chmod 755 /usr/local/bin/watchgoose
  [ -f /etc/watchgoose.conf ] || install -m 0644 watchgoose.conf.default /etc/watchgoose.conf
  install -m 0644 watchgoose.service /etc/systemd/system/watchgoose.service
  systemctl daemon-reload
  systemctl enable --now watchgoose
  echo 'watchgoose service enabled and started. Logs: journalctl -u watchgoose -f'
  echo 'Off switch: sudo bash app-store.sh service-off' ;;
 service-off)
  [ "$(id -u)" -eq 0 ] || { echo 'Run with sudo: sudo bash app-store.sh service-off';exit 1; }
  systemctl disable --now watchgoose 2>/dev/null || true
  echo 'watchgoose service stopped and disabled. Files and /etc/watchgoose.conf kept.' ;;
 run) [ "$#" -eq 0 ] || shift;exec python3 watchgoose.py "$@" ;;
 *) echo 'Use install, status or run (any casing).';exit 2 ;;
esac
