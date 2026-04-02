# MiniMax TTS Troubleshooting Guide

## Overview

This skill provides two methods for TTS:
1. **Direct API** - Uses MiniMax API directly
2. **Proxy** - Uses local OpenAI-compatible proxy (`http://127.0.0.1:18793`)

---

## Common Issues

### Issue: "MiniMax TTS service not available"

**Symptom:** Skill returns error "MiniMax TTS service not available"

**Diagnosis:**
- If using `--use-proxy`: Proxy may not be running
- If using direct API: MINIMAX_API_KEY may not be set

**Fix:**
1. Check if proxy is running:
   ```bash
   curl http://127.0.0.1:18793/health
   ```

2. If proxy not running, start it:
   ```bash
   cd ~/git/clawbie
   python -m minixtts_proxy.app
   ```

3. Or use the proxy flag directly:
   ```bash
   python tts.py synthesize --text "Hello" --use-proxy
   ```

---

### Issue: "Proxy error: 401 - Unauthorized"

**Symptom:** TTS returns 401 error through proxy

**Diagnosis:** MINIMAX_API_KEY not set in the proxy environment

**Fix:**
1. Set the API key:
   ```bash
   export MINIMAX_API_KEY=sk-your-api-key
   python -m minixtts_proxy.app
   ```

2. Or add to .env:
   ```
   MINIMAX_API_KEY=sk-your-api-key
   ```

3. Restart the proxy and retry

---

### Issue: "Proxy error: Connection refused"

**Symptom:** TTS returns "Connection refused" or can't connect to proxy

**Diagnosis:** Proxy service is not running

**Fix:**
1. Check if proxy is running:
   ```bash
   curl http://127.0.0.1:18793/health
   ```

2. Start the proxy:
   ```bash
   cd ~/git/clawbie
   python -m minixtts_proxy.app
   ```

3. For background running with systemd:
   ```bash
   cp ~/git/clawbie/systemd/minixtts-proxy.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable minixtts-proxy
   systemctl --user start minixtts-proxy
   ```

---

### Issue: "MiniMax API error" or "status_code not 0"

**Symptom:** Direct API returns error with status_msg

**Diagnosis:** MiniMax API returned an error

**Fix:**
1. Check API key is valid and has quota
2. Check model name is correct (use `speech-2.8-hd` or `speech-02-turbo`)
3. Check voice ID exists (see `python tts.py voices`)

---

### Issue: Poor audio quality or strange artifacts

**Diagnosis:** Wrong model or voice setting

**Fix:**
1. Try different model:
   ```bash
   python tts.py synthesize --text "Hello" --model speech-2.8-hd  # HD quality
   python tts.py synthesize --text "Hello" --model speech-02-turbo  # Fast
   ```

2. Try different voice:
   ```bash
   python tts.py voices  # list available voices
   python tts.py synthesize --text "Hello" --voice English_Friendly_Guide
   ```

---

## Health Check Commands

### Check proxy is running
```bash
curl http://127.0.0.1:18793/health
```

Expected response:
```json
{
  "status": "configured",
  "has_api_key": true,
  "default_voice": "English_expressive_narrator",
  "default_model": "speech-2.8-hd"
}
```

### Check MiniMax API directly
```bash
python -c "
from minimax_tts.service import MinimaxTTSService
svc = MinimaxTTSService()
print(svc.list_models())
"
```

### List available voices
```bash
python tts.py voices
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| MINIMAX_API_KEY | MiniMax API key | Required |
| TTS_PROXY_URL | Local proxy URL | http://127.0.0.1:18793 |
| TTS_OUTPUT_DIR | Output directory for audio | ~/workspace |
| CLAWBIE_SRC | Path to clawbie src | Auto-detected |

### .env file

Create `~/.env` or `.env` in the skill directory with:
```
MINIMAX_API_KEY=sk-your-key
TTS_PROXY_URL=http://127.0.0.1:18793
TTS_OUTPUT_DIR=~/workspace
```

---

## For Evie (Remote Deployment)

If you're running on a remote machine:

1. **Start the proxy locally** on the remote machine:
   ```bash
   cd ~/git/clawbie
   python -m minixtts_proxy.app
   ```

2. **Use --use-proxy flag** when calling the skill:
   ```bash
   python tts.py synthesize --text "Hello" --use-proxy
   ```

3. **Or configure** the skill to always use proxy by setting:
   ```bash
   export TTS_PROXY_URL=http://127.0.0.1:18793
   ```

---

## Still Stuck?

1. Check the proxy logs:
   ```bash
   journalctl --user -u minixtts-proxy -n 50
   ```

2. Test MiniMax directly:
   ```bash
   curl -X POST https://api.minimax.io/v1/t2a_v2 \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model":"speech-2.8-hd","text":"test","stream":false,"voice_setting":{"voice_id":"English_expressive_narrator"}}'
   ```

3. Contact the operator (Mal) with the error message
