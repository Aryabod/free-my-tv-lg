#!/usr/bin/env python3
"""Opens Free My TV on an LG TV as soon as the TV turns on, from a computer on the same Wi-Fi.

    python tools/autostart.py 192.168.1.50            # run (Windows: started at logon by the "FreeMyTV Autostart" task)
    python tools/autostart.py 192.168.1.50 --check    # connect once, show the power state and the app in front, exit

LG's webOS keeps Developer Mode apps away from the power state and won't open an app when the TV turns on (its
"Power On Screen" is Home or the last input only). So this stays connected to the TV's remote control API (the one LG's
phone app uses: wss://<TV>:3001), and when the TV turns on and LG's home comes up, opens Free My TV instead, once;
pressing Home later is left alone. The first run asks on the TV to allow it; the key is kept in
~/.ssh/freemytv_autostart_<IP>. Python 3 standard library only. Logs to tools/autostart.log.
"""
import base64
import json
import os
import re
import socket
import ssl
import struct
import sys
import time

APP_ID = 'io.freemytv'
HOME_APPS = ('com.webos.app.home', 'com.webos.app.homeconnect')
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'autostart.log')
PERMISSIONS = ['LAUNCH', 'READ_POWER_STATE', 'READ_RUNNING_APPS', 'READ_INSTALLED_APPS']


def log(text):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + text
    print(line, flush=True)
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1000000:
            os.replace(LOG, LOG + '.old')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def key_path(ip):
    return os.path.join(os.path.expanduser('~'), '.ssh', 'freemytv_autostart_' + ip.replace('.', '_'))


class Socket:
    """A minimal WebSocket client (RFC 6455): text frames out (masked), text, ping and close in."""

    def __init__(self, ip):
        self.sock = None
        for port, tls in ((3001, True), (3000, False)):
            try:
                raw = socket.create_connection((ip, port), timeout=6)
                if tls:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE   # the TV's certificate is its own, self-signed
                    raw = ctx.wrap_socket(raw, server_hostname=ip)
                key = base64.b64encode(os.urandom(16)).decode()
                raw.sendall(('GET / HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                             'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (ip, port, key)).encode())
                head = b''
                while b'\r\n\r\n' not in head:
                    chunk = raw.recv(1024)
                    if not chunk:
                        raise OSError('closed during handshake')
                    head += chunk
                if b' 101 ' not in head.split(b'\r\n')[0]:
                    raise OSError('refused: ' + head.split(b'\r\n')[0].decode('latin-1'))
                self.sock, self.buf = raw, head.split(b'\r\n\r\n', 1)[1]
                return
            except (OSError, ssl.SSLError):
                continue
        raise OSError('TV not reachable')

    def send(self, obj):
        data = json.dumps(obj).encode()
        n, mask = len(data), os.urandom(4)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack('>H', n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def ping(self):
        self.sock.sendall(bytes([0x89, 0x80]) + os.urandom(4))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError('connection closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """The next text message as JSON; None on a timeout (the socket's timeout)."""
        text = b''
        while True:
            try:
                b0, b1 = self._read(2)
            except socket.timeout:
                return None
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            if b1 & 0x80:
                mask = self._read(4)
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read(n)))
            else:
                data = self._read(n)
            if op == 8:
                raise OSError('closed by the TV')
            if op == 9:   # ping: answer with a pong
                self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + b'\0\0\0\0' + data)
                continue
            if op in (0, 1):
                text += data
                if b0 & 0x80:
                    try:
                        return json.loads(text.decode('utf-8'))
                    except ValueError:
                        text = b''

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def register(ws, ip):
    path = key_path(ip)
    payload = {'forcePairing': False, 'pairingType': 'PROMPT',
               'manifest': {'manifestVersion': 1, 'appVersion': '1.0', 'permissions': PERMISSIONS}}
    if os.path.exists(path):
        with open(path) as f:
            payload['client-key'] = f.read().strip()
    ws.send({'type': 'register', 'id': 'register', 'payload': payload})
    ws.sock.settimeout(120)   # time to answer the TV's prompt the first time
    while True:
        m = ws.recv()
        if m is None:
            raise OSError('no answer to the pairing prompt')
        if m.get('type') == 'response' and (m.get('payload') or {}).get('pairingType') == 'PROMPT':
            log('Asked on the TV to allow this computer: choose Allow (once).')
        elif m.get('type') == 'registered':
            key = (m.get('payload') or {}).get('client-key')
            if key:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as f:
                    f.write(key)
            return
        elif m.get('type') == 'error':
            raise OSError('the TV refused: ' + str(m.get('error')))


def run(ip, check=False):
    """One connection. LG keeps the power state from remote apps (401), so the TV turning on is read from the app in
    front: nothing in front (off, or Quick Start+ standby) then LG's home, or a new connection (the TV was off and
    unreachable) that finds LG's home, is the TV just turned on."""
    ws = Socket(ip)
    register(ws, ip)
    ws.send({'type': 'subscribe', 'id': 'fg', 'uri': 'ssap://com.webos.applicationManager/getForegroundAppInfo'})
    ws.sock.settimeout(25)
    front, ready = None, True   # ready: the TV may have just turned on, so LG's home coming up next means power-on
    if check:
        log('Connected and allowed.')
    while True:
        m = ws.recv()
        if m is None:
            ws.ping()          # keep the connection alive; a TV that went away fails the next read
            continue
        p = m.get('payload') or {}
        if m.get('type') == 'error' or p.get('returnValue') is False:
            log('The TV refused %s: %s' % (m.get('id'), m.get('error') or p.get('errorText')))
            continue
        if m.get('id') == 'launch':
            log('Opened Free My TV.' if p.get('returnValue') else 'Could not open Free My TV: %s' % p)
            continue
        if m.get('id') != 'fg':
            continue
        app = p.get('appId') or ''
        if app != front:
            log('In front: %s' % (app or '(nothing: TV off or in standby)'))
        if check:
            ws.close()
            return
        if not app:
            ready = True       # off or in standby: the next LG home is the TV turning on
        elif app in HOME_APPS and ready:
            log('TV on: opening Free My TV.')
            ws.send({'type': 'request', 'id': 'launch', 'uri': 'ssap://system.launcher/launch', 'payload': {'id': APP_ID}})
            ready = False
        else:
            ready = False      # anything else in front (or Home pressed later): left alone
        front = app


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args or not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', args[0]):
        sys.exit(__doc__)
    ip, check = args[0], '--check' in sys.argv
    if check:
        run(ip, check=True)
        return
    log('Started, watching %s.' % ip)
    while True:
        try:
            run(ip)
        except (OSError, ssl.SSLError, ValueError) as e:
            if 'not reachable' not in str(e):
                log('Disconnected (%s); trying again.' % e)
            time.sleep(5)


if __name__ == '__main__':
    main()
