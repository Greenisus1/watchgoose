'''watchgoose core: stats, thresholds, watchdog + reboot policy. No curses here.'''
import json, os, subprocess, time

APP = 'watchgoose'

# Conservative defaults. A breach must persist for the whole window to count.
DEFAULTS = {
    'interval': 5,            # seconds between checks
    'load1_max': 8.0,         # 1-min load average
    'load_window': 300,       # sustained seconds before action
    'mem_avail_min_pct': 5,   # MemAvailable percent
    'mem_window': 120,
    'swap_max_pct': 90,       # swap used percent
    'swap_window': 120,
    'temp_max_c': 80.0,       # SoC temperature
    'temp_window': 60,
    'boot_grace': 300,        # never act in the first 5 min after boot
    'cooldown': 1800,         # min seconds between watchgoose reboots
    'max_reboots_per_day': 3,
    'reboot_enabled': True,
    'watchdog_arm': False,     # --service only: arm /dev/watchdog
}

WATCHDOG_DEV = '/dev/watchdog'


def state_dir(root=None):
    if root is None:
        root = (os.geteuid() == 0)
    if root:
        return '/var/lib/watchgoose'
    return os.path.expanduser('~/.local/state/watchgoose')


def state_path(root=None):
    return os.path.join(state_dir(root), 'state.json')


def log_path(root=None):
    if root is None:
        root = (os.geteuid() == 0)
    if root:
        return '/var/log/watchgoose.log'
    return os.path.join(state_dir(False), 'watchgoose.log')


def load_state(path):
    try:
        with open(path) as f:
            d = json.load(f)
        if isinstance(d, dict):
            return {'reboots': [float(x) for x in d.get('reboots', [])]}
    except Exception:
        pass
    return {'reboots': []}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, path)


def log_line(path, msg):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a') as f:
            f.write('%s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
    except Exception:
        pass


def read_loadavg(proc='/proc/loadavg'):
    with open(proc) as f:
        return float(f.read().split()[0])


def read_meminfo(proc='/proc/meminfo'):
    info = {}
    with open(proc) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(':')] = int(parts[1])  # kB
    total = info.get('MemTotal', 0)
    avail = info.get('MemAvailable', 0)
    swap_total = info.get('SwapTotal', 0)
    swap_free = info.get('SwapFree', 0)
    mem_pct = (100.0 * avail / total) if total else 100.0
    swap_pct = (100.0 * (swap_total - swap_free) / swap_total) if swap_total else 0.0
    return mem_pct, swap_pct


def read_temp(path='/sys/class/thermal/thermal_zone0/temp'):
    try:
        with open(path) as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return None


def read_uptime(proc='/proc/uptime'):
    with open(proc) as f:
        return float(f.read().split()[0])


def read_stats(loadavg='/proc/loadavg', meminfo='/proc/meminfo',
               temp='/sys/class/thermal/thermal_zone0/temp'):
    mem_pct, swap_pct = read_meminfo(meminfo)
    return {
        'load1': read_loadavg(loadavg),
        'mem_avail_pct': mem_pct,
        'swap_used_pct': swap_pct,
        'temp_c': read_temp(temp),
    }


def breaches(stats, cfg):
    '''Which metrics are breaching right now.'''
    out = set()
    if stats['load1'] >= cfg['load1_max']:
        out.add('load')
    if stats['mem_avail_pct'] <= cfg['mem_avail_min_pct']:
        out.add('mem')
    if stats['swap_used_pct'] >= cfg['swap_max_pct']:
        out.add('swap')
    if stats['temp_c'] is not None and stats['temp_c'] >= cfg['temp_max_c']:
        out.add('temp')
    return out


def required_checks(cfg, metric):
    window = {'load': cfg['load_window'], 'mem': cfg['mem_window'],
              'swap': cfg['swap_window'], 'temp': cfg['temp_window']}[metric]
    return max(1, int(round(window / cfg['interval'])))


def update_counters(counters, now_breaching, cfg):
    '''Advance sustained-breach counters. Returns metrics that just triggered.'''
    triggered = []
    for metric in ('load', 'mem', 'swap', 'temp'):
        if metric in now_breaching:
            counters[metric] = counters.get(metric, 0) + 1
            if counters[metric] == required_checks(cfg, metric):
                triggered.append(metric)
        else:
            counters[metric] = 0
    return triggered


def reboot_allowed(state, now, uptime, cfg):
    '''None if a reboot is allowed, else the blocking reason.'''
    if not cfg['reboot_enabled']:
        return 'reboots disabled (dry-run)'
    if uptime < cfg['boot_grace']:
        return 'boot grace (%ds left)' % int(cfg['boot_grace'] - uptime)
    recent = [t for t in state['reboots'] if now - t < cfg['cooldown']]
    if recent:
        return 'cooldown (%ds left)' % int(cfg['cooldown'] - (now - max(recent)))
    today = [t for t in state['reboots'] if now - t < 86400]
    if len(today) >= cfg['max_reboots_per_day']:
        return 'daily cap reached'
    return None


def record_reboot(state, now):
    state['reboots'] = [t for t in state['reboots'] if now - t < 86400] + [now]


def do_reboot(run=subprocess.run):
    '''Clean reboot via systemd, falling back to /sbin/reboot.'''
    for cmd in (['systemctl', 'reboot'], ['reboot']):
        try:
            run(cmd, check=True)
            return True
        except Exception:
            continue
    return False


class Watchdog:
    '''Feeds /dev/watchdog so a HARD kernel freeze reboots the Pi.'''
    def __init__(self, dev=WATCHDOG_DEV):
        self.dev = dev
        self.fd = None

    def arm(self):
        try:
            self.fd = os.open(self.dev, os.O_WRONLY)
            return True
        except Exception:
            self.fd = None
            return False

    @property
    def armed(self):
        return self.fd is not None

    def feed(self):
        if self.fd is not None:
            try:
                os.write(self.fd, b'1')
            except OSError:
                pass

    def disarm(self):
        '''Magic close: 'V' means do not reboot when we exit cleanly.'''
        if self.fd is not None:
            try:
                os.write(self.fd, b'V')
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None


def load_config(path):
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    if k in cfg:
                        if isinstance(cfg[k], bool):
                            cfg[k] = v.lower() in ('1', 'true', 'yes', 'on')
                        else:
                            cfg[k] = type(cfg[k])(v)
    except FileNotFoundError:
        pass
    return cfg
