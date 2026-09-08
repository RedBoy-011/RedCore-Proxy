#!/usr/bin/env python3
"""RedCore-Proxy Mihomo controller: provider loading, real delay tests and SOCKS outputs."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import logging
import re
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
SUBS, CONFIG, SANAEI, STATUS = ETC/'subs.txt', ETC/'mihomo.yaml', ETC/'sanaei.json', ETC/'status.json'
PROVIDERS, LOG = ETC/'providers', Path('/var/log/titan/refresh.log')
API = 'http://127.0.0.1:19090'
PORT_BASE, MAX_NODES = 10801, 8
TEST_URL, TIMEOUT = 'https://www.gstatic.com/generate_204', 12


@dataclass(frozen=True)
class Subscription:
    name: str
    url: str
    provider: str


def setup_log() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.FileHandler(LOG), logging.StreamHandler()])


def yaml_quote(value: str) -> str:
    """JSON strings are valid YAML strings and safely preserve Persian and URL characters."""
    return json.dumps(str(value), ensure_ascii=False)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as out:
        out.write(content)
        temp = Path(out.name)
    temp.replace(path)


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def subscriptions() -> list[Subscription]:
    ETC.mkdir(parents=True, exist_ok=True)
    PROVIDERS.mkdir(parents=True, exist_ok=True)
    SUBS.touch(mode=0o600, exist_ok=True)
    result: list[Subscription] = []
    for index, line in enumerate(SUBS.read_text(encoding='utf-8').splitlines(), 1):
        raw = line.strip()
        if not raw or raw.startswith('#'):
            continue
        if '|' in raw:
            name, url = (part.strip() for part in raw.split('|', 1))
        else:
            name, url = f'ساب {index}', raw
        if not url.startswith(('https://', 'http://')):
            logging.warning('لینک نامعتبر: %s', raw)
            continue
        result.append(Subscription(name or f'ساب {index}', url, f'titan-provider-{index}'))
    return result


def download_provider_file(sub: Subscription) -> tuple[bool, str]:
    """Fetch subscription ourselves so URL-safe Base64 is normalized before Mihomo reads it."""
    try:
        request = urllib.request.Request(sub.url, headers={'User-Agent': 'RedCore-Proxy/4.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read().decode('utf-8', errors='replace').strip()
        compact = re.sub(r'\s+', '', content)
        if '://' not in compact:
            try:
                normalized = compact.replace('-', '+').replace('_', '/')
                decoded = base64.b64decode(normalized + '=' * (-len(normalized) % 4)).decode('utf-8')
                if '://' in decoded or 'proxies:' in decoded:
                    content = decoded
            except (ValueError, UnicodeDecodeError):
                pass
        target = PROVIDERS / f'{sub.provider}.txt'
        write_text(target, content.strip() + '\n')
        node_count = len(re.findall(r'(?im)^(?:vless|trojan|vmess|ss|hysteria2|hy2|tuic)://', content))
        return True, f'{node_count} URI detected'
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return False, str(error)


def prepare_provider_files(subs: list[Subscription]) -> dict[str, str]:
    results: dict[str, str] = {}
    for sub in subs:
        ok, message = download_provider_file(sub)
        results[sub.name] = message if ok else f'ERROR: {message}'
        if not ok:
            logging.warning('%s: %s', sub.name, message)
    return results


def make_config(subs: list[Subscription], selected: list[str] | None = None) -> str:
    """Build one Mihomo config. selected=None is test mode; selected list creates listeners."""
    lines = [
        'allow-lan: false',
        'mode: rule',
        'log-level: warning',
        'external-controller: 127.0.0.1:19090',
        'external-ui: ""',
        'ipv6: true',
        'profile:',
        '  store-selected: false',
        '  store-fake-ip: false',
        'proxy-providers:',
    ]
    for sub in subs:
        prefix = f'{sub.provider}::'
        lines += [
            f'  {sub.provider}:',
            '    type: file',
            f'    path: {yaml_quote(str(PROVIDERS / (sub.provider + ".txt")))}',
            '    health-check:',
            '      enable: true',
            f'      url: {yaml_quote(TEST_URL)}',
            '      interval: 600',
            '      timeout: 12000',
            '      lazy: false',
            '    override:',
            f'      additional-prefix: {yaml_quote(prefix)}',
        ]
    lines += ['proxy-groups:', '  - name: TITAN_ALL', '    type: select', '    use:']
    lines += [f'      - {sub.provider}' for sub in subs]

    if selected:
        for index, proxy in enumerate(selected, 1):
            lines += [
                f'  - name: TITAN_PIN_{index}',
                '    type: select',
                '    proxies:',
                f'      - {yaml_quote(proxy)}',
            ]
    lines += ['listeners:' if selected else 'listeners: []']
    if selected:
        for index, _proxy in enumerate(selected, 1):
            lines += [
                f'  - name: titan-socks-{index}',
                '    type: socks',
                '    listen: 127.0.0.1',
                f'    port: {PORT_BASE + index - 1}',
                '    udp: true',
                '    users: []',
            ]
    lines += ['rules:']
    if selected:
        lines += [f'  - IN-NAME,titan-socks-{index},TITAN_PIN_{index}' for index in range(1, len(selected) + 1)]
    lines += ['  - MATCH,TITAN_ALL']
    return '\n'.join(lines) + '\n'


def api(path: str, timeout: int = 8) -> dict[str, Any]:
    request = urllib.request.Request(API + path, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def restart_mihomo(subs: list[Subscription], selected: list[str] | None = None) -> None:
    write_text(CONFIG, make_config(subs, selected))
    check = subprocess.run(['/usr/local/bin/mihomo', '-d', str(ETC), '-f', str(CONFIG), '-t'], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError(check.stderr.strip() or check.stdout.strip() or 'کانفیگ Mihomo نامعتبر است')
    subprocess.run(['systemctl', 'restart', 'titan-mihomo.service'], check=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            api('/version', timeout=2)
            return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.5)
    raise RuntimeError('API محلی Mihomo در دسترس نشد')


def provider_members(subs: list[Subscription]) -> list[str]:
    """Read actual provider proxies, never group placeholders such as COMPATIBLE."""
    deadline = time.monotonic() + 45
    last: list[str] = []
    while time.monotonic() < deadline:
        try:
            data = api('/providers/proxies')
            providers = data.get('providers', data)
            values: list[str] = []
            for sub in subs:
                entry = providers.get(sub.provider, {}) if isinstance(providers, dict) else {}
                proxies = entry.get('proxies', []) if isinstance(entry, dict) else []
                for proxy in proxies:
                    name = proxy.get('name') if isinstance(proxy, dict) else proxy
                    if isinstance(name, str) and name not in {'DIRECT', 'REJECT', 'REJECT-DROP', 'COMPATIBLE'}:
                        values.append(name)
            last = values
            if last:
                return last
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(1)
    return last


def provider_delays(subs: list[Subscription]) -> dict[str, int]:
    """Provider proxies are not in /proxies; use their dedicated delay endpoint."""
    all_names = provider_members(subs)
    tasks: list[tuple[str, str]] = []
    for name in all_names:
        for sub in subs:
            if name.startswith(sub.provider + '::'):
                tasks.append((sub.provider, name))
                break

    def test_one(task: tuple[str, str]) -> tuple[str, int | None]:
        provider, proxy = task
        path = '/providers/proxies/' + urllib.parse.quote(provider, safe='') + '/' + urllib.parse.quote(proxy, safe='') + '/healthcheck?'
        path += urllib.parse.urlencode({'timeout': TIMEOUT * 1000, 'url': TEST_URL, 'expected': 204})
        try:
            data = api(path, timeout=TIMEOUT + 5)
            delay_value = data.get('delay')
            return proxy, delay_value if isinstance(delay_value, int) and delay_value > 0 else None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            logging.info('health-check %s failed: %s', proxy, error)
            return proxy, None

    delays: dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(20, max(1, len(tasks)))) as pool:
        for name, value in pool.map(test_one, tasks):
            if value is not None:
                delays[name] = value
    return delays


def recv_exact(sock: socket.socket, count: int) -> bytes:
    data = b''
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise OSError('اتصال بسته شد')
        data += part
    return data


def socks_http_test(port: int) -> tuple[bool, float | None, str]:
    """Tests the final listener, not only Mihomo's API: SOCKS5 + TLS + HTTP."""
    started = time.perf_counter()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=TIMEOUT) as sock:
            sock.settimeout(TIMEOUT)
            sock.sendall(b'\x05\x01\x00')
            if recv_exact(sock, 2) != b'\x05\x00':
                return False, None, 'SOCKS handshake ناموفق'
            host = b'example.com'
            sock.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + (443).to_bytes(2, 'big'))
            reply = recv_exact(sock, 4)
            if reply[1] != 0:
                return False, None, f'کد SOCKS {reply[1]}'
            if reply[3] == 1:
                recv_exact(sock, 6)
            elif reply[3] == 4:
                recv_exact(sock, 18)
            elif reply[3] == 3:
                recv_exact(sock, recv_exact(sock, 1)[0] + 2)
            else:
                return False, None, 'ATYP نامعتبر'
            context = ssl.create_default_context()
            with context.wrap_socket(sock, server_hostname='example.com') as tls:
                tls.sendall(b'GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n')
                if not tls.recv(16).startswith(b'HTTP/'):
                    return False, None, 'HTTP معتبر نیست'
        return True, round((time.perf_counter() - started) * 1000, 1), 'SOCKS/TLS/HTTP موفق'
    except (OSError, ssl.SSLError) as error:
        return False, None, str(error)


