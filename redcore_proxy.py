#!/usr/bin/env python3
"""RedCore-Proxy: subscription downloader, real Xray SOCKS tester and selector.

The program deliberately uses Xray for protocol transport. Python owns the
workflow: subscription cache, URI parsing, concurrent real tests, ranking and
the final eight localhost SOCKS listeners.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP = 'redcore-proxy'
ROOT = Path('/etc/redcore-proxy')
SUBS = ROOT / 'subs.txt'
NODES = ROOT / 'nodes.json'
STATUS = ROOT / 'status.json'
CONFIG = ROOT / 'config.json'
SANAEI = ROOT / 'sanaei.json'
LOG = Path('/var/log/redcore-proxy/refresh.log')
XRAY = '/usr/local/bin/xray'
PORT_BASE = 10801
MAX_NODES = 8
DOWNLOAD_EVERY = 3600
TEST_TIMEOUT = 12
WORKERS = 8
TEST_HOST = 'www.gstatic.com'
TEST_PATH = '/generate_204'


@dataclass
class Subscription:
    name: str
    url: str


@dataclass
class Node:
    tag: str
    protocol: str
    source: str
    label: str
    outbound: dict[str, Any]


def setup() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    SUBS.touch(exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_subs() -> list[Subscription]:
    result: list[Subscription] = []
    for raw in SUBS.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '|' not in line:
            continue
        name, url = (part.strip() for part in line.split('|', 1))
        if url.startswith(('http://', 'https://')):
            result.append(Subscription(name or f'ساب {len(result) + 1}', normalize_url(url)))
    return result


def normalize_url(url: str) -> str:
    """Turn github blob links into raw links; leave every other provider intact."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() == 'github.com' and '/blob/' in parsed.path:
        return urllib.parse.urlunparse(('https', 'raw.githubusercontent.com', parsed.path.replace('/blob/', '/', 1), '', '', ''))
    return url


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={'User-Agent': 'RedCore-Proxy/2.0', 'Accept': '*/*'})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read()
    return data.decode('utf-8-sig', errors='replace').strip()


def decode_subscription(text: str) -> str:
    """Accept normal URI lists and standard/url-safe Base64 subscription bodies."""
    compact = ''.join(text.split())
    if any(scheme in text.lower() for scheme in ('vless://', 'vmess://', 'trojan://')):
        return text
    try:
        padded = compact.replace('-', '+').replace('_', '/') + '=' * (-len(compact) % 4)
        decoded = base64.b64decode(padded, validate=False).decode('utf-8', errors='replace')
        if any(scheme in decoded.lower() for scheme in ('vless://', 'vmess://', 'trojan://')):
            return decoded
    except (ValueError, UnicodeError):
        pass
    return text


