import os, tempfile, unittest

import core, service


def cfg(**kw):
    c = dict(core.DEFAULTS)
    c.update(kw)
    return c


def stats(load1=1.0, mem=50.0, swap=10.0, temp=50.0):
    return {'load1': load1, 'mem_avail_pct': mem, 'swap_used_pct': swap,
            'temp_c': temp}


class FakeWatchdog:
    def __init__(self, armed=True):
        self.armed = armed
        self.feeds = 0
        self.disarmed = False

    def feed(self):
        self.feeds += 1

    def disarm(self):
        self.disarmed = True
        self.armed = False


class TestBoolConfig(unittest.TestCase):
    def test_bool_parsing(self):
        with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as f:
            f.write('reboot_enabled=false\nwatchdog_arm=true\ninterval=7\n')
            path = f.name
        try:
            c = core.load_config(path)
        finally:
            os.unlink(path)
        self.assertIs(c['reboot_enabled'], False)
        self.assertIs(c['watchdog_arm'], True)
        self.assertEqual(c['interval'], 7)

    def test_defaults_watchdog_off(self):
        c = core.load_config('/nonexistent.conf')
        self.assertIs(c['watchdog_arm'], False)
        self.assertIs(c['reboot_enabled'], True)


class TestServiceCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.statep = os.path.join(self.tmp, 'state.json')
        self.reboots = []

    def fake_reboot(self):
        self.reboots.append(1)
        return True

    def test_sustained_breach_reboots_and_records(self):
        c = cfg(interval=5, mem_window=15)   # 3 checks
        ctr, st = {}, {'reboots': []}
        quiet = lambda m: None
        for _ in range(2):
            ev = service.check(1000.0, c, st, ctr, None, False, self.statep,
                               stats=stats(mem=2.0), uptime=4000.0,
                               out=quiet, do_reboot=self.fake_reboot)
            self.assertEqual(ev, [])
        ev = service.check(1005.0, c, st, ctr, None, False, self.statep,
                           stats=stats(mem=2.0), uptime=4000.0,
                           out=quiet, do_reboot=self.fake_reboot)
        self.assertEqual(self.reboots, [1])
        self.assertTrue(any('REBOOTING' in e for e in ev))
        saved = core.load_state(self.statep)
        self.assertEqual(saved['reboots'], [1005.0])

    def test_dry_run_blocks(self):
        c = cfg(interval=5, mem_window=5, reboot_enabled=False)   # 1 check
        ev = service.check(1000.0, c, {'reboots': []}, {}, None, True,
                           self.statep, stats=stats(mem=2.0), uptime=4000.0,
                           out=lambda m: None, do_reboot=self.fake_reboot)
        self.assertEqual(self.reboots, [])
        self.assertTrue(any('BLOCKED' in e and 'dry-run' in e for e in ev))

    def test_boot_grace_blocks(self):
        c = cfg(interval=5, mem_window=5)
        ev = service.check(1000.0, c, {'reboots': []}, {}, None, False,
                           self.statep, stats=stats(mem=2.0), uptime=100.0,
                           out=lambda m: None, do_reboot=self.fake_reboot)
        self.assertEqual(self.reboots, [])
        self.assertTrue(any('boot grace' in e for e in ev))

    def test_cooldown_blocks_second_reboot(self):
        c = cfg(interval=5, mem_window=5)
        st = {'reboots': [900.0]}   # 100s ago, within 1800s cooldown
        ev = service.check(1000.0, c, st, {}, None, False, self.statep,
                           stats=stats(mem=2.0), uptime=4000.0,
                           out=lambda m: None, do_reboot=self.fake_reboot)
        self.assertEqual(self.reboots, [])
        self.assertTrue(any('cooldown' in e for e in ev))

    def test_armed_watchdog_is_fed(self):
        wd = FakeWatchdog(armed=True)
        service.check(1000.0, cfg(), {'reboots': []}, {}, wd, False,
                      self.statep, stats=stats(), uptime=4000.0,
                      out=lambda m: None, do_reboot=self.fake_reboot)
        self.assertEqual(wd.feeds, 1)

    def test_clean_stats_no_events(self):
        ev = service.check(1000.0, cfg(), {'reboots': []}, {}, None, False,
                           self.statep, stats=stats(), uptime=4000.0,
                           out=lambda m: None, do_reboot=self.fake_reboot)
        self.assertEqual(ev, [])
        self.assertEqual(self.reboots, [])


if __name__ == '__main__':
    unittest.main()
