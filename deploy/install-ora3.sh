#!/usr/bin/env bash
# Safe ORA3 install: prepare binaries and unit only, NEVER enable bot or write secrets.
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo "run as root on ORA3" >&2; exit 1; fi
SOURCE_DIR=$(cd "$(dirname "$0")/.." && pwd)
if [[ ! -f "$SOURCE_DIR/src/roborath/irc_adapter.py" ]]; then
  echo "not a RoboRath source checkout" >&2; exit 1
fi
if ! id roborath >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/roborath --shell /usr/sbin/nologin roborath
fi
install -d -o root -g root -m 0755 /opt/roborath
install -d -o roborath -g roborath -m 0700 /var/lib/roborath /var/lib/roborath/private
cp -a "$SOURCE_DIR/src" /opt/roborath/
cp -a "$SOURCE_DIR/pyproject.toml" /opt/roborath/
chown -R root:root /opt/roborath/src /opt/roborath/pyproject.toml
python3 -m venv /opt/roborath/.venv
/opt/roborath/.venv/bin/python -m pip install --quiet --disable-pip-version-check \
   'httpx>=0.27,<1' 'websockets>=14,<17'
install -m 0644 "$SOURCE_DIR/deploy/roborath-irc.service" /etc/systemd/system/roborath-irc.service
systemctl daemon-reload
systemctl disable --now roborath-irc.service >/dev/null 2>&1 || true
echo "Source and service installed. RoboRath remains DISABLED."
if [[ -e /etc/roborath.env ]]; then
  mode=$(stat -c %a /etc/roborath.env)
  if [[ "$mode" != "600" ]]; then
    echo "Warning: /etc/roborath.env must have mode 600 before starting." >&2
  fi
else
  echo "Create /etc/roborath.env mode 600 AFTER provisioning rotated OAuth and relay account."
fi
echo "Do not enable until the account IDs, token refresh and private Mattermost relay are verified."