def query_values(uri: str) -> tuple[urllib.parse.SplitResult, dict[str, str], str]:
    parsed = urllib.parse.urlsplit(uri)
    query = {key.lower(): value for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    label = urllib.parse.unquote(parsed.fragment) or parsed.hostname or 'بدون‌نام'
    return parsed, query, label


def stream_settings(query: dict[str, str]) -> dict[str, Any]:
    network = query.get('type', query.get('net', 'tcp')).lower() or 'tcp'
    security = query.get('security', query.get('tls', 'none')).lower()
    result: dict[str, Any] = {'network': network, 'security': security if security in ('tls', 'reality') else 'none'}
    host = query.get('host', '')
    path = query.get('path', '')
    if network == 'ws':
        result['wsSettings'] = {'path': path or '/', 'headers': {'Host': host} if host else {}}
    elif network == 'grpc':
        result['grpcSettings'] = {'serviceName': query.get('servicename', query.get('serviceName', '')), 'multiMode': query.get('mode', '') == 'multi'}
    elif network in ('httpupgrade', 'http-upgrade'):
        result['network'] = 'httpupgrade'
        result['httpupgradeSettings'] = {'path': path or '/', 'host': host}
    elif network == 'xhttp':
        # XHTTP links frequently carry `mode` and a JSON `extra` object.
        # `extra` is not cosmetic: it can contain XPadding/xmux/header values
        # required by the upstream.  Dropping it produces a valid Xray config
        # that nevertheless cannot connect to many modern -x subscriptions.
        xhttp: dict[str, Any] = {'path': path or '/', 'host': host, 'mode': query.get('mode', 'auto') or 'auto'}
        if query.get('extra'):
            try:
                extra = json.loads(query['extra'])
                if isinstance(extra, dict):
                    xhttp['extra'] = extra
            except json.JSONDecodeError:
                pass
        # A few publishers send this single XHTTP value outside `extra`.
        if query.get('x_padding_bytes'):
            xhttp.setdefault('extra', {})['xPaddingBytes'] = query['x_padding_bytes']
        result['xhttpSettings'] = xhttp
    elif network == 'http':
        result['httpSettings'] = {'path': path or '/', 'host': [host] if host else []}
    if result['security'] == 'tls':
        tls: dict[str, Any] = {'serverName': query.get('sni', host), 'allowInsecure': query.get('allowinsecure', '0').lower() in ('1', 'true')}
        if query.get('fp'):
            tls['fingerprint'] = query['fp']
        if query.get('alpn'):
            tls['alpn'] = [item for item in query['alpn'].split(',') if item]
        result['tlsSettings'] = tls
    elif result['security'] == 'reality':
        reality: dict[str, Any] = {'show': False, 'serverName': query.get('sni', host), 'fingerprint': query.get('fp', 'chrome'), 'publicKey': query.get('pbk', ''), 'shortId': query.get('sid', ''), 'spiderX': query.get('spx', '')}
        result['realitySettings'] = reality
    return result


def make_tag(protocol: str, source: str, uri: str) -> str:
    return f'rc-{protocol}-{hashlib.sha1((source + uri).encode()).hexdigest()[:12]}'


def parse_vless(uri: str, source: str) -> Node | None:
    parsed, query, label = query_values(uri)
    if not parsed.hostname or not parsed.username or not parsed.port:
        return None
    user: dict[str, Any] = {'id': urllib.parse.unquote(parsed.username), 'encryption': query.get('encryption', 'none')}
    if query.get('flow'):
        user['flow'] = query['flow']
    outbound = {'tag': make_tag('vless', source, uri), 'protocol': 'vless', 'settings': {'vnext': [{'address': parsed.hostname, 'port': parsed.port, 'users': [user]}]}, 'streamSettings': stream_settings(query)}
    return Node(outbound['tag'], 'vless', source, label, outbound)


def parse_trojan(uri: str, source: str) -> Node | None:
    parsed, query, label = query_values(uri)
    if not parsed.hostname or not parsed.username or not parsed.port:
        return None
    # Trojan normally uses TLS even when the URI omits the explicit parameter.
    query.setdefault('security', 'tls')
    outbound = {'tag': make_tag('trojan', source, uri), 'protocol': 'trojan', 'settings': {'servers': [{'address': parsed.hostname, 'port': parsed.port, 'password': urllib.parse.unquote(parsed.username), 'level': 0}]}, 'streamSettings': stream_settings(query)}
    return Node(outbound['tag'], 'trojan', source, label, outbound)


def parse_vmess(uri: str, source: str) -> Node | None:
    try:
        body = uri.split('://', 1)[1]
        body += '=' * (-len(body) % 4)
        data = json.loads(base64.b64decode(body.replace('-', '+').replace('_', '/')).decode('utf-8'))
        address, port, ident = str(data.get('add', '')).strip(), int(data.get('port', 0)), str(data.get('id', '')).strip()
        if not address or not port or not ident:
            return None
        query = {'net': str(data.get('net', 'tcp')), 'type': str(data.get('net', 'tcp')), 'security': str(data.get('tls', 'none')), 'host': str(data.get('host', '')), 'path': str(data.get('path', '')), 'sni': str(data.get('sni', data.get('host', ''))), 'alpn': str(data.get('alpn', '')), 'fp': str(data.get('fp', ''))}
        user = {'id': ident, 'alterId': int(data.get('aid', 0) or 0), 'security': str(data.get('scy', 'auto') or 'auto')}
        outbound = {'tag': make_tag('vmess', source, uri), 'protocol': 'vmess', 'settings': {'vnext': [{'address': address, 'port': port, 'users': [user]}]}, 'streamSettings': stream_settings(query)}
        label = str(data.get('ps', '')).strip() or address
        return Node(outbound['tag'], 'vmess', source, label, outbound)
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None


def parse_nodes(text: str, source: str) -> list[Node]:
    result: list[Node] = []
    seen: set[str] = set()
    for raw in decode_subscription(text).splitlines():
        uri = raw.strip()
        lower = uri.lower()
        node = parse_vless(uri, source) if lower.startswith('vless://') else parse_trojan(uri, source) if lower.startswith('trojan://') else parse_vmess(uri, source) if lower.startswith('vmess://') else None
        if node and node.tag not in seen:
            result.append(node)
            seen.add(node.tag)
    return result


def download_nodes(force: bool = False) -> tuple[list[Node], list[dict[str, Any]]]:
    subs = read_subs()
    if not subs:
        return [], []
    cache = read_json(NODES, {'downloaded_at': 0, 'nodes': [], 'subscriptions': []})
    age = time.time() - float(cache.get('downloaded_at', 0))
    expected = {(sub.name, sub.url) for sub in subs}
    cached_expected = {(item.get('name'), item.get('url')) for item in cache.get('subscriptions', [])}
    if not force and age < DOWNLOAD_EVERY and expected == cached_expected and cache.get('nodes'):
        return [Node(**item) for item in cache['nodes']], cache.get('subscriptions', [])
    nodes: list[Node] = []
    report: list[dict[str, Any]] = []
    for sub in subs:
        try:
            parsed = parse_nodes(fetch(sub.url), sub.name)
            nodes.extend(parsed)
            report.append({'name': sub.name, 'url': sub.url, 'loaded': len(parsed), 'error': ''})
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            logging.warning('subscription %s failed: %s', sub.name, error)
            report.append({'name': sub.name, 'url': sub.url, 'loaded': 0, 'error': str(error)})
    atomic_json(NODES, {'downloaded_at': time.time(), 'nodes': [asdict(item) for item in nodes], 'subscriptions': report})
    return nodes, report


def config_for(nodes: list[Node], listeners: bool) -> dict[str, Any]:
    config: dict[str, Any] = {'log': {'loglevel': 'warning'}, 'outbounds': [node.outbound for node in nodes] + [{'tag': 'direct', 'protocol': 'freedom', 'settings': {}}]}
    if listeners:
        config['inbounds'] = [{'tag': f'redcore-in-{index}', 'listen': '127.0.0.1', 'port': PORT_BASE + index - 1, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}} for index in range(1, len(nodes) + 1)]
        config['routing'] = {'domainStrategy': 'AsIs', 'rules': [{'type': 'field', 'inboundTag': [f'redcore-in-{index}'], 'outboundTag': node.tag} for index, node in enumerate(nodes, 1)]}
    return config