def sanaei_json(count: int) -> list[dict[str, Any]]:
    return [{'tag': f'Socks_{index}_titan', 'protocol': 'socks', 'settings': {'servers': [{'address': '127.0.0.1', 'port': PORT_BASE + index - 1, 'users': []}]}} for index in range(1, count + 1)]


def source_of(proxy: str, subs: list[Subscription]) -> str:
    for sub in subs:
        if proxy.startswith(sub.provider + '::'):
            return sub.name
    return 'نامشخص'


def test_subs() -> int:
    setup_log()
    subs = subscriptions()
    if not subs:
        print('هیچ سابی ثبت نشده است.')
        return 1
    fetched = prepare_provider_files(subs)
    restart_mihomo(subs)
    names = provider_members(subs)
    print('--- نتیجهٔ بارگذاری Mihomo ---')
    for sub in subs:
        count = sum(item.startswith(sub.provider + '::') for item in names)
        print(f"{'✓' if count else '✗'} {sub.name}: {count} نود توسط Mihomo بارگذاری شد | دانلود: {fetched[sub.name]}")
    print(f'جمع کل: {len(names)} نود')
    return 0 if names else 1


def refresh(quiet: bool = False) -> int:
    setup_log()
    subs = subscriptions()
    if not subs:
        if not quiet:
            print('هیچ سابی ثبت نشده است.')
        return 0
    fetched = prepare_provider_files(subs)
    if not quiet:
        print('--- مرحله ۱: دریافت Subscriptionها با Mihomo ---')
    restart_mihomo(subs)
    names = provider_members(subs)
    if not names:
        write_json(SANAEI, [])
        write_json(STATUS, {'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'loaded': 0, 'selected': [], 'error': 'هیچ نودی از providerها بارگذاری نشد'})
        subprocess.run(['systemctl', 'stop', 'titan-mihomo.service'], check=False)
        if not quiet:
            print('هیچ نودی توسط Mihomo بارگذاری نشد.')
        return 0
    if not quiet:
        print(f'--- مرحله ۲: health-check واقعی Mihomo برای {len(names)} نود ---')
    delays = provider_delays(subs)
    tested: list[tuple[str, int]] = [(name, delays[name]) for name in names if name in delays]
    if not quiet:
        for name in names:
            if name in delays:
                print(f'✓ {name} | {source_of(name, subs)} | {delays[name]}ms')
            else:
                print(f'✗ {name} | {source_of(name, subs)} | health-check ناموفق')
    tested.sort(key=lambda item: item[1])
    candidates = [name for name, _ in tested[:MAX_NODES]]
    if not quiet:
        print(f'--- مرحله ۳: ساخت و تست SOCKSهای نهایی ({len(candidates)} نود) ---')
    if candidates:
        restart_mihomo(subs, candidates)
    else:
        write_json(SANAEI, [])
        subprocess.run(['systemctl', 'stop', 'titan-mihomo.service'], check=False)
    results: list[dict[str, Any]] = []
    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as pool:
            checks = list(pool.map(socks_http_test, [PORT_BASE + i for i in range(len(candidates))]))
        for index, (name, delay_ms) in enumerate(tested[:MAX_NODES], 1):
            ok, real_ms, message = checks[index - 1]
            if ok and real_ms is not None:
                results.append({'index': len(results) + 1, 'port': PORT_BASE + len(results), 'proxy': name, 'source': source_of(name, subs), 'mihomo_delay_ms': delay_ms, 'socks_latency_ms': real_ms, 'message': message})
            if not quiet:
                print(f"{'✓' if ok else '✗'} پورت {PORT_BASE + index - 1} | {name} | {message}")
    # If a final listener failed, regenerate config with only truly healthy proxies.
    final_names = [item['proxy'] for item in results]
    if final_names:
        restart_mihomo(subs, final_names)
    else:
        subprocess.run(['systemctl', 'stop', 'titan-mihomo.service'], check=False)
    write_json(SANAEI, sanaei_json(len(final_names)))
    report = {'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'loaded': len(names), 'api_healthy': len(tested), 'selected': results, 'subscriptions': [{'name': s.name, 'url': s.url, 'download': fetched[s.name], 'loaded': sum(n.startswith(s.provider + "::") for n in names)} for s in subs]}
    write_json(STATUS, report)
    if not quiet:
        print('--- نتیجهٔ نهایی ---')
        if results:
            for item in results:
                print(f"{item['index']}. 127.0.0.1:{item['port']} | {item['socks_latency_ms']}ms | {item['proxy']} | منبع: {item['source']}")
            print(f'JSON ثنایی: {SANAEI}')
        else:
            print('هیچ نودی تست واقعی SOCKS را پاس نکرد.')
    return 0


def status() -> int:
    if not STATUS.exists():
        print('هنوز تستی اجرا نشده است.')
        return 1
    data = json.loads(STATUS.read_text(encoding='utf-8'))
    print(f"آخرین اجرا: {data.get('updated_at', '-')} | بارگذاری‌شده: {data.get('loaded', 0)} | API سالم: {data.get('api_healthy', 0)}")
    for item in data.get('selected', []):
        print(f"{item['index']}. پورت {item['port']} | API: {item['mihomo_delay_ms']}ms | SOCKS: {item['socks_latency_ms']}ms | {item['proxy']} | منبع: {item['source']}")
    if not data.get('selected'):
        print('هیچ SOCKS سالمی انتخاب نشده است.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
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
            return status()
        if args.command == 'json':
            print(SANAEI.read_text(encoding='utf-8') if SANAEI.exists() else 'هنوز JSON ساخته نشده است.')
            return 0
        ok, latency, message = socks_http_test(args.port or PORT_BASE)
        print(f"پورت {args.port or PORT_BASE}: {'✓ سالم' if ok else '✗ ناموفق'} | {latency if latency is not None else '-'}ms | {message}")
        return 0 if ok else 1
    except Exception as error:
        logging.exception('خطا')
        print(f'خطا: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
