#!/usr/bin/env python3
"""
aios — command-line client for the AIOS REST API (/api/v1).

A Client Builder uses this to configure their assigned client's AIOS from a
terminal. It authenticates with a scoped Bearer token issued by a super-admin in
the admin panel (Builders & Access → Issue CLI Token). The token is bound to one
tenant server-side, so every command here acts only on that client.

Zero dependencies — standard library only. Python 3.8+.

  aios login                        # paste your token once (saved to ~/.aios/config, 0600)
  aios whoami
  aios integrations list
  aios integrations connect toast_pos --field client_id=abc --field client_secret=xyz
  aios integrations test toast_pos
  aios integrations disconnect toast_pos
  aios docs list
  aios docs upload ./handbook.pdf
  aios domains list
  aios domains add app.client.com
  aios domains verify <domain_id>
  aios users list
  aios users add jane@client.com --name "Jane" --role member
  aios settings get
  aios settings set --field contact_email=ops@client.com --field notes="Q3 rollout"
"""
import os
import sys
import json
import uuid
import argparse
import getpass
import mimetypes
import urllib.request
import urllib.error

CONFIG_DIR  = os.path.join(os.path.expanduser('~'), '.aios')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config')
DEFAULT_URL = os.getenv('AIOS_URL', 'https://aios-platform-production.up.railway.app')


# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    # env vars win, so CI can run without a config file
    if os.getenv('AIOS_TOKEN'):
        return {'base_url': DEFAULT_URL.rstrip('/'), 'token': os.getenv('AIOS_TOKEN')}
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)        # owner read/write only (POSIX)
    except Exception:
        pass


# ── HTTP ──────────────────────────────────────────────────────────────────────
def _request(method: str, path: str, *, body=None, files=None, auth=True):
    cfg = load_config()
    base = (cfg.get('base_url') or DEFAULT_URL).rstrip('/')
    url  = base + path
    headers = {'Accept': 'application/json', 'User-Agent': 'aios-cli/1.0'}
    if auth:
        token = cfg.get('token')
        if not token:
            _die('Not logged in. Run:  aios login')
        headers['Authorization'] = 'Bearer ' + token

    data = None
    if files:
        data, ctype = _encode_multipart(files)
        headers['Content-Type'] = ctype
    elif body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except Exception:
            return e.code, {'ok': False, 'error': f'HTTP {e.code}'}
    except urllib.error.URLError as e:
        _die(f'Connection failed: {e.reason}  (base url: {base})')


def _encode_multipart(files: dict):
    """Minimal multipart/form-data encoder for file uploads (stdlib only)."""
    boundary = '----aios' + uuid.uuid4().hex
    body = bytearray()
    for field, path in files.items():
        fn = os.path.basename(path)
        ctype = mimetypes.guess_type(fn)[0] or 'application/octet-stream'
        with open(path, 'rb') as fh:
            content = fh.read()
        body += f'--{boundary}\r\n'.encode()
        body += (f'Content-Disposition: form-data; name="{field}"; '
                 f'filename="{fn}"\r\n').encode()
        body += f'Content-Type: {ctype}\r\n\r\n'.encode()
        body += content + b'\r\n'
    body += f'--{boundary}--\r\n'.encode()
    return bytes(body), f'multipart/form-data; boundary={boundary}'


# ── Output ────────────────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1):
    print('error: ' + msg, file=sys.stderr)
    sys.exit(code)


def _out(status: int, payload: dict):
    if isinstance(payload, dict) and payload.get('ok') is False:
        _die(payload.get('error', f'request failed (HTTP {status})'),
             code=1 if status < 500 else 2)
    print(json.dumps(payload, indent=2))


def _kv(pairs):
    """Parse repeated --field k=v into a dict."""
    out = {}
    for p in pairs or []:
        if '=' not in p:
            _die(f'--field must be key=value, got: {p}')
        k, v = p.split('=', 1)
        out[k.strip()] = v
    return out


# ── Commands ──────────────────────────────────────────────────────────────────
def cmd_login(args):
    base = (args.url or DEFAULT_URL).rstrip('/')
    token = args.token or getpass.getpass('Paste your AIOS API token (hidden): ').strip()
    if not token.startswith('aios_pat_'):
        _die('That does not look like an AIOS token (expected aios_pat_…).')
    save_config({'base_url': base, 'token': token})
    status, payload = _request('GET', '/api/v1/whoami')
    if payload.get('ok'):
        print(f"Logged in as {payload['email']} → "
              f"{payload.get('firm_name')} ({payload.get('industry')})")
        print('Scopes: ' + ', '.join(payload.get('scopes', [])))
    else:
        _die(payload.get('error', 'token rejected'))


def cmd_logout(args):
    try:
        os.remove(CONFIG_PATH)
    except FileNotFoundError:
        pass
    print('Logged out.')


def cmd_whoami(args):
    _out(*_request('GET', '/api/v1/whoami'))


def cmd_integrations(args):
    if args.action == 'list':
        q = f'?industry={args.industry}' if args.industry else ''
        _out(*_request('GET', '/api/v1/integrations' + q))
    elif args.action == 'connect':
        _out(*_request('POST', f'/api/v1/integrations/{args.platform}/connect',
                       body=_kv(args.field)))
    elif args.action == 'test':
        _out(*_request('POST', f'/api/v1/integrations/{args.platform}/test'))
    elif args.action == 'disconnect':
        _out(*_request('POST', f'/api/v1/integrations/{args.platform}/disconnect'))


