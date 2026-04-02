#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
USER_SYSTEMD_DIR="${HOME}/.config/systemd/user"

mkdir -p "${USER_SYSTEMD_DIR}"

if [[ ! -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  echo "Missing ${REPO_ROOT}/.venv/bin/python. Create the project venv first." >&2
  exit 1
fi

for unit in \
  clawbie-memory-repair.service \
  clawbie-memory-repair.timer \
  clawbie-chat-bridge.service \
  clawbie-chat-bridge.timer \
  clawbie-sub-agent-activity.service \
  clawbie-sub-agent-activity.timer \
  clawbie-nightly-reverie.service \
  clawbie-nightly-reverie.timer \
  minixtts-proxy.service; do
  sed "s|__REPO_ROOT__|${REPO_ROOT}|g" "${SCRIPT_DIR}/${unit}" > "${USER_SYSTEMD_DIR}/${unit}"
done

systemctl --user daemon-reload
systemctl --user enable clawbie-memory-repair.service
systemctl --user enable --now clawbie-memory-repair.timer
systemctl --user enable clawbie-chat-bridge.service
systemctl --user enable --now clawbie-chat-bridge.timer
systemctl --user enable clawbie-sub-agent-activity.service
systemctl --user enable --now clawbie-sub-agent-activity.timer
systemctl --user enable clawbie-nightly-reverie.service
systemctl --user enable --now clawbie-nightly-reverie.timer

echo "Installed units to ${USER_SYSTEMD_DIR}"
echo "Timers are active. Run once now with:"
echo "  systemctl --user start clawbie-memory-repair.service"
echo "  systemctl --user start clawbie-chat-bridge.service"
echo "  systemctl --user start clawbie-sub-agent-activity.service"
echo "  systemctl --user start clawbie-nightly-reverie.service"
