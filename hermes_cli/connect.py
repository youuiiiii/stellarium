"""
Stellarium Unified Connect Hub: Intuitive OAuth & Account Connector.

Provides zero-friction, one-command browser authentication for:
1. 🎵 Spotify (PKCE OAuth with auto-loopback on port 43827 or 8888)
2. 🍿 MyAnimeList (PKCE OAuth with auto-loopback on port 8080)

Zero manual file editing. Tokens and credentials are automatically
managed, stored in standard profile/home directories, and verified.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

from hermes_constants import get_hermes_home

# Default Bundled Client IDs
DEFAULT_MAL_CLIENT_ID = "76153138ea74cb88617608bf0bb2d7f3"
DEFAULT_SPOTIFY_FALLBACK_CLIENT_ID = "c907f902caf44924a022b4f24e4a189d"

MAL_AUTH_URL = "https://myanimelist.net/v1/oauth2/authorize"
MAL_TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"
MAL_API_BASE = "https://api.myanimelist.net/v2"


def _stella_home() -> Path:
    """Resolve home directory for Stellarium/Hermes."""
    return get_hermes_home()


# ============================================================================
# 1. MyAnimeList (MAL) Connection Logic
# ============================================================================

def get_mal_tokens_path() -> Path:
    mal_dir = _stella_home() / "mal"
    mal_dir.mkdir(parents=True, exist_ok=True)
    return mal_dir / "tokens.json"


def get_mal_status() -> Dict[str, Any]:
    """Inspect current MyAnimeList connection status."""
    token_file = get_mal_tokens_path()
    if not token_file.exists():
        return {"connected": False, "reason": "No tokens stored"}

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        access_token = tokens.get("access_token")
        if not access_token:
            return {"connected": False, "reason": "Empty access token"}

        # Probe user profile to verify valid token
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = httpx.get(
            f"{MAL_API_BASE}/users/@me?fields=anime_statistics",
            headers=headers,
            timeout=8.0,
        )

        if resp.status_code == 401 and tokens.get("refresh_token"):
            # Try refresh
            refreshed = refresh_mal_token(tokens)
            if refreshed:
                return get_mal_status()
            return {"connected": False, "reason": "Token expired, refresh failed"}

        if resp.status_code == 200:
            user_data = resp.json()
            stats = user_data.get("anime_statistics", {})
            return {
                "connected": True,
                "username": user_data.get("name"),
                "id": user_data.get("id"),
                "watching": stats.get("num_items_watching", 0),
                "completed": stats.get("num_items_completed", 0),
                "days_watched": stats.get("num_days_watched", 0),
                "mean_score": stats.get("mean_score", 0),
                "raw": user_data,
            }
        return {"connected": False, "status_code": resp.status_code, "reason": resp.text[:100]}
    except Exception as exc:
        return {"connected": False, "reason": str(exc)}


def refresh_mal_token(tokens: Dict[str, Any], client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None

    cid = client_id or tokens.get("client_id") or DEFAULT_MAL_CLIENT_ID
    payload = {
        "client_id": cid,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        resp = httpx.post(
            MAL_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20.0,
        )
        if resp.status_code == 200:
            new_tokens = resp.json()
            tokens.update(new_tokens)
            tokens["client_id"] = cid
            with open(get_mal_tokens_path(), "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)
            return tokens
    except Exception:
        pass
    return None


def connect_mal(client_id: Optional[str] = None, no_browser: bool = False, port: int = 8080) -> bool:
    """Launch intuitive PKCE authorization for MyAnimeList."""
    cid = client_id or DEFAULT_MAL_CLIENT_ID
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    # Generate 128-char URL-safe PKCE code verifier
    code_verifier = secrets.token_urlsafe(96)[:128]
    state_nonce = uuid.uuid4().hex

    callback_result: Dict[str, Any] = {"code": None, "state": None, "error": None}

    class _MALCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            callback_result["code"] = params.get("code", [None])[0]
            callback_result["state"] = params.get("state", [None])[0]
            callback_result["error"] = params.get("error", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

            if callback_result["error"]:
                body = (
                    "<html><body style='background:#0a0a12;color:#f43f5e;font-family:sans-serif;text-align:center;padding:50px;'>"
                    f"<h2>Authorization Failed: {callback_result['error']}</h2>"
                    "<p>You can close this tab and try again.</p></body></html>"
                )
            else:
                body = (
                    "<html><body style='background:#0a0a12;color:#f3e8ff;font-family:sans-serif;text-align:center;padding:50px;'>"
                    "<h1 style='color:#b794f6;'>✦ Stella & MyAnimeList Connected! ✦</h1>"
                    "<p style='color:#a39abf;'>Authentication was captured successfully. You can close this window now.</p>"
                    "</body></html>"
                )
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    try:
        server = HTTPServer(("127.0.0.1", port), _MALCallbackHandler)
    except OSError:
        # Fallback port if 8080 is busy
        port = 8889
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        server = HTTPServer(("127.0.0.1", port), _MALCallbackHandler)

    auth_params = {
        "response_type": "code",
        "client_id": cid,
        "code_challenge": code_verifier,
        "code_challenge_method": "plain",
        "state": state_nonce,
        "redirect_uri": redirect_uri,
    }
    auth_url = f"{MAL_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    print(f"\n{'=' * 60}")
    print("✦ MyAnimeList Authorization (Project Stella)")
    print(f"{'=' * 60}")
    print(f"Client ID:    {cid}")
    print(f"Redirect URI: {redirect_uri}\n")
    print(f"Opening browser to authorize:\n{auth_url}\n")

    if not no_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            print("Could not auto-open browser. Please copy and open the URL above manually.")

    print("Waiting for browser authorization...")
    server.timeout = 180.0
    while not callback_result["code"] and not callback_result["error"]:
        server.handle_request()

    server.server_close()

    if callback_result["error"]:
        print(f"\n❌ MyAnimeList authorization rejected: {callback_result['error']}")
        return False

    auth_code = callback_result["code"]
    if not auth_code:
        print("\n❌ Authorization timed out or no code received.")
        return False

    print("Exchanging authorization code for tokens...")
    token_payload = {
        "client_id": cid,
        "grant_type": "authorization_code",
        "code": auth_code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }

    try:
        resp = httpx.post(
            MAL_TOKEN_URL,
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            print(f"❌ Failed to obtain tokens ({resp.status_code}): {resp.text}")
            return False

        tokens_data = resp.json()
        tokens_data["client_id"] = cid
        tokens_data["obtained_at"] = time.time()

        # Save to mal/tokens.json
        tokens_path = get_mal_tokens_path()
        with open(tokens_path, "w", encoding="utf-8") as f:
            json.dump(tokens_data, f, indent=2)

        # Save auth state
        auth_state_path = _stella_home() / "mal" / "auth_state.json"
        with open(auth_state_path, "w", encoding="utf-8") as f:
            json.dump({"client_id": cid, "code_verifier": code_verifier}, f, indent=2)

        # Immediate verification
        status = get_mal_status()
        if status.get("connected"):
            print(f"\n🎉 Successfully connected to MyAnimeList!")
            print(f"👤 Account:   @{status.get('username')}")
            print(f"📺 Watching:  {status.get('watching')} anime")
            print(f"✅ Completed: {status.get('completed')} anime")
            print(f"📁 Stored at: {tokens_path}\n")
            return True
        else:
            print("\n⚠️ Tokens saved, but verification probe returned warning.")
            return True
    except Exception as exc:
        print(f"\n❌ Error during token exchange: {exc}")
        return False


# ============================================================================
# 2. Spotify Connection Logic
# ============================================================================

def get_spotify_status() -> Dict[str, Any]:
    """Inspect current Spotify connection status and active playback."""
    from hermes_cli.auth_spotify import get_spotify_auth_status, resolve_spotify_runtime_credentials

    auth_status = get_spotify_auth_status()
    if not auth_status.get("logged_in"):
        return {"connected": False, "reason": "Not authenticated with Spotify"}

    try:
        creds = resolve_spotify_runtime_credentials()
        access_token = creds.get("access_token") or creds.get("api_key")
        if not access_token:
            return {"connected": False, "reason": "No access token available"}

        headers = {"Authorization": f"Bearer {access_token}"}

        # Fetch user profile
        user_resp = httpx.get("https://api.spotify.com/v1/me", headers=headers, timeout=8.0)
        user_data = user_resp.json() if user_resp.status_code == 200 else {}

        # Fetch devices
        dev_resp = httpx.get("https://api.spotify.com/v1/me/player/devices", headers=headers, timeout=8.0)
        devices = dev_resp.json().get("devices", []) if dev_resp.status_code == 200 else []
        active_device = next((d for d in devices if d.get("is_active")), None)

        # Fetch currently playing track
        playback_resp = httpx.get("https://api.spotify.com/v1/me/player", headers=headers, timeout=8.0)
        track_name = None
        artist_name = None
        is_playing = False
        if playback_resp.status_code == 200 and playback_resp.content:
            try:
                pb_data = playback_resp.json()
                is_playing = pb_data.get("is_playing", False)
                item = pb_data.get("item") or {}
                track_name = item.get("name")
                artists = [a.get("name") for a in item.get("artists", [])]
                artist_name = ", ".join(artists) if artists else None
            except Exception:
                pass

        return {
            "connected": True,
            "display_name": user_data.get("display_name"),
            "id": user_data.get("id"),
            "product": user_data.get("product"),
            "country": user_data.get("country"),
            "devices_count": len(devices),
            "active_device": active_device.get("name") if active_device else None,
            "is_playing": is_playing,
            "track": track_name,
            "artist": artist_name,
        }
    except Exception as exc:
        return {"connected": True, "auth_ok": True, "note": f"Auth valid, query error: {exc}"}


def connect_spotify(client_id: Optional[str] = None, no_browser: bool = False) -> bool:
    """Launch Spotify PKCE authentication flow seamlessly."""
    from types import SimpleNamespace
    from hermes_cli.auth_spotify import login_spotify_command, _spotify_client_id

    # Fallback to known client_id if missing to make it zero-friction
    cid = client_id or os.environ.get("HERMES_SPOTIFY_CLIENT_ID") or os.environ.get("STELLA_SPOTIFY_CLIENT_ID")
    if not cid:
        # Check existing state
        try:
            cid = _spotify_client_id()
        except Exception:
            cid = DEFAULT_SPOTIFY_FALLBACK_CLIENT_ID

    args = SimpleNamespace(
        client_id=cid,
        redirect_uri=None,
        scope=None,
        no_browser=no_browser,
        timeout=180.0,
    )

    try:
        login_spotify_command(args)
        status = get_spotify_status()
        print(f"\n🎉 Successfully connected to Spotify!")
        if status.get("connected"):
            print(f"👤 Account:       {status.get('display_name')} ({status.get('product', 'free')})")
            print(f"🔈 Active Device: {status.get('active_device') or 'None active'}")
            if status.get("track"):
                print(f"🎵 Now Playing:   {status.get('artist')} - {status.get('track')}")
        return True
    except SystemExit as exc:
        print(f"⚠️ Spotify connection cancelled: {exc}")
        return False
    except Exception as exc:
        print(f"❌ Spotify connection failed: {exc}")
        return False


# ============================================================================
# 3. Unified Dashboard & Command Dispatcher
# ============================================================================

def _box_line(text: str, width: int = 64) -> str:
    line = f"│  {text}"
    if len(line) > width - 2:
        line = line[:width - 5] + "..."
    return line.ljust(width - 1) + "│"


def print_connect_status() -> None:
    """Display a rich, unified terminal dashboard of all connected services."""
    mal = get_mal_status()
    spot = get_spotify_status()

    w = 64
    print("\n" + "╭" + "─" * (w - 2) + "╮")
    title = "✦ STELLARIUM INTEGRATIONS HUB ✦"
    print("│" + title.center(w - 2) + "│")
    print("│" + " " * (w - 2) + "│")

    # Spotify Section
    if spot.get("connected"):
        user = spot.get("display_name") or spot.get("id") or "Connected"
        prod = f"({spot.get('product')})" if spot.get("product") else ""
        dev = spot.get("active_device") or "No active device"
        print(_box_line(f"🎵 Spotify:      ● CONNECTED", w))
        print(_box_line(f"   Account:      {user} {prod}".rstrip(), w))
        print(_box_line(f"   Device:       {dev}", w))
        if spot.get("track"):
            playing_state = "▶ Playing" if spot.get("is_playing") else "⏸ Paused"
            print(_box_line(f"   {playing_state}:    {spot.get('artist')} - {spot.get('track')}", w))
    else:
        print(_box_line(f"🎵 Spotify:      ○ NOT CONNECTED", w))
        print(_box_line(f"   To connect:   stella connect spotify", w))

    print("│" + " " * (w - 2) + "│")

    # MyAnimeList Section
    if mal.get("connected"):
        user = f"@{mal.get('username')}"
        watching = mal.get("watching", 0)
        completed = mal.get("completed", 0)
        print(_box_line(f"🍿 MyAnimeList:  ● CONNECTED", w))
        print(_box_line(f"   Account:      {user}", w))
        print(_box_line(f"   List Summary: {watching} watching | {completed} completed", w))
    else:
        print(_box_line(f"🍿 MyAnimeList:  ○ NOT CONNECTED", w))
        print(_box_line(f"   To connect:   stella connect mal", w))

    print("│" + " " * (w - 2) + "│")
    print("╰" + "─" * (w - 2) + "╯\n")


def connect_command(args: Any) -> None:
    """CLI handler for `stella connect [target]`."""
    target = getattr(args, "target", None)
    if not target or target == "status":
        print_connect_status()
        return

    target = str(target).strip().lower()
    no_browser = getattr(args, "no_browser", False)
    client_id = getattr(args, "client_id", None)

    if target in {"spotify", "music"}:
        connect_spotify(client_id=client_id, no_browser=no_browser)
    elif target in {"mal", "myanimelist", "anime"}:
        connect_mal(client_id=client_id, no_browser=no_browser)
    else:
        print(f"Unknown connection target: '{target}'. Available: spotify, mal, status")
        print_connect_status()
