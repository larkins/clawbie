#!/usr/bin/env python3
"""Send a message to OpenClaw via WebSocket to trigger an agent turn.

This allows external scripts (like systemd timers) to trigger agent tasks
by sending messages through the OpenClaw Gateway WebSocket.

Usage:
    python openclaw_ws_client.py "Your message here"
    python openclaw_ws_client.py --agent main --session main "Generate nightly reverie"

The WebSocket server (OpenClaw Gateway) must be running on localhost:18789.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    import websocket
except ImportError:
    print("Error: websocket-client package required. Install with:")
    print("  pip install websocket-client")
    sys.exit(1)

DEFAULT_WS_URL = "ws://localhost:18789"
DEFAULT_AGENT_ID = "main"
DEFAULT_SESSION_KEY = "main"

# Gateway token — MUST be read from openclaw.json config.
# Do not hardcode tokens here; always use get_gateway_token() which reads from config.
GATEWAY_TOKEN = ""  # No default — must come from openclaw.json


def get_gateway_token() -> str:
    """Read gateway token from openclaw.json config."""
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        config = json.loads(config_path.read_text())
        token = config.get("gateway", {}).get("auth", {}).get("token", "")
        if not token:
            raise ValueError("No gateway auth token found in openclaw.json")
        return token
    except Exception as e:
        raise RuntimeError(
            f"Could not read gateway token from {config_path}: {e}. "
            "Set gateway.auth.token in openclaw.json"
        )


def authenticate(ws, token: str) -> bool:
    """Authenticate with the Gateway using token challenge.
    
    The Gateway sends a connect.challenge event with a nonce.
    We respond with an auth message containing the token.
    """
    try:
        # Receive the challenge
        ws.settimeout(10)
        challenge = ws.recv()
        data = json.loads(challenge)
        
        if data.get("type") == "event" and data.get("event") == "connect.challenge":
            nonce = data.get("payload", {}).get("nonce", "")
            # Respond with auth
            auth_msg = {
                "type": "auth",
                "token": token,
                "nonce": nonce
            }
            ws.send(json.dumps(auth_msg))
            
            # Wait for auth result
            result = ws.recv()
            result_data = json.loads(result)
            if result_data.get("type") == "auth_result" and result_data.get("success"):
                return True
            
        return False
    except Exception as e:
        print(f"Auth error: {e}")
        return False


def send_openclaw_message(
    message: str,
    agent_id: str = DEFAULT_AGENT_ID,
    session_key: str = DEFAULT_SESSION_KEY,
    ws_url: str = DEFAULT_WS_URL,
    timeout: float = 120.0,
    wait_for_response: bool = True,
) -> dict:
    """Send a message to OpenClaw via WebSocket.
    
    Args:
        message: The message to send to the agent
        agent_id: Agent ID to target (default: "main")
        session_key: Session key (default: "main")
        ws_url: WebSocket URL (default: ws://localhost:18789)
        timeout: Connection timeout in seconds (default: 120)
        wait_for_response: Whether to wait for agent response (default: True)
    
    Returns:
        dict: The response from the agent (or {"status": "sent"} if not waiting)
    """
    token = get_gateway_token()
    
    try:
        # Create connection with timeout
        ws = websocket.create_connection(ws_url, timeout=timeout)
        
        # Authenticate with Gateway
        if not authenticate(ws, token):
            ws.close()
            return {"error": "Authentication failed"}
        
        print(f"Authenticated with Gateway")
        
        # Build the payload
        payload = {
            "method": "agent",
            "params": {
                "agentId": agent_id,
                "sessionKey": session_key,
                "message": message
            }
        }
        
        # Send the message
        ws.send(json.dumps(payload))
        print(f"Sent message to agent '{agent_id}' (session: {session_key})")
        
        if not wait_for_response:
            ws.close()
            return {"status": "sent", "message": "Trigger sent, not waiting for response"}
        
        # Receive response(s) - agent may send multiple messages
        final_response = None
        ws.settimeout(timeout)
        
        while True:
            try:
                result = ws.recv()
                if not result:
                    break
                    
                response_data = json.loads(result)
                
                # Check if this is the final response
                if "result" in response_data:
                    final_response = response_data["result"]
                    if "text" in final_response:
                        print(f"\nAgent: {final_response['text'][:500]}...")
                    break
                elif "error" in response_data:
                    print(f"Error: {response_data['error']}")
                    final_response = response_data
                    break
                    
            except websocket.WebSocketTimeoutException:
                print("Timeout waiting for response")
                break
        
        ws.close()
        return final_response or {"status": "sent", "message": "No response received"}
        
    except websocket.WebSocketException as e:
        print(f"WebSocket error: {e}")
        return {"error": str(e)}
    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Send a message to OpenClaw via WebSocket"
    )
    parser.add_argument(
        "message",
        help="Message to send to the agent"
    )
    parser.add_argument(
        "--agent", "-a",
        default=DEFAULT_AGENT_ID,
        help=f"Agent ID (default: {DEFAULT_AGENT_ID})"
    )
    parser.add_argument(
        "--session", "-s",
        default=DEFAULT_SESSION_KEY,
        help=f"Session key (default: {DEFAULT_SESSION_KEY})"
    )
    parser.add_argument(
        "--url", "-u",
        default=DEFAULT_WS_URL,
        help=f"WebSocket URL (default: {DEFAULT_WS_URL})"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=120.0,
        help="Timeout in seconds (default: 120)"
    )
    parser.add_argument(
        "--prompt-file", "-f",
        type=Path,
        help="Read message from file instead of argument"
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Send message and exit without waiting for response"
    )
    
    args = parser.parse_args()
    
    # Get message from file or argument
    if args.prompt_file:
        if not args.prompt_file.exists():
            print(f"Error: File not found: {args.prompt_file}")
            sys.exit(1)
        message = args.prompt_file.read_text()
    else:
        message = args.message
    
    # Send the message
    response = send_openclaw_message(
        message=message,
        agent_id=args.agent,
        session_key=args.session,
        ws_url=args.url,
        timeout=args.timeout,
        wait_for_response=not args.no_wait
    )
    
    # Exit with appropriate code
    if "error" in response:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()