# OPENCODE Update Guide

## Recommended Update Procedure (Gateway-safe)

Follow these steps in your terminal within the OpenClaw directory.

### 0) Backup the Entire Workspace (mandatory)
Create a timestamped backup of the whole OpenClaw workspace before making changes.

```bash
mkdir -p ~/backups
TS=$(date +%Y%m%d-%H%M%S)
tar -czf ~/backups/openclaw-workspace-$TS.tgz -C ~/.openclaw workspace
```

### 1) Prepare Recovery Script (before stopping gateway)
Create a recovery script that can run independently if restart fails.

```bash
cat > /tmp/openclaw-recovery.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

LOG=~/openclaw-recovery.log
{
  echo "[$(date -Is)] Recovery timer fired"
  openclaw doctor --fix || echo "doctor --fix failed"
  openclaw gateway restart || echo "gateway restart failed"

  if ! openclaw gateway status >/dev/null 2>&1; then
    echo "[$(date -Is)] FAULT: gateway still unhealthy after recovery run" >> ~/.openclaw/workspace/memory/recovery-fault.log
  fi
} >> "$LOG" 2>&1
EOF
chmod +x /tmp/openclaw-recovery.sh
```

### 2) Arm 10-minute Recovery Timer (before stopping gateway)
This is critical: timer must be armed while gateway/session is still alive.

```bash
systemd-run --user \
  --unit=openclaw-recovery \
  --on-active=10m \
  /tmp/openclaw-recovery.sh
```

### 3) Stop the Gateway
Now it is safe to stop the gateway.

```bash
openclaw gateway stop
```

### 4) Stash Local Changes
Save modified files to a temporary stack.

```bash
git stash
```

### 5) Pull Latest Updates
Fetch and merge latest code from remote.

```bash
git pull origin main
```

### 6) Re-apply Workspace Files
Restore local changes.

```bash
git stash pop
```

### 7) Rebuild
Update dependencies and rebuild.

```bash
pnpm install && pnpm build
```

### 8) Doctor + Restart

```bash
openclaw doctor --fix
openclaw gateway restart
```

### 9) Verify Health, Then Cancel Recovery Timer
If restart is healthy, cancel the armed failsafe timer/service.

```bash
openclaw gateway status
systemctl --user stop openclaw-recovery.timer 2>/dev/null || true
systemctl --user stop openclaw-recovery.service 2>/dev/null || true
```

---

## Why this ordering matters
If you stop gateway before arming the timer, your active control session can be terminated and the deadman switch may never be created.