def wait_port(port: int, seconds: float = 3.0) -> bool:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.3):
                return True
        except OSError:
            time.sleep(.08)
    return False


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def socks_probe(port: int) -> tuple[bool, int | None, str]:
    started = time.monotonic()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=TEST_TIMEOUT) as sock:
            sock.settimeout(TEST_TIMEOUT)
            sock.sendall(b'\x05\x01\x00')
            if sock.recv(2) != b'\x05\x00':
                return False, None, 'SOCKS authentication failed'
            host = TEST_HOST.encode('idna')
            sock.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + (443).to_bytes(2, 'big'))
            header = sock.recv(4)
            if len(header) != 4 or header[1] != 0:
                return False, None, f'SOCKS connect error {header[1] if len(header) > 1 else "?"}'
            size = 4 if header[3] == 1 else 16 if header[3] == 4 else sock.recv(1)[0] if header[3] == 3 else 0
            if size:
                remaining = size + 2
                while remaining:
                    chunk = sock.recv(remaining)
                    remaining -= len(chunk)
            context = ssl.create_default_context()
            with context.wrap_socket(sock, server_hostname=TEST_HOST) as tls:
                tls.sendall(f'GET {TEST_PATH} HTTP/1.1\r\nHost: {TEST_HOST}\r\nConnection: close\r\n\r\n'.encode())
                first = tls.recv(64)
        elapsed = int((time.monotonic() - started) * 1000)
        if b' 204 ' in first or b' 200 ' in first or b' 301 ' in first or b' 302 ' in first:
            return True, elapsed, f'HTTPS OK ({elapsed}ms)'
        return False, None, first[:40].decode('latin1', errors='replace')
    except (OSError, ssl.SSLError, ValueError) as error:
        return False, None, str(error)


