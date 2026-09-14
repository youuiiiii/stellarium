"""Thin MyAnimeList Web API v2 client used by Hermes native tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

from hermes_cli.config import get_hermes_home


class MALError(RuntimeError):
    """Base MyAnimeList tool error."""


class MALAuthRequiredError(MALError):
    """Raised when the user needs to authenticate with MyAnimeList first."""


class MALAPIError(MALError):
    """Structured MyAnimeList API failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def _strip_none(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not data:
        return {}
    return {k: v for k, v in data.items() if v is not None}


class MALClient:
    BASE_URL = "https://api.myanimelist.net/v2"
    AUTH_URL = "https://myanimelist.net/v1/oauth2/token"

    def __init__(self) -> None:
        self._tokens_path = get_hermes_home() / "mal" / "tokens.json"
        self._auth_state_path = get_hermes_home() / "mal" / "auth_state.json"
        self._tokens = self._load_tokens()

    def _load_tokens(self) -> Dict[str, Any]:
        if not self._tokens_path.exists():
            raise MALAuthRequiredError(
                f"MyAnimeList tokens not found at {self._tokens_path}. Please authenticate first."
            )
        try:
            with open(self._tokens_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("access_token"):
                raise MALAuthRequiredError("MyAnimeList access token is empty.")
            return data
        except Exception as exc:
            if isinstance(exc, MALAuthRequiredError):
                raise
            raise MALAuthRequiredError(f"Failed to read MAL tokens: {exc}") from exc

    def _load_client_id(self) -> str:
        if self._auth_state_path.exists():
            try:
                with open(self._auth_state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                cid = state.get("client_id")
                if cid:
                    return str(cid)
            except Exception:
                pass
        return "76153138ea74cb88617608bf0bb2d7f3"

    def refresh_access_token(self) -> Dict[str, Any]:
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise MALAuthRequiredError("No refresh token available to refresh MAL credentials.")

        client_id = self._load_client_id()
        payload = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = httpx.post(
            self.AUTH_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )

        if response.status_code >= 400:
            raise MALAPIError(
                f"Failed to refresh MAL access token ({response.status_code}): {response.text}",
                status_code=response.status_code,
                response_body=response.text,
            )

        new_tokens = response.json()
        self._tokens.update(new_tokens)
        try:
            with open(self._tokens_path, "w", encoding="utf-8") as f:
                json.dump(self._tokens, f, indent=2)
        except Exception as exc:
            raise MALError(f"Failed to save refreshed MAL tokens: {exc}") from exc

        return self._tokens

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tokens['access_token']}",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        allow_retry_on_401: bool = True,
    ) -> Any:
        url = f"{self.BASE_URL}{path}" if path.startswith("/") else f"{self.BASE_URL}/{path}"
        headers = self._headers()

        response = httpx.request(
            method=method,
            url=url,
            headers=headers,
            params=_strip_none(params),
            data=_strip_none(data) if data is not None else None,
            json=_strip_none(json_body) if json_body is not None else None,
            timeout=30.0,
        )

        if response.status_code == 401 and allow_retry_on_401:
            self.refresh_access_token()
            return self.request(
                method,
                path,
                params=params,
                data=data,
                json_body=json_body,
                allow_retry_on_401=False,
            )

        if response.status_code >= 400:
            raise MALAPIError(
                f"MAL API {method} {path} returned {response.status_code}: {response.text}",
                status_code=response.status_code,
                response_body=response.text,
            )

        if response.status_code == 204 or not response.content:
            return {"success": True, "status_code": response.status_code}

        if "application/json" in response.headers.get("content-type", ""):
            return response.json()

        return {"success": True, "text": response.text}

    def search_anime(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        fields: Optional[str] = None,
    ) -> Dict[str, Any]:
        default_fields = "id,title,main_picture,alternative_titles,mean,num_episodes,status,genres,my_list_status"
        params = {
            "q": query,
            "limit": limit,
            "offset": offset,
            "fields": fields or default_fields,
        }
        return self.request("GET", "/anime", params=params)

    def get_user_animelist(
        self,
        *,
        username: str = "@me",
        status: Optional[str] = None,
        sort: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        fields: Optional[str] = None,
    ) -> Dict[str, Any]:
        default_fields = "list_status,num_episodes,main_picture"
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "fields": fields or default_fields,
        }
        if status:
            params["status"] = status
        if sort:
            params["sort"] = sort
        return self.request("GET", f"/users/{username}/animelist", params=params)

    def get_anime_details(
        self,
        anime_id: int,
        *,
        fields: Optional[str] = None,
    ) -> Dict[str, Any]:
        default_fields = (
            "id,title,main_picture,alternative_titles,synopsis,mean,rank,popularity,"
            "status,genres,my_list_status,num_episodes,start_season,studios,broadcast,source"
        )
        params = {"fields": fields or default_fields}
        return self.request("GET", f"/anime/{anime_id}", params=params)

    def update_user_animelist(
        self,
        anime_id: int,
        *,
        status: Optional[str] = None,
        is_rewatching: Optional[bool] = None,
        score: Optional[int] = None,
        num_watched_episodes: Optional[int] = None,
        priority: Optional[int] = None,
        num_times_rewatched: Optional[int] = None,
        rewatch_value: Optional[int] = None,
        tags: Optional[str] = None,
        comments: Optional[str] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "status": status,
            "is_rewatching": is_rewatching,
            "score": score,
            "num_watched_episodes": num_watched_episodes,
            "priority": priority,
            "num_times_rewatched": num_times_rewatched,
            "rewatch_value": rewatch_value,
            "tags": tags,
            "comments": comments,
        }
        return self.request("PATCH", f"/anime/{anime_id}/my_list_status", data=data)

    def delete_user_animelist(self, anime_id: int) -> Dict[str, Any]:
        return self.request("DELETE", f"/anime/{anime_id}/my_list_status")

    def get_seasonal_anime(
        self,
        year: int,
        season: str,
        *,
        sort: str = "anime_score",
        limit: int = 20,
        offset: int = 0,
        fields: Optional[str] = None,
    ) -> Dict[str, Any]:
        default_fields = "id,title,main_picture,mean,num_episodes,genres,status,my_list_status"
        params = {
            "sort": sort,
            "limit": limit,
            "offset": offset,
            "fields": fields or default_fields,
        }
        return self.request("GET", f"/anime/season/{year}/{season.lower()}", params=params)

    def get_user_profile(
        self,
        username: str = "@me",
        *,
        fields: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"fields": fields} if fields else None
        return self.request("GET", f"/users/{username}", params=params)
