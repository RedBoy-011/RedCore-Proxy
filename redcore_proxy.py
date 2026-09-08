#!/usr/bin/env python3
"""RedCore-Proxy: real end-to-end subscription tester for local SOCKS outputs."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import logging
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ETC = Path('/etc/titan')
SUBS, XRAY, SANAEI, STATUS = ETC/'subs.txt', ETC/'xray.json', ETC/'sanaei.json', ETC/'status.json'
LOG = Path('/var/log/titan/refresh.log')
PORT_BASE, MAX_NODES = 10801, 8
TCP_TIMEOUT, REAL_TIMEOUT = 3.5, 12.0
TEST_HOST, TEST_PORT = 'example.com', 443


@dataclass(frozen=True)
class Subscription:
    name: str
    url: str


@dataclass(frozen=True)
class Node:
    protocol: str
    address: str
    port: int
    user: dict[str, Any]
    stream: dict[str, Any]
    name: str
    source: str

    def key(self) -> str:
        return json.dumps([self.protocol, self.address, self.port, self.user, self.stream], sort_keys=True)


def setup_log() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.FileHandler(LOG), logging.StreamHandler()])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as out:
        json.dump(payload, out, ensure_ascii=False, indent=2)
        out.write('\n')
        temp = Path(out.name)
    temp.replace(path)


def subscriptions() -> list[Subscription]:
    ETC.mkdir(parents=True, exist_ok=True)
    SUBS.touch(mode=0o600, exist_ok=True)
    result: list[Subscription] = []
    for line_no, raw in enumerate(SUBS.read_text(encoding='utf-8').splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        if '|' in raw:
            name, url = (part.strip() for part in raw.split('|', 1))
        else:
            url = raw
            name = f'ساب {line_no} ({urllib.parse.urlparse(url).netloc or "بدون‌نام"})'
        if url.startswith(('https://', 'http://')):
            result.append(Subscription(name or f'ساب {line_no}', url))
        else:
            logging.warning('خط نامعتبر ساب: %s', raw)
    return result


def jsdelivr(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip('/').split('/')
    if parsed.netloc == 'raw.githubusercontent.com' and len(parts) >= 4:
        return f'https://cdn.jsdelivr.net/gh/{parts[0]}/{parts[1]}@{parts[2]}/' + '/'.join(parts[3:])
    if parsed.netloc in {'github.com', 'www.github.com'} and len(parts) >= 5 and parts[2] in {'blob', 'raw'}:
        return f'https://cdn.jsdelivr.net/gh/{parts[0]}/{parts[1]}@{parts[3]}/' + '/'.join(parts[4:])
    return url


def fetch(url: str) -> str:
    request = urllib.request.Request(jsdelivr(url), headers={'User-Agent': 'RedCore-Proxy/3.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode('utf-8', errors='replace').strip()


def decode_subscription(text: str) -> str:
    compact = re.sub(r'\s+', '', text)
    if '://' in compact:
        return text
    try:
        decoded = base64.b64decode(compact + '=' * (-len(compact) % 4), validate=True).decode('utf-8')
        return decoded if '://' in decoded else text
    except (ValueError, UnicodeDecodeError):
        return text


def first(query: dict[str, list[str]], key: str, default: str = '') -> str:
    return query.get(key, [default])[0]


def bool_value(value: str) -> bool:
    return value.lower() in {'1', 'true', 'yes', 'on'}


def stream_config(network: str, security: str, query: dict[str, list[str]]) -> dict[str, Any]:
    network = network or 'tcp'
    security = security or 'none'
    output: dict[str, Any] = {'network': network, 'security': security}
    host, path = first(query, 'host'), first(query, 'path', '/')
    if network == 'ws':
        output['wsSettings'] = {'path': path, 'headers': {'Host': host} if host else {}}
    elif network == 'grpc':
        output['grpcSettings'] = {'serviceName': first(query, 'serviceName')}
    elif network == 'httpupgrade':
        output['httpupgradeSettings'] = {'path': path, 'host': host}
    elif network == 'xhttp':
        xhttp: dict[str, Any] = {'path': path, 'host': host}
        mode = first(query, 'mode')
        if mode:
            xhttp['mode'] = mode
        extra = first(query, 'extra')
        if extra:
            try:
                decoded_extra = json.loads(extra)
                if isinstance(decoded_extra, dict):
                    xhttp.update(decoded_extra)
            except json.JSONDecodeError:
                pass
        output['xhttpSettings'] = xhttp
    sni = first(query, 'sni') or host
    fp = first(query, 'fp')
    if security == 'tls':
        tls: dict[str, Any] = {'serverName': sni, 'allowInsecure': bool_value(first(query, 'allowInsecure'))}
        if fp:
            tls['fingerprint'] = fp
        alpn = [x for x in first(query, 'alpn').split(',') if x]
        if alpn:
            tls['alpn'] = alpn
        output['tlsSettings'] = tls
    elif security == 'reality':
        reality: dict[str, Any] = {'serverName': sni, 'publicKey': first(query, 'pbk'), 'shortId': first(query, 'sid')}
        if fp:
            reality['fingerprint'] = fp
        if first(query, 'spx'):
            reality['spiderX'] = first(query, 'spx')
        output['realitySettings'] = reality
    return output


def parse_vless_or_trojan(uri: str, source: str) -> Node | None:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme not in {'vless', 'trojan'} or not parsed.hostname or not parsed.port or not parsed.username:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.scheme == 'vless':
        user: dict[str, Any] = {'id': urllib.parse.unquote(parsed.username), 'encryption': first(query, 'encryption', 'none')}
        if first(query, 'flow'):
            user['flow'] = first(query, 'flow')
        security = first(query, 'security', 'none')
    else:
        user = {'password': urllib.parse.unquote(parsed.username)}
        security = first(query, 'security', 'tls')
    return Node(parsed.scheme, parsed.hostname, parsed.port, user, stream_config(first(query, 'type', 'tcp'), security, query), urllib.parse.unquote(parsed.fragment) or f'{parsed.scheme}-{parsed.hostname}', source)


def parse_vmess(uri: str, source: str) -> Node | None:
    try:
        body = uri.split('://', 1)[1]
        data = json.loads(base64.b64decode(body + '=' * (-len(body) % 4)).decode('utf-8'))
        query = {
            'host': [str(data.get('host', ''))], 'path': [str(data.get('path', '/'))],
            'sni': [str(data.get('sni', data.get('servername', '')))], 'fp': [str(data.get('fp', ''))],
            'pbk': [str(data.get('pbk', ''))], 'sid': [str(data.get('sid', ''))], 'serviceName': [str(data.get('path', ''))],
        }
        user = {'id': str(data['id']), 'alterId': int(data.get('aid', 0)), 'security': str(data.get('scy', 'auto'))}
        return Node('vmess', str(data['add']), int(data['port']), user, stream_config(str(data.get('net', 'tcp')), str(data.get('tls', 'none')), query), str(data.get('ps', 'vmess-node')), source)
    except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def parse_shadowsocks(uri: str, source: str) -> Node | None:
    try:
        parsed = urllib.parse.urlparse(uri)
        fragment = urllib.parse.unquote(parsed.fragment) or 'shadowsocks-node'
        if parsed.hostname and parsed.port and parsed.username:
            credential = urllib.parse.unquote(parsed.username)
        else:
            raw = uri.split('://', 1)[1].split('#', 1)[0].split('?', 1)[0]
            encoded, host_port = raw.rsplit('@', 1)
            credential = base64.b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8')
            host, port = host_port.rsplit(':', 1)
            parsed = urllib.parse.urlparse(f'//{host}:{port}')
        method, password = credential.split(':', 1)
        return Node('shadowsocks', parsed.hostname or '', parsed.port or 0, {'method': method, 'password': password}, {}, fragment, source)
    except (ValueError, UnicodeDecodeError):
        return None


def extract_nodes(text: str, source: str) -> tuple[list[Node], dict[str, int]]:
    decoded = decode_subscription(text)
    links = re.findall(r'(?:[A-Za-z0-9+.-]+)://[^\s]+', decoded)
    nodes: dict[str, Node] = {}
    unsupported: dict[str, int] = {}
    for uri in links:
        scheme = uri.split('://', 1)[0].lower()
        node: Node | None
        if scheme in {'vless', 'trojan'}:
            node = parse_vless_or_trojan(uri, source)
        elif scheme == 'vmess':
            node = parse_vmess(uri, source)
        elif scheme == 'ss':
            node = parse_shadowsocks(uri, source)
        else:
            unsupported[scheme] = unsupported.get(scheme, 0) + 1
            continue
        if node:
            nodes.setdefault(node.key(), node)
    return list(nodes.values()), unsupported


def load_subscription(sub: Subscription) -> tuple[Subscription, list[Node], dict[str, int], str | None]:
    try:
        nodes, unsupported = extract_nodes(fetch(sub.url), sub.name)
        return sub, nodes, unsupported, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return sub, [], {}, str(error)


def tcp_probe(node: Node) -> tuple[Node, float | None]:
    started = time.perf_counter()
    try:
        with socket.create_connection((node.address, node.port), timeout=TCP_TIMEOUT):
            return node, round((time.perf_counter() - started) * 1000, 1)
    except OSError:
        return node, None


def outbound(node: Node, tag: str) -> dict[str, Any]:
    if node.protocol == 'trojan':
        settings = {'servers': [{'address': node.address, 'port': node.port, 'password': node.user['password']}]}
    elif node.protocol == 'shadowsocks':
        settings = {'servers': [{'address': node.address, 'port': node.port, 'method': node.user['method'], 'password': node.user['password']}]}
    else:
        settings = {'vnext': [{'address': node.address, 'port': node.port, 'users': [node.user]}]}
    result = {'tag': tag, 'protocol': node.protocol, 'settings': settings}
    if node.stream:
        result['streamSettings'] = node.stream
    return result


def xray_config(nodes: list[Node]) -> dict[str, Any]:
    inbounds, outbounds, rules = [], [{'tag': 'direct', 'protocol': 'freedom'}], []
    for index, node in enumerate(nodes, 1):
        inbound_tag, outbound_tag = f'titan-in-{index}', f'titan-out-{index}'
        inbounds.append({'tag': inbound_tag, 'listen': '127.0.0.1', 'port': PORT_BASE + index - 1, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}})
        outbounds.append(outbound(node, outbound_tag))
        rules.append({'type': 'field', 'inboundTag': [inbound_tag], 'outboundTag': outbound_tag})
    return {'log': {'loglevel': 'warning'}, 'inbounds': inbounds, 'outbounds': outbounds, 'routing': {'rules': rules}}


def sanaei_config(count: int) -> list[dict[str, Any]]:
    return [{'tag': f'Socks_{index}_titan', 'protocol': 'socks', 'settings': {'servers': [{'address': '127.0.0.1', 'port': PORT_BASE + index - 1, 'users': []}]}} for index in range(1, count + 1)]


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise OSError('اتصال هنگام دریافت پاسخ بسته شد')
        data += part
    return data


def real_socks_test(port: int) -> tuple[bool, float | None, str]:
    """SOCKS5 handshake + remote TLS handshake + HTTP response: no false positives."""
    started = time.perf_counter()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=REAL_TIMEOUT) as sock:
            sock.settimeout(REAL_TIMEOUT)
            sock.sendall(b'\x05\x01\x00')
            if recv_exact(sock, 2) != b'\x05\x00':
                return False, None, 'SOCKS handshake ناموفق'
            host = TEST_HOST.encode('idna')
            sock.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + TEST_PORT.to_bytes(2, 'big'))
            reply = recv_exact(sock, 4)
            if reply[1] != 0:
                return False, None, f'اتصال SOCKS ناموفق (کد {reply[1]})'
            if reply[3] == 1:
                recv_exact(sock, 6)
            elif reply[3] == 4:
                recv_exact(sock, 18)
            elif reply[3] == 3:
                recv_exact(sock, recv_exact(sock, 1)[0] + 2)
            else:
                return False, None, 'پاسخ SOCKS نامعتبر'
            context = ssl.create_default_context()
            with context.wrap_socket(sock, server_hostname=TEST_HOST) as tls:
                tls.sendall(b'GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n')
                if not tls.recv(16).startswith(b'HTTP/'):
                    return False, None, 'TLS برقرار شد ولی HTTP پاسخ معتبر نداد'
        latency = round((time.perf_counter() - started) * 1000, 1)
        return True, latency, 'TLS و HTTP موفق'
    except (OSError, ssl.SSLError) as error:
        return False, None, str(error)


def start_xray(nodes: list[Node]) -> None:
    binary = shutil.which('xray')
    if not binary:
        raise RuntimeError('Xray پیدا نشد. install.sh را اجرا کنید.')
    write_json(XRAY, xray_config(nodes))
    check = subprocess.run([binary, 'run', '-test', '-config', str(XRAY)], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError(check.stderr.strip() or 'کانفیگ Xray نامعتبر است.')
    subprocess.run(['systemctl', 'restart', 'titan-xray.service'], check=True)
    time.sleep(1)


def test_subs() -> int:
    setup_log()
    subs = subscriptions()
    if not subs:
        print('هیچ سابی ثبت نشده است.')
        return 1
    print('--- تست دریافت و پارس ساب‌ها ---')
    for sub in subs:
        _, nodes, unsupported, error = load_subscription(sub)
        if error:
            print(f'✗ {sub.name}: خطا در دریافت — {error}')
        else:
            extra = f' | پشتیبانی‌نشده: {unsupported}' if unsupported else ''
            print(f'✓ {sub.name}: {len(nodes)} نود پشتیبانی‌شده{extra}')
    return 0


def refresh(quiet: bool = False) -> int:
    setup_log()
    subs = subscriptions()
    if not subs:
        if not quiet:
            print('هیچ سابی ثبت نشده است. ابتدا یک ساب اضافه کنید.')
        return 0
    collected: list[Node] = []
    reports: list[dict[str, Any]] = []
    if not quiet:
        print('--- مرحله ۱: دریافت و پارس ساب‌ها ---')
    for sub in subs:
        _, nodes, unsupported, error = load_subscription(sub)
        reports.append({'name': sub.name, 'url': sub.url, 'parsed_nodes': len(nodes), 'unsupported': unsupported, 'error': error})
        if error:
            logging.warning('%s: %s', sub.name, error)
            if not quiet:
                print(f'✗ {sub.name}: {error}')
        else:
            collected.extend(nodes)
            if not quiet:
                print(f'✓ {sub.name}: {len(nodes)} نود پشتیبانی‌شده')
    unique = list({node.key(): node for node in collected}.values())
    if not quiet:
        print(f'--- مرحله ۲: تست TCP هم‌زمان ({len(unique)} نود) ---')
    tcp_alive: list[tuple[Node, float]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(64, max(1, len(unique)))) as pool:
        for node, latency in pool.map(tcp_probe, unique):
            if latency is not None:
                tcp_alive.append((node, latency))
    tcp_alive.sort(key=lambda item: item[1])
    if not quiet:
        print(f'{len(tcp_alive)} نود TCP پاسخ‌گو هستند. مرحله ۳: تست واقعی SOCKS/TLS/HTTP')
    passed: list[tuple[Node, float, str]] = []
    for start in range(0, len(tcp_alive), MAX_NODES):
        batch = tcp_alive[start:start + MAX_NODES]
        try:
            start_xray([node for node, _ in batch])
        except RuntimeError as error:
            logging.warning('دستهٔ آزمایشی نامعتبر: %s', error)
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
            results = list(pool.map(real_socks_test, [PORT_BASE + index for index in range(len(batch))]))
        for (node, tcp_ms), (ok, real_ms, message) in zip(batch, results):
            if not quiet:
                mark = '✓' if ok else '✗'
                speed = f'{real_ms}ms' if real_ms is not None else '-'
                print(f'{mark} {node.name} | منبع: {node.source} | TCP: {tcp_ms}ms | واقعی: {speed} | {message}')
            if ok and real_ms is not None and len(passed) < MAX_NODES:
                passed.append((node, real_ms, message))
        if len(passed) >= MAX_NODES:
            break
    passed.sort(key=lambda item: item[1])
    final_nodes = [node for node, _, _ in passed]
    write_json(SANAEI, sanaei_config(len(final_nodes)))
    if final_nodes:
        start_xray(final_nodes)
    else:
        write_json(XRAY, xray_config([]))
        subprocess.run(['systemctl', 'stop', 'titan-xray.service'], check=False)
    selected = []
    for index, (node, real_ms, message) in enumerate(passed, 1):
        selected.append({'index': index, 'port': PORT_BASE + index - 1, 'real_latency_ms': real_ms, 'protocol': node.protocol, 'name': node.name, 'address': node.address, 'source': node.source, 'result': message})
    write_json(STATUS, {'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'subscription_count': len(subs), 'unique_nodes': len(unique), 'tcp_alive': len(tcp_alive), 'selected': selected, 'subscriptions': reports})
    if not quiet:
        print('--- نتیجهٔ نهایی ---')
        if selected:
            for item in selected:
                print(f"{item['index']}. پورت {item['port']} | {item['real_latency_ms']}ms | {item['protocol']} | {item['name']} | منبع: {item['source']}")
            print(f'JSON ثنایی: {SANAEI}')
        else:
            print('هیچ نودی تست واقعی را پاس نکرد؛ خروجی ثنایی خالی است.')
    return 0


def show_status() -> int:
    if not STATUS.exists():
        print('هنوز تستی اجرا نشده است.')
        return 1
    data = json.loads(STATUS.read_text(encoding='utf-8'))
    print(f"آخرین اجرا: {data['updated_at']} | یکتا: {data['unique_nodes']} | TCP پاسخ‌گو: {data['tcp_alive']}")
    if not data['selected']:
        print('هیچ SOCKS سالمی انتخاب نشده است.')
    for item in data['selected']:
        print(f"{item['index']}. 127.0.0.1:{item['port']} | {item['real_latency_ms']}ms | {item['protocol']} | {item['name']} | منبع: {item['source']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='RedCore-Proxy')
    parser.add_argument('command', choices=['refresh', 'test-subs', 'status', 'json', 'socks-test'])
    parser.add_argument('port', nargs='?', type=int)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'refresh':
            return refresh(args.quiet)
        if args.command == 'test-subs':
            return test_subs()
        if args.command == 'status':
            return show_status()
        if args.command == 'json':
            print(SANAEI.read_text(encoding='utf-8') if SANAEI.exists() else 'هنوز JSON ساخته نشده است.')
            return 0
        ok, latency, message = real_socks_test(args.port or PORT_BASE)
        print(f"پورت {args.port or PORT_BASE}: {'✓ سالم' if ok else '✗ ناموفق'} | {latency if latency else '-'}ms | {message}")
        return 0 if ok else 1
    except Exception as error:
        logging.exception('خطا')
        print(f'خطا: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
