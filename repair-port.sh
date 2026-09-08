#!/usr/bin/env bash
# Repair one SOCKS port by trying fallback NordVPN countries without touching other ports.
set -euo pipefail

port="${1:-}"
case "$port" in
  1081) key=DE; short=de ;;
  1082) key=GR; short=gr ;;
  1083) key=BG; short=bg ;;
  1084) key=RO; short=ro ;;
  1085) key=AT; short=at ;;
  1086) key=FR; short=fr ;;
  1087) key=PL; short=pl ;;
  *) echo 'Usage: sudo ./repair-port.sh <1081..1087>'; exit 1 ;;
esac

[[ -f .env ]] || { echo 'Missing .env. Run RedSocKs5 setup first.'; exit 1; }
command -v docker >/dev/null || { echo 'Docker is not installed.'; exit 1; }

candidates=(Germany United_States United_Kingdom Netherlands France Italy Austria Romania Bulgaria Poland Switzerland Hungary Czech_Republic Serbia Greece Spain Sweden Denmark)
current=$(sed -n "s/^LOC_${key}=//p" .env | head -n1 || true)
[[ -n "$current" ]] && candidates=("$current" "${candidates[@]}")

wait_vpn() {
  local deadline=$((SECONDS+90)) state
  while (( SECONDS < deadline )); do
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "nord-socks-${short}" 2>/dev/null || true)
    [[ "$state" == healthy ]] && return 0
    sleep 3
  done
  return 1
}

used='|'
for country in "${candidates[@]}"; do
  [[ "$used" == *"|$country|"* ]] && continue
  used="${used}${country}|"
  echo "Testing $country for SOCKS 127.0.0.1:$port..."
  sed -i "s/^LOC_${key}=.*/LOC_${key}=${country}/" .env
  docker compose up -d --force-recreate "vpn-${short}" "socks-${short}" >/dev/null 2>&1 || true
  if wait_vpn && curl --silent --show-error --fail --max-time 20 --socks5-hostname "127.0.0.1:${port}" https://ifconfig.me >/dev/null; then
    echo "OK: 127.0.0.1:${port} -> ${country}"
    docker compose ps "vpn-${short}" "socks-${short}"
    exit 0
  fi
  echo "Failed: ${country}; trying next country..."
done

echo "No healthy replacement found for port ${port}."
exit 1
