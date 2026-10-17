'''Event-driven PTY smoke test for watchgoose (demo mode).'''
import fcntl, os, pty, re, select, struct, subprocess, tempfile, termios, time

HERE = os.path.dirname(os.path.abspath(__file__))
BUF = bytearray()


def wait_out(fd, patterns, timeout=20):
    '''Wait until every regex has appeared in the SHARED buffer.'''
    need = {p: False for p in patterns}
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if fd in r:
            try:
                BUF.extend(os.read(fd, 65536))
            except OSError:
                pass
        text = BUF.decode('utf-8', 'replace')
        for p in need:
            if not need[p] and re.search(p, text):
                need[p] = True
        if all(need.values()):
            return
    raise SystemExit('TIMEOUT waiting for %s; got: %r'
                     % ([p for p, v in need.items() if not v], bytes(BUF[-400:])))


def main():
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
    env = dict(os.environ, TERM='xterm-256color', WATCHGOOSE_DEMO='1',
               HOME=tempfile.mkdtemp())
    p = subprocess.Popen(['python3', os.path.join(HERE, 'watchgoose.py')],
                         stdin=slave, stdout=slave, stderr=slave, env=env,
                         close_fds=True)
    os.close(slave)
    fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
    try:
        wait_out(master, [r'W A T C H G O O S E', r'load 1m', r'mem free',
                          r'swap used', r'\[DEMO\]', r'DRY-RUN'])
        # demo drives memory down to the breach; the block must be logged
        wait_out(master, [r'mem threshold held - BLOCKED'], timeout=90)
        # w in demo reports unavailable; d toggles dry-run off (LIVE)
        os.write(master, b'w')
        wait_out(master, [r'not available in demo'])
        os.write(master, b'q')
        deadline = time.time() + 10
        while time.time() < deadline and p.poll() is None:
            time.sleep(0.1)
        if p.poll() is None:
            p.kill()
            raise SystemExit('FAIL: did not exit on q')
        if p.returncode != 0:
            raise SystemExit('FAIL: exit %d' % p.returncode)
        print('PTY PASS')
    finally:
        if p.poll() is None:
            p.kill()
        os.close(master)


if __name__ == '__main__':
    main()