def test_one(node: Node) -> tuple[Node, bool, int | None, str]:
    if not Path(XRAY).exists():
        return node, False, None, 'Xray Core نصب نیست'
    port = free_port()
    with tempfile.TemporaryDirectory(prefix='redcore-xray-') as directory:
        cfg = Path(directory) / 'config.json'
        cfg.write_text(json.dumps({'log': {'loglevel': 'none'}, 'inbounds': [{'listen': '127.0.0.1', 'port': port, 'protocol': 'socks', 'settings': {'auth': 'noauth'}}], 'outbounds': [node.outbound]}, ensure_ascii=False), encoding='utf-8')
        process = subprocess.Popen([XRAY, 'run', '-c', str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if not wait_port(port):
                return node, False, None, 'Xray test listener باز نشد'
            ok, latency, message = socks_probe(port)
            return node, ok, latency, message
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


def sanaei_json(count: int) -> list[dict[str, Any]]:
    return [{'tag': f'Socks_{index}_redcore', 'protocol': 'socks', 'settings': {'servers': [{'address': '127.0.0.1', 'port': PORT_BASE + index - 1, 'users': []}]}} for index in range(1, count + 1)]


def apply_final(nodes: list[Node]) -> None:
    atomic_json(CONFIG, config_for(nodes, listeners=True))
    check = subprocess.run([XRAY, 'run', '-test', '-c', str(CONFIG)], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError('کانفیگ Xray نامعتبر است: ' + (check.stderr or check.stdout)[-800:])
    if nodes:
        subprocess.run(['systemctl', 'restart', 'redcore-proxy-xray.service'], check=True)
    else:
        subprocess.run(['systemctl', 'stop', 'redcore-proxy-xray.service'], check=False)


def refresh(quiet: bool = False) -> int:
    setup()
    nodes, subs = download_nodes()
    if not nodes:
        apply_final([])
        atomic_json(SANAEI, [])
        atomic_json(STATUS, {'updated_at': time.strftime('%F %T'), 'loaded': 0, 'tested': 0, 'selected': [], 'subscriptions': subs, 'error': 'هیچ نودی بارگذاری نشد'})
        print('هیچ نودی بارگذاری نشد.')
        return 1
    if not quiet:
        print(f'بارگذاری‌شده: {len(nodes)} نود | تست هم‌زمان: {WORKERS} نود')
    outcomes: list[tuple[Node, bool, int | None, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for index, outcome in enumerate(pool.map(test_one, nodes), 1):
            outcomes.append(outcome)
            node, ok, latency, message = outcome
            logging.info('test %s | %s | %s', node.tag, 'ok ' + str(latency) if ok else 'failed', message)
            if not quiet:
                print(f"{'✓' if ok else '✗'} {index}/{len(nodes)} | {node.protocol} | {node.label} | {node.source} | {latency if latency else '-'}ms | {message}")
    healthy = sorted((item for item in outcomes if item[1] and item[2] is not None), key=lambda item: int(item[2]))[:MAX_NODES]
    selected = [item[0] for item in healthy]
    apply_final(selected)
    report_selected = [{'index': index, 'port': PORT_BASE + index - 1, 'tag': node.tag, 'protocol': node.protocol, 'label': node.label, 'source': node.source, 'ping_ms': latency} for index, (node, _ok, latency, _message) in enumerate(healthy, 1)]
    atomic_json(SANAEI, sanaei_json(len(selected)))
    atomic_json(STATUS, {'updated_at': time.strftime('%F %T'), 'loaded': len(nodes), 'tested': len(outcomes), 'healthy': len(healthy), 'selected': report_selected, 'subscriptions': subs})
    if not quiet:
        print(f'نتیجه: {len(healthy)} نود سالم؛ خروجی JSON: {SANAEI}')
    return 0


def test_subs() -> int:
    setup()
    nodes, report = download_nodes(force=True)
    for item in report:
        state = f"{item['loaded']} نود" if not item['error'] else 'خطا: ' + item['error']
        print(f"{'✓' if not item['error'] else '✗'} {item['name']} | {state}")
    print(f'جمع: {len(nodes)} نود قابل‌پارس')
    return 0 if nodes else 1


def status() -> int:
    data = read_json(STATUS, {})
    if not data:
        print('هنوز تستی اجرا نشده است.')
        return 1
    print(f"آخرین تست: {data.get('updated_at', '-')} | بارگذاری: {data.get('loaded', 0)} | تست‌شده: {data.get('tested', 0)} | سالم: {data.get('healthy', 0)}")
    for item in data.get('selected', []):
        print(f"{item['index']}. 127.0.0.1:{item['port']} | {item['ping_ms']}ms | {item['protocol']} | {item['label']} | منبع: {item['source']}")
    return 0


def socks_test(port: int) -> int:
    ok, latency, message = socks_probe(port)
    print(f"{'✓' if ok else '✗'} 127.0.0.1:{port} | {latency if latency else '-'}ms | {message}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog=APP)
    parser.add_argument('command', choices=['refresh', 'test-subs', 'status', 'json', 'socks-test'])
    parser.add_argument('port', nargs='?', type=int)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'refresh': return refresh(args.quiet)
        if args.command == 'test-subs': return test_subs()
        if args.command == 'status': return status()
        if args.command == 'json': print(SANAEI.read_text(encoding='utf-8') if SANAEI.exists() else '[]'); return 0
        if args.command == 'socks-test': return socks_test(args.port or PORT_BASE)
    except KeyboardInterrupt:
        print('\nتست توسط کاربر متوقف شد.')
        return 130
    except Exception as error:
        logging.exception('fatal error')
        print('خطا: ' + str(error), file=sys.stderr)
        return 1
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
