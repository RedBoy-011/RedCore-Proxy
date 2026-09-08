#!/usr/bin/env bash
set -Eeuo pipefail

RAW_BASE="https://raw.githubusercontent.com/RedBoy-011/RedCore-Proxy/main"
SOURCE_DIR="$(mktemp -d)"
trap 'rm -rf "$SOURCE_DIR"' EXIT

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'با root یا sudo اجرا کنید.' >&2; exit 1; }

echo 'Downloading RedCore-Proxy files…'
for file in redcore_proxy.py titan; do
  curl -fL --retry 3 --connect-timeout 15 "$RAW_BASE/$file" -o "$SOURCE_DIR/$file"
done

if command -v apt-get >/dev/null 2>&1; then
  if ! apt-get update; then
    echo 'هشدار: یک مخزن خارجی APT خطا دارد؛ نصب با فهرست بسته‌های موجود ادامه می‌یابد.' >&2
  fi
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl jq netcat-openbsd ca-certificates unzip
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y python3 curl jq nmap-ncat ca-certificates unzip
else
  echo 'مدیر بسته پشتیبانی‌نشده است. python3 curl jq netcat unzip را دستی نصب کنید.' >&2
  exit 1
fi

if ! command -v xray >/dev/null 2>&1; then
  installer="$(mktemp)"
  curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh -o "$installer"
  bash "$installer" install
  rm -f "$installer"
fi

install -d -m 0755 /opt/redcore-proxy /etc/titan /var/log/titan
install -m 0755 "$SOURCE_DIR/redcore_proxy.py" /opt/redcore-proxy/redcore_proxy.py
install -m 0755 "$SOURCE_DIR/titan" /usr/local/bin/titan
touch /etc/titan/subs.txt
chmod 600 /etc/titan/subs.txt

cat >/etc/systemd/system/titan-xray.service <<'EOF'
[Unit]
Description=RedCore-Proxy local SOCKS Xray
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/xray run -config /etc/titan/xray.json
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/titan-refresh.service <<'EOF'
[Unit]
Description=Refresh RedCore-Proxy subscriptions
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/redcore-proxy/redcore_proxy.py refresh --quiet
EOF

cat >/etc/systemd/system/titan-refresh.timer <<'EOF'
[Unit]
Description=Refresh RedCore-Proxy every 30 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now titan-refresh.timer
echo 'نصب کامل شد. اجرا کنید: titan'
