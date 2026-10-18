#!/usr/bin/env python3
'''watchgoose --service: headless monitor loop for systemd. No curses.

Same core loop as the fullscreen UI: read stats, advance sustained-breach
counters, feed the hardware watchdog ONLY if configured, and cleanly reboot
on sustained critical trouble. Logs to stdout (captured by the journal) and
to the watchgoose log file. A single bad sensor read never kills the loop.
'''
import os, signal, sys, time

import core

CONFIG = '/etc/watchgoose.conf'


def check(now, cfg, state, counters, wd, dry, statep, stats=None,
          uptime=None, out=print, do_reboot=core.do_reboot):
    '''One headless check cycle. Returns the event strings it emitted.'''
    events = []

    def ev(msg):
        events.append(msg)
        out(msg)

    if stats is None:
        stats = core.read_stats()
    if uptime is None:
        uptime = core.read_uptime()
    if wd is not None and wd.armed:
        wd.feed()
    trig = core.update_counters(counters, core.breaches(stats, cfg), cfg)
    for metric in trig:
        reason = core.reboot_allowed(state, now, uptime, cfg)
        if dry and reason is None:
            reason = 'dry-run'
        if reason:
            ev('%s threshold held - BLOCKED: %s' % (metric, reason))
        else:
            ev('%s threshold held - REBOOTING' % metric)
            core.save_state(statep, state)
            if do_reboot():
                core.record_reboot(state, now)
                core.save_state(statep, state)
            else:
                ev('reboot command failed')
    return events


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = core.load_config(CONFIG)
    arm = cfg.get('watchdog_arm', False)
    if '--watchdog' in argv:
        arm = True
    if '--no-watchdog' in argv:
        arm = False
    dry = not cfg['reboot_enabled']
    statep = core.state_path(True)
    logp = core.log_path(True)
    state = core.load_state(statep)
    counters = {'load': 0, 'mem': 0, 'swap': 0, 'temp': 0}

    def log(msg):
        line = '%s %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
        print(line, flush=True)
        core.log_line(logp, msg)

    wd = None
    if arm:
        wd = core.Watchdog()
        if wd.arm():
            log('hardware watchdog ARMED - hard freezes will reboot')
        else:
            log('no /dev/watchdog - continuing without it')
            wd = None
    log('watchgoose service starting: reboots %s, watchdog %s, interval %ds'
        % ('DISABLED (reboot_enabled=false)' if dry else 'LIVE',
           'armed' if wd else 'not armed', cfg['interval']))

    stop = []
    signal.signal(signal.SIGTERM, lambda s, f: stop.append(s))
    signal.signal(signal.SIGINT, lambda s, f: stop.append(s))

    last = 0.0
    while not stop:
        now = time.time()
        if now - last >= cfg['interval']:
            last = now
            try:
                check(now, cfg, state, counters, wd, dry, statep,
                      out=lambda m: log(m))
            except Exception as e:
                log('check failed, continuing: %r' % (e,))
        time.sleep(0.5)

    if wd is not None and wd.armed:
        wd.disarm()   # magic 'V' close: clean stop must not reboot the Pi
        log('hardware watchdog disarmed (clean exit)')
    log('watchgoose service stopped')
    return 0


if __name__ == '__main__':
    sys.exit(main())
