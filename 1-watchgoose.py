#!/usr/bin/env python3
'''watchgoose: restart your Pi BEFORE it freezes. Fullscreen terminal monitor.'''
import curses, os, sys, time

import core

VERSION = '1.1.0'
DEMO = os.environ.get('WATCHGOOSE_DEMO') == '1'


def demo_stats(t):
    '''Scripted demo: memory exhausts, stays critical, then recovers.'''
    phase = t % 80
    if phase < 25:
        mem, swap = 40.0 - phase, 30.0       # 40% -> 15% available
    elif phase < 60:
        mem, swap = 3.0, 92.0                # sustained critical stretch
    else:
        mem, swap = 55.0, 20.0               # recovered
    return {'load1': 1.2 + (t % 7) * 0.05, 'mem_avail_pct': mem,
            'swap_used_pct': swap, 'temp_c': 52.0}


class App:
    def __init__(self, scr):
        self.scr = scr
        self.cfg = core.load_config('/etc/watchgoose.conf')
        if DEMO:
            self.cfg['reboot_enabled'] = False   # demo never reboots
            self.cfg['interval'] = 1
            self.cfg['mem_window'] = 10
        self.root = (os.geteuid() == 0) and not DEMO
        self.state = core.load_state(core.state_path(self.root))
        self.logp = core.log_path(self.root)
        self.statep = core.state_path(self.root)
        self.counters = {'load': 0, 'mem': 0, 'swap': 0, 'temp': 0}
        self.events = []
        self.last_block = {}
        self.wd = None
        self.dry = not self.cfg['reboot_enabled']
        self.t0 = time.time()

    def event(self, msg):
        self.events.append(time.strftime('%H:%M:%S ') + msg)
        del self.events[:-6]
        core.log_line(self.logp, msg)

    def run(self):
        curses.curs_set(0)
        self.scr.timeout(200)
        last = 0
        while True:
            now = time.time()
            if now - last >= self.cfg['interval']:
                last = now
                self.check(now)
            self.draw(now)
            k = self.scr.getch()
            if k in (ord('q'), ord('Q')):
                return 0
            if k in (ord('w'), ord('W')):
                self.toggle_watchdog()
            if k in (ord('d'), ord('D')):
                self.dry = not self.dry
                self.event('dry-run ' + ('ON - will not reboot' if self.dry
                                         else 'OFF - reboots live'))

    def current_stats(self):
        if DEMO:
            return demo_stats(time.time() - self.t0)
        return core.read_stats()

    def check(self, now):
        stats = self.current_stats()
        self.stats = stats
        if self.wd and self.wd.armed:
            self.wd.feed()
        trig = core.update_counters(self.counters, core.breaches(stats, self.cfg),
                                    self.cfg)
        for metric in trig:
            uptime = 9999.0 if DEMO else core.read_uptime()
            reason = core.reboot_allowed(self.state, now, uptime, self.cfg)
            if self.dry and reason is None:
                reason = 'dry-run'
            if reason:
                key = (metric, reason.split('(')[0])
                if self.last_block.get(key, 0) + 60 < now:   # anti-spam, in memory only
                    self.last_block[key] = now
                    self.event('%s threshold held - BLOCKED: %s' % (metric, reason))
            else:
                self.event('%s threshold held - REBOOTING' % metric)
                core.save_state(self.statep, self.state)
                if core.do_reboot():
                    core.record_reboot(self.state, now)
                    core.save_state(self.statep, self.state)
                else:
                    self.event('reboot command failed')

    def toggle_watchdog(self):
        if DEMO:
            self.event('watchdog: not available in demo')
            return
        if self.wd and self.wd.armed:
            self.wd.disarm()
            self.event('hardware watchdog DISARMED (safe clean exit)')
        else:
            self.wd = core.Watchdog()
            if self.wd.arm():
                self.event('hardware watchdog ARMED - hard freezes will reboot')
            else:
                self.event('no /dev/watchdog (needs root + bcm2835_wdt)')

    def draw(self, now):
        s = self.scr
        s.erase()
        h, w = s.getmaxyx()
        title = ' W A T C H G O O S E '
        s.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
        s.addstr(1, 2, 'restarts your Pi before it freezes', curses.A_DIM)
        st = getattr(self, 'stats', None) or {'load1': 0, 'mem_avail_pct': 100,
                                              'swap_used_pct': 0, 'temp_c': None}
        rows = [
            ('load 1m', st['load1'], self.cfg['load1_max'],
             '%.2f / max %.1f' % (st['load1'], self.cfg['load1_max']),
             self.counters['load'], core.required_checks(self.cfg, 'load')),
            ('mem free', 100 - st['mem_avail_pct'], 100 - self.cfg['mem_avail_min_pct'],
             '%.0f%% free / min %d%%' % (st['mem_avail_pct'], self.cfg['mem_avail_min_pct']),
             self.counters['mem'], core.required_checks(self.cfg, 'mem')),
            ('swap used', st['swap_used_pct'], self.cfg['swap_max_pct'],
             '%.0f%% / max %d%%' % (st['swap_used_pct'], self.cfg['swap_max_pct']),
             self.counters['swap'], core.required_checks(self.cfg, 'swap')),
            ('temp', st['temp_c'] or 0, self.cfg['temp_max_c'],
             ('%.1fC / max %.0fC' % (st['temp_c'], self.cfg['temp_max_c']))
             if st['temp_c'] is not None else 'no sensor',
             self.counters['temp'], core.required_checks(self.cfg, 'temp')),
        ]
        y = 3
        for name, val, mx, label, cnt, req in rows:
            frac = min(1.0, val / mx) if mx else 0
            width = max(10, w - 30)
            fill = int(frac * width)
            attr = curses.A_NORMAL
            if cnt:
                attr = curses.A_REVERSE if cnt >= req else curses.A_BOLD
            s.addstr(y, 2, '%-9s' % name)
            s.addstr(y, 12, '#' * fill + '-' * (width - fill), attr)
            s.addstr(y, 13 + width, label[:w - width - 15])
            if cnt:
                s.addstr(y + 1, 12, 'held %d/%d checks' % (cnt, req), attr)
            y += 2
        wdt = ('ARMED' if (self.wd and self.wd.armed) else 'off')
        mode = 'DRY-RUN' if self.dry else 'LIVE'
        demo = '  [DEMO]' if DEMO else ''
        s.addstr(y, 2, 'watchdog: %s   mode: %s   uptime %dm%s' %
                 (wdt, mode, int((now - self.t0) / 60), demo))
        y += 2
        s.addstr(y, 2, 'events:', curses.A_DIM)
        for i, e in enumerate(self.events[-6:]):
            if y + 1 + i < h - 2:
                s.addstr(y + 1 + i, 2, e[:w - 4])
        s.addstr(h - 1, 2, 'q quit  w watchdog arm/disarm  d dry-run on/off')
        s.refresh()


def main():
    if '--version' in sys.argv:
        print(VERSION)
        return 0
    if '--service' in sys.argv:
        import service
        return service.main()
    if '--check' in sys.argv:
        print(core.read_stats())
        return 0
    app = [None]
    def go(scr):
        a = App(scr)
        app[0] = a
        return a.run()
    try:
        return curses.wrapper(go)
    finally:
        a = app[0]
        if a and a.wd and a.wd.armed:
            a.wd.disarm()   # clean exit must not trigger a hardware reboot


if __name__ == '__main__':
    sys.exit(main())
