#!/usr/bin/env bash
set -Eeuo pipefail

RAW_BASE='https://raw.githubusercontent.com/RedBoy-011/RedCore-Proxy/main'
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'با root یا sudo اجرا کنید.' >&2; exit 1; }

echo 'Downloading RedCore-Proxy files…'
for file in redcore_proxy.py titan; do
  curl -fL --retry 3 --connect-timeout 15 "$RAW_BASE/$file" -o "$WORK_DIR/$file"
done

if command -v apt-get >/dev/null 2>&1; then
  apt-get update || echo 'هشدار: یک مخزن خارجی APT خطا دارد؛ ادامه با فهرست بسته‌های موجود.' >&2
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl jq ca-certificates gzip
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y python3 curl jq ca-certificates gzip
else
  echo 'مدیر بسته پشتیبانی‌نشده است.' >&2; exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ASSET_RE='mihomo-linux-amd64.*\.gz$' ;;
  aarch64|arm64) ASSET_RE='mihomo-linux-arm64.*\.gz$' ;;
  *) echo "معماری پشتیبانی‌نشده: $ARCH" >&2; exit 1 ;;
esac

if ! command -v mihomo >/dev/null 2>&1; then
  echo 'Installing Mihomo…'
  RELEASE_URL="$(curl -fsSL https://api.github.com/repos/MetaCubeX/mihomo/releases/latest | jq -r --arg re "$ASSET_RE" '.assets[] | select(.browser_download_url | test($re)) | .browser_download_url' | head -n1)"
  [[ -n "$RELEASE_URL" && "$RELEASE_URL" != null ]] || { echo 'فایل انتشار Mihomo پیدا نشد.' >&2; exit 1; }
  curl -fL "$RELEASE_URL" -o "$WORK_DIR/mihomo.gz"
  gzip -dc "$WORK_DIR/mihomo.gz" > /usr/local/bin/mihomo
  chmod 755 /usr/local/bin/mihomo
fi

install -d -m 0755 /opt/redcore-proxy /etc/titan /etc/titan/providers /var/log/titan
install -m 0755 "$WORK_DIR/redcore_proxy.py" /opt/redcore-proxy/redcore_proxy.py
install -m 0755 "$WORK_DIR/titan" /usr/local/bin/titan
touch /etc/titan/subs.txt
chmod 600 /etc/titan/subs.txt

# مهاجرت از نسخهٔ قدیمی Xray Titan؛ فایل‌های قبلی را حذف نمی‌کند، فقط سرویس
# قدیمی را متوقف می‌کند تا پورت‌های 10801 تا 10808 با Mihomo تداخل نداشته باشند.
systemctl disable --now titan-xray.service 2>/dev/null || true

cat >/etc/systemd/system/titan-mihomo.service <<'EOF'
[Unit]
Description=RedCore-Proxy Mihomo local SOCKS endpoints
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mihomo -d /etc/titan -f /etc/titan/mihomo.yaml
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
echo 'نصب Mihomo کامل شد. اجرا کنید: titan'
