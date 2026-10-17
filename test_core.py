import os, tempfile, unittest

import core


def cfg(**kw):
    c = dict(core.DEFAULTS)
    c.update(kw)
    return c


def stats(load1=1.0, mem=50.0, swap=10.0, temp=50.0):
    return {'load1': load1, 'mem_avail_pct': mem, 'swap_used_pct': swap,
            'temp_c': temp}


class TestBreaches(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(core.breaches(stats(), cfg()), set())

    def test_each_metric(self):
        self.assertEqual(core.breaches(stats(load1=9.0), cfg()), {'load'})
        self.assertEqual(core.breaches(stats(mem=4.0), cfg()), {'mem'})
        self.assertEqual(core.breaches(stats(swap=91.0), cfg()), {'swap'})
        self.assertEqual(core.breaches(stats(temp=81.0), cfg()), {'temp'})

    def test_no_temp_sensor_never_breaches(self):
        self.assertNotIn('temp', core.breaches(stats(temp=None), cfg()))


class TestCounters(unittest.TestCase):
    def test_sustained_trigger_and_reset(self):
        c = cfg(interval=5, mem_window=15)   # needs 3 checks
        ctr = {}
        self.assertEqual(core.update_counters(ctr, {'mem'}, c), [])
        self.assertEqual(core.update_counters(ctr, {'mem'}, c), [])
        self.assertEqual(core.update_counters(ctr, {'mem'}, c), ['mem'])
        ctr2 = {}
        core.update_counters(ctr2, {'mem'}, c)
        core.update_counters(ctr2, set(), c)      # recovered: resets
        self.assertEqual(core.update_counters(ctr2, {'mem'}, c), [])

    def test_windows_per_metric(self):
        c = cfg(interval=5, temp_window=60, load_window=300)
        self.assertEqual(core.required_checks(c, 'temp'), 12)
        self.assertEqual(core.required_checks(c, 'load'), 60)


class TestRebootPolicy(unittest.TestCase):
    def test_boot_grace(self):
        r = core.reboot_allowed({'reboots': []}, 1000, uptime=100, cfg=cfg())
        self.assertIn('boot grace', r)

    def test_cooldown(self):
        st = {'reboots': [1000.0]}
        r = core.reboot_allowed(st, 1000 + 600, uptime=100000, cfg=cfg())
        self.assertIn('cooldown', r)
        self.assertIsNone(core.reboot_allowed(st, 1000 + 1900, 100000, cfg()))

    def test_daily_cap(self):
        st = {'reboots': [100.0, 200.0, 300.0]}
        now = 100.0 + 80000
        r = core.reboot_allowed(st, now, uptime=100000, cfg=cfg(cooldown=60))
        self.assertIn('daily cap', r)

    def test_disabled(self):
        self.assertIn('disabled', core.reboot_allowed({'reboots': []}, 1000,
                                                      100000, cfg(reboot_enabled=False)))

    def test_allowed(self):
        self.assertIsNone(core.reboot_allowed({'reboots': []}, 100000, 100000, cfg()))

    def test_record_prunes_old(self):
        st = {'reboots': [1.0]}
        core.record_reboot(st, 90000.0)
        self.assertEqual(st['reboots'], [90000.0])


class TestFiles(unittest.TestCase):
    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'sub', 'state.json')
            st = {'reboots': [1.0, 2.0]}
            core.save_state(p, st)
            self.assertEqual(core.load_state(p), st)
            self.assertEqual(core.load_state(os.path.join(d, 'nope.json')),
                             {'reboots': []})

    def test_meminfo_parse(self):
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write('MemTotal: 1000 kB\nMemAvailable: 250 kB\n'
                    'SwapTotal: 100 kB\nSwapFree: 10 kB\n')
            path = f.name
        mem, swap = core.read_meminfo(path)
        os.unlink(path)
        self.assertAlmostEqual(mem, 25.0)
        self.assertAlmostEqual(swap, 90.0)

    def test_config_file(self):
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write('load1_max = 4.0\n# comment\ninterval=2\nbogus = 9\n')
            path = f.name
        c = core.load_config(path)
        os.unlink(path)
        self.assertEqual(c['load1_max'], 4.0)
        self.assertEqual(c['interval'], 2)
        self.assertNotIn('bogus', c)
        self.assertEqual(core.load_config('/nonexistent.conf')['load1_max'],
                         core.DEFAULTS['load1_max'])


class TestWatchdog(unittest.TestCase):
    def test_arm_feed_disarm_on_fake_device(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        wd = core.Watchdog(path)
        self.assertTrue(wd.arm())
        self.assertTrue(wd.armed)
        wd.feed()
        wd.disarm()
        self.assertFalse(wd.armed)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), b'1V')   # feed byte + magic close 'V'
        os.unlink(path)

    def test_arm_failure_is_clean(self):
        wd = core.Watchdog('/nonexistent/watchdog')
        self.assertFalse(wd.arm())
        self.assertFalse(wd.armed)
        wd.feed(); wd.disarm()   # no-ops, no exceptions


class TestRebootCmd(unittest.TestCase):
    def test_systemctl_first_then_fallback(self):
        calls = []
        def fake_run(cmd, check):
            calls.append(cmd)
            if cmd[0] == 'systemctl':
                raise FileNotFoundError()
            return None
        self.assertTrue(core.do_reboot(run=fake_run))
        self.assertEqual(calls, [['systemctl', 'reboot'], ['reboot']])

    def test_all_fail(self):
        def fake_run(cmd, check):
            raise FileNotFoundError()
        self.assertFalse(core.do_reboot(run=fake_run))


if __name__ == '__main__':
    unittest.main()
