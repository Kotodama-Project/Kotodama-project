#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
test ! -e /opt/kotodama-os
test ! -e /etc/kotodama/os-instance.json
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git xz-utils build-essential python3
install -d -m 755 /opt/kotodama-os/downloads /etc/kotodama
cd /opt/kotodama-os/downloads
curl --fail --location --proto '=https' --tlsv1.2 -o node.tar.xz https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.xz
curl --fail --location --proto '=https' --tlsv1.2 -o pnpm.tgz https://registry.npmjs.org/pnpm/-/pnpm-11.17.0.tgz
python3 /root/kotodama-template-assets/verify-toolchain.py
tar -xJf node.tar.xz -C /opt/kotodama-os
export PATH=/opt/kotodama-os/node-v24.19.0-linux-x64/bin:$PATH
npm install --prefix /opt/kotodama-os/toolchain --ignore-scripts --no-audit --no-fund --offline ./pnpm.tgz
export PATH=/opt/kotodama-os/toolchain/node_modules/.bin:$PATH
useradd --create-home --shell /bin/bash os-runtime
git clone https://github.com/cloudflare/cloudflare-os.git /opt/kotodama-os/core
git -C /opt/kotodama-os/core checkout --detach c0b6f3e52ff0ab8d44d290647e256936e88e6b57
chown -R os-runtime:os-runtime /opt/kotodama-os/core
runuser -u os-runtime -- env PATH="$PATH" CI=true WRANGLER_SEND_METRICS=false DO_NOT_TRACK=1 \
  bash -c 'cd /opt/kotodama-os/core && pnpm install --frozen-lockfile'
test ! -e /opt/kotodama-os/core/.wrangler/state
install -m 644 /root/kotodama-template-assets/kotodama-cloudflare-os.service /etc/systemd/system/kotodama-cloudflare-os.service
install -m 755 /root/kotodama-template-assets/activate-instance.py /usr/local/sbin/kotodama-os-activate
install -m 755 /root/kotodama-template-assets/seal-check.py /usr/local/sbin/kotodama-os-seal-check
systemctl daemon-reload
systemctl enable kotodama-cloudflare-os.service
python3 /usr/local/sbin/kotodama-os-seal-check --record-install
python3 /usr/local/sbin/kotodama-os-seal-check
echo KOTODAMA_TEMPLATE_INSTALL_COMPLETE
