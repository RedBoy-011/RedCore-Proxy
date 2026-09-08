#!/usr/bin/env bash
set -euo pipefail
REPO='https://raw.githubusercontent.com/RedBoy-011/RedCore-Proxy/main'
APP=redcore-proxy
[ "${EUID:-$(id -u)}" -eq 0 ] || { echo 'Run as root.'; exit 1; }

install_packages() {
  # Do not run apt update merely for the sake of it.  A server can have an
  # unrelated, broken third-party repository (for example an old Docker repo)
  # while every dependency required by RedCore is already installed.
  local missing=()
  command -v python3 >/dev/null 2>&1 || missing+=(python3)
  command -v curl >/dev/null 2>&1 || missing+=(curl)
  command -v jq >/dev/null 2>&1 || missing+=(jq)
  command -v unzip >/dev/null 2>&1 || missing+=(unzip)
  [ -e /etc/ssl/certs/ca-certificates.crt ] || missing+=(ca-certificates)
  [ "${#missing[@]}" -eq 0 ] && return
  if command -v apt-get >/dev/null; then
    if ! apt-get update; then
      echo 'apt update به‌دلیل یک repository خارجی ناموفق است. ابتدا آن repository را اصلاح یا موقتاً غیرفعال کنید.' >&2
      exit 1
    fi
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
  elif command -v dnf >/dev/null; then
    dnf install -y "${missing[@]}"
  else
    echo 'Ubuntu/Debian یا Fedora/RHEL پشتیبانی می‌شود.'; exit 1
  fi
}
install_xray() {
  command -v xray >/dev/null 2>&1 && return
  case "$(uname -m)" in
    x86_64|amd64) asset='Xray-linux-64.zip';;
    aarch64|arm64) asset='Xray-linux-arm64-v8a.zip';;
    *) echo "معماری پشتیبانی‌نشده: $(uname -m)"; exit 1;;
  esac
  url="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq -r --arg asset "$asset" '.assets[] | select(.name == $asset) | .browser_download_url' | head -n1)"
  [ -n "$url" ] && [ "$url" != null ] || { echo 'دریافت نسخه Xray ناموفق بود.'; exit 1; }
  work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
  curl -fL "$url" -o "$work/xray.zip"
  unzip -q "$work/xray.zip" -d "$work/out"
  install -m 0755 "$work/out/xray" /usr/local/bin/xray
}

echo 'Installing RedCore-Proxy…'
install_packages
install_xray
install -d -m 0755 /opt/redcore-proxy /etc/redcore-proxy /var/log/redcore-proxy
touch /etc/redcore-proxy/subs.txt
chmod 600 /etc/redcore-proxy/subs.txt
for file in redcore_proxy.py redcore-proxy; do
  curl -fL "$REPO/$file" -o "/opt/redcore-proxy/$file"
done
chmod 755 /opt/redcore-proxy/redcore_proxy.py /opt/redcore-proxy/redcore-proxy
ln -sf /opt/redcore-proxy/redcore-proxy /usr/local/bin/redcore-proxy

# Stop old project services only; no user subscription or unrelated service is removed.
systemctl disable --now titan-mihomo.service titan-refresh.timer titan-refresh.service titan-xray.service 2>/dev/null || true
cat >/etc/systemd/system/redcore-proxy-xray.service <<'EOF'
[Unit]
Description=RedCore-Proxy Xray local SOCKS outputs
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/local/bin/xray run -c /etc/redcore-proxy/config.json
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/redcore-proxy-refresh.service <<'EOF'
[Unit]
Description=RedCore-Proxy subscription update and real proxy tests
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/redcore-proxy/redcore_proxy.py refresh --quiet
EOF
cat >/etc/systemd/system/redcore-proxy-refresh.timer <<'EOF'
[Unit]
Description=Run RedCore-Proxy ping test every minute
[Timer]
OnBootSec=90s
OnUnitActiveSec=1min
Persistent=true
Unit=redcore-proxy-refresh.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now redcore-proxy-refresh.timer
echo 'نصب کامل شد. اجرا کنید: redcore-proxy'