def cmd_docs(args):
    if args.action == 'list':
        _out(*_request('GET', '/api/v1/documents'))
    elif args.action == 'upload':
        if not os.path.isfile(args.path):
            _die(f'No such file: {args.path}')
        _out(*_request('POST', '/api/v1/documents', files={'file': args.path}))


def cmd_domains(args):
    if args.action == 'list':
        _out(*_request('GET', '/api/v1/domains'))
    elif args.action == 'add':
        _out(*_request('POST', '/api/v1/domains', body={'domain': args.domain}))
    elif args.action == 'verify':
        _out(*_request('POST', f'/api/v1/domains/{args.domain_id}/verify'))


def cmd_users(args):
    if args.action == 'list':
        _out(*_request('GET', '/api/v1/users'))
    elif args.action == 'add':
        _out(*_request('POST', '/api/v1/users',
                       body={'email': args.email, 'name': args.name or '',
                             'role': args.role}))


def cmd_agents(args):
    if args.action == 'list':
        _out(*_request('GET', '/api/v1/agents'))
    elif args.action == 'get':
        _out(*_request('GET', f'/api/v1/agents/{args.id}'))
    elif args.action in ('create', 'update'):
        body = _kv(args.field)
        cfg = _kv(args.config)
        if cfg:
            body['config'] = cfg
        if args.action == 'create':
            if 'name' not in body:
                _die('create requires --field name=...')
            _out(*_request('POST', '/api/v1/agents', body=body))
        else:
            _out(*_request('PATCH', f'/api/v1/agents/{args.id}', body=body))
    elif args.action in ('enable', 'disable'):
        status = 'active' if args.action == 'enable' else 'paused'
        _out(*_request('PATCH', f'/api/v1/agents/{args.id}', body={'status': status}))
    elif args.action == 'delete':
        _out(*_request('DELETE', f'/api/v1/agents/{args.id}'))


def cmd_settings(args):
    if args.action == 'get':
        _out(*_request('GET', '/api/v1/settings'))
    elif args.action == 'set':
        _out(*_request('PATCH', '/api/v1/settings', body=_kv(args.field)))


# ── Parser ────────────────────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(prog='aios', description='AIOS client builder CLI')
    sub = p.add_subparsers(dest='cmd', required=True)

    lp = sub.add_parser('login', help='store your API token')
    lp.add_argument('--url', help=f'API base URL (default {DEFAULT_URL})')
    lp.add_argument('--token', help='token (otherwise prompted, hidden)')
    lp.set_defaults(func=cmd_login)

    sub.add_parser('logout', help='remove stored token').set_defaults(func=cmd_logout)
    sub.add_parser('whoami', help='show token identity + scopes').set_defaults(func=cmd_whoami)

    ip = sub.add_parser('integrations', help='manage platform integrations')
    isub = ip.add_subparsers(dest='action', required=True)
    il = isub.add_parser('list'); il.add_argument('--industry')
    ic = isub.add_parser('connect'); ic.add_argument('platform'); ic.add_argument('--field', action='append')
    it = isub.add_parser('test'); it.add_argument('platform')
    idd = isub.add_parser('disconnect'); idd.add_argument('platform')
    ip.set_defaults(func=cmd_integrations)

    dp = sub.add_parser('docs', help='documents')
    dsub = dp.add_subparsers(dest='action', required=True)
    dsub.add_parser('list')
    du = dsub.add_parser('upload'); du.add_argument('path')
    dp.set_defaults(func=cmd_docs)

    mp = sub.add_parser('domains', help='custom domains')
    msub = mp.add_subparsers(dest='action', required=True)
    msub.add_parser('list')
    ma = msub.add_parser('add'); ma.add_argument('domain')
    mv = msub.add_parser('verify'); mv.add_argument('domain_id')
    mp.set_defaults(func=cmd_domains)

    up = sub.add_parser('users', help="manage the client's staff users")
    usub = up.add_subparsers(dest='action', required=True)
    usub.add_parser('list')
    ua = usub.add_parser('add'); ua.add_argument('email')
    ua.add_argument('--name'); ua.add_argument('--role', default='member', choices=['member', 'admin'])
    up.set_defaults(func=cmd_users)

    ap = sub.add_parser('agents', help='build & manage per-client agents')
    asub = ap.add_subparsers(dest='action', required=True)
    asub.add_parser('list')
    ag = asub.add_parser('get'); ag.add_argument('id')
    ac = asub.add_parser('create')
    ac.add_argument('--field', action='append', help='top-level key=value (name, agent_type, status, description)')
    ac.add_argument('--config', action='append', help='config key=value (instructions, schedule, model)')
    auu = asub.add_parser('update'); auu.add_argument('id')
    auu.add_argument('--field', action='append'); auu.add_argument('--config', action='append')
    ae = asub.add_parser('enable'); ae.add_argument('id')
    ad = asub.add_parser('disable'); ad.add_argument('id')
    adel = asub.add_parser('delete'); adel.add_argument('id')
    ap.set_defaults(func=cmd_agents)

    sp = sub.add_parser('settings', help='tenant settings')
    ssub = sp.add_subparsers(dest='action', required=True)
    ssub.add_parser('get')
    ss = ssub.add_parser('set'); ss.add_argument('--field', action='append', required=True)
    sp.set_defaults(func=cmd_settings)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
