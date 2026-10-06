"""Asynchronous HTTP client for interacting with slskd daemon API."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from .config import Settings, settings as default_settings

logger = logging.getLogger("slskd_mcp.client")


class SlskdClient:
    """Async client for slskd REST API with JWT auto-refresh and connection pooling."""

    def __init__(self, config: Optional[Settings] = None):
        self.config = config or default_settings
        self.base_url = self.config.url.rstrip("/")
        self.username = self.config.username
        self.password = self.config.password
        self.api_key = self.config.api_key
        self.timeout = self.config.timeout

        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "SlskdClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _authenticate(self, force: bool = False) -> None:
        """Authenticate with slskd via /api/v0/session and cache the JWT token."""
        if self.api_key:
            # Static API key authentication doesn't use JWT tokens
            return

        now = time.time()
        if not force and self._token and now < (self._token_expires - 60):
            return

        async with self._lock:
            # Double check inside lock
            if not force and self._token and now < (self._token_expires - 60):
                return

            client = await self._get_client()
            login_payload = {
                "username": self.username,
                "password": self.password,
            }
            try:
                response = await client.post("/api/v0/session", json=login_payload)
                response.raise_for_status()
                data = response.json()
                self._token = data.get("token")
                self._token_expires = float(data.get("expires", now + 3600))
                logger.info("Successfully authenticated with slskd daemon.")
            except httpx.HTTPError as exc:
                logger.error("Authentication with slskd failed: %s", exc)
                raise RuntimeError(
                    f"Failed to authenticate with slskd at {self.base_url}: {exc}"
                ) from exc

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an authenticated HTTP request with auto-retry on 401 Unauthorized."""
        await self._authenticate()
        client = await self._get_client()

        req_headers = self._get_headers()
        if headers:
            req_headers.update(headers)

        req_timeout = httpx.Timeout(timeout or self.timeout)

        resp = await client.request(
            method,
            path,
            headers=req_headers,
            timeout=req_timeout,
            **kwargs,
        )

        # Handle token expiration (401) with auto-reauth and retry
        if resp.status_code == 401 and not self.api_key:
            logger.warning("Received 401 Unauthorized; attempting token refresh...")
            await self._authenticate(force=True)
            req_headers = self._get_headers()
            if headers:
                req_headers.update(headers)
            resp = await client.request(
                method,
                path,
                headers=req_headers,
                timeout=req_timeout,
                **kwargs,
            )

        return resp

    # -------------------------------------------------------------------------
    # Status & Application
    # -------------------------------------------------------------------------

    async def get_application(self) -> Dict[str, Any]:
        """Fetch slskd daemon application details."""
        resp = await self.request("GET", "/api/v0/application")
        resp.raise_for_status()
        return resp.json()

    async def get_server(self) -> Dict[str, Any]:
        """Fetch slskd Soulseek network server state."""
        resp = await self.request("GET", "/api/v0/server")
        resp.raise_for_status()
        return resp.json()

    async def get_status(self) -> Dict[str, Any]:
        """Fetch aggregated server status overview."""
        app_task = self.get_application()
        srv_task = self.get_server()
        app_info, srv_info = await asyncio.gather(app_task, srv_task)

        user_info = app_info.get("user") or {}
        user_stats = user_info.get("statistics") or {}
        shares_info = app_info.get("shares") or {}
        version_info = app_info.get("version") or {}

        # Fetch active downloads for current transfer speed if possible
        download_speed = 0.0
        try:
            dl_resp = await self.request("GET", "/api/v0/transfers/downloads")
            if dl_resp.status_code == 200:
                for peer in dl_resp.json():
                    for d in peer.get("directories", []):
                        for f in d.get("files", []):
                            if "InProgress" in f.get("state", ""):
                                download_speed += float(f.get("averageSpeed", 0.0))
        except Exception:
            pass

        return {
            "connected": srv_info.get("isConnected", False),
            "logged_in": srv_info.get("isLoggedIn", False),
            "username": user_info.get("username", srv_info.get("username", "")),
            "version": version_info.get("current", version_info.get("full", "unknown")),
            "upload_speed": float(user_stats.get("averageSpeed", 0.0)),
            "download_speed": round(download_speed, 2),
            "peer_count": len(app_info.get("users", [])),
            "shares_directories": shares_info.get("directories", 0),
            "shares_files": shares_info.get("files", 0),
            "server_address": srv_info.get("ipEndPoint", srv_info.get("address", "")),
        }

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    async def initiate_search(self, query: str, timeout_seconds: int = 15) -> str:
        """Initiate a search across Soulseek network and return the search ID."""
        # slskd expects searchTimeout in milliseconds (minimum 5000ms)
        timeout_ms = max(5, int(timeout_seconds)) * 1000
        payload = {
            "searchText": query,
            "searchTimeout": timeout_ms,
        }
        resp = await self.request("POST", "/api/v0/searches", json=payload)
        resp.raise_for_status()
        return resp.json()["id"]

    async def get_search_state(self, search_id: str) -> Dict[str, Any]:
        """Poll search status by search ID."""
        resp = await self.request("GET", f"/api/v0/searches/{search_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_search_responses(self, search_id: str) -> List[Dict[str, Any]]:
        """Retrieve peer responses for a search ID."""
        resp = await self.request("GET", f"/api/v0/searches/{search_id}/responses")
        resp.raise_for_status()
        return resp.json()

    async def delete_search(self, search_id: str) -> None:
        """Delete/cleanup search from slskd memory."""
        try:
            await self.request("DELETE", f"/api/v0/searches/{search_id}")
        except Exception as exc:
            logger.debug("Failed to delete search %s: %s", search_id, exc)

    async def search(
        self,
        query: str,
        timeout_seconds: int = 15,
        max_results: int = 50,
        format_filter: Optional[str] = None,
        min_bitrate: int = 0,
    ) -> List[Dict[str, Any]]:
        """Search Soulseek network, poll until responses arrive or timeout, rank & filter results."""
        search_id = await self.initiate_search(query, timeout_seconds=timeout_seconds)
        start_time = time.time()
        max_wait = max(5, int(timeout_seconds)) + 5

        responses: List[Dict[str, Any]] = []
        try:
            # 1. Poll until search finishes or reaches requested timeout
            while (time.time() - start_time) < max_wait:
                await asyncio.sleep(1.0)
                state_data = await self.get_search_state(search_id)
                is_complete = state_data.get("isComplete", False)
                response_count = state_data.get("responseCount", 0)

                if is_complete or ((time.time() - start_time) >= timeout_seconds and response_count > 0):
                    break

            # 2. Fetch responses (slskd may take ~1s to map responses after completion)
            resp_wait_start = time.time()
            while (time.time() - resp_wait_start) < 10.0:
                responses = await self.get_search_responses(search_id)
                if responses:
                    break
                await asyncio.sleep(1.0)
        finally:
            # Clean up search in background
            asyncio.create_task(self.delete_search(search_id))

        # Flatten and filter results
        results: List[Dict[str, Any]] = []
        ext_clean = format_filter.lower().lstrip(".") if format_filter else None

        for resp in responses:
            username = resp.get("username", "")
            has_free_slot = resp.get("hasFreeUploadSlot", False)
            upload_speed = resp.get("uploadSpeed", 0)
            queue_length = resp.get("queueLength", 0)

            for f in resp.get("files", []):
                filename = f.get("filename", "")
                if not filename:
                    continue

                # Extension filter
                if ext_clean and not filename.lower().endswith(f".{ext_clean}"):
                    continue

                # Bitrate filter: only filter if bitrate is reported and below minimum
                bitrate = f.get("bitRate")
                if min_bitrate > 0 and bitrate is not None and bitrate > 0 and bitrate < min_bitrate:
                    continue

                size = f.get("size", 0)
                size_mb = round(size / (1024 * 1024), 2)

                results.append({
                    "user": username,
                    "filename": filename,
                    "size": size,
                    "size_mb": size_mb,
                    "bitrate": bitrate,
                    "bit_depth": f.get("bitDepth"),
                    "sample_rate": f.get("sampleRate"),
                    "length": f.get("length"),
                    "has_free_upload_slot": has_free_slot,
                    "upload_speed": upload_speed,
                    "queue_length": queue_length,
                    "is_locked": f.get("isLocked", False),
                })

        # Rank results:
        # 1. Peer has open upload slot (True before False)
        # 2. Lowest queue length
        # 3. Highest upload speed
        results.sort(
            key=lambda r: (
                not r["has_free_upload_slot"],
                r["queue_length"],
                -r["upload_speed"],
            )
        )

        return results[:max_results]

    # -------------------------------------------------------------------------
    # Transfers (Downloads & Uploads)
    # -------------------------------------------------------------------------

    async def enqueue_download(
        self,
        username: str,
        filename: str,
        size: int = 0,
    ) -> Dict[str, Any]:
        """Enqueue a file from a specific user for download."""
        payload = [
            {
                "filename": filename,
                "size": int(size),
            }
        ]
        resp = await self.request(
            "POST",
            f"/api/v0/transfers/downloads/{username}",
            json=payload,
        )

        if resp.status_code in (200, 201, 204):
            return {
                "success": True,
                "username": username,
                "filename": filename,
                "size": size,
                "status": "queued",
                "message": "File successfully enqueued for download",
            }

        error_detail = resp.text
        return {
            "success": False,
            "username": username,
            "filename": filename,
            "size": size,
            "status": "error",
            "message": f"Failed to enqueue download ({resp.status_code}): {error_detail}",
        }

    async def get_transfers(self, direction: str = "downloads") -> List[Dict[str, Any]]:
        """List active or queued downloads or uploads."""
        normalized_dir = direction.lower().strip()
        if normalized_dir in ("download", "downloads"):
            endpoint = "/api/v0/transfers/downloads"
            default_dir = "Download"
        elif normalized_dir in ("upload", "uploads"):
            endpoint = "/api/v0/transfers/uploads"
            default_dir = "Upload"
        else:
            raise ValueError(f"Invalid transfer direction '{direction}'. Must be 'downloads' or 'uploads'.")

        resp = await self.request("GET", endpoint)
        resp.raise_for_status()

        flat_transfers: List[Dict[str, Any]] = []
        for peer in resp.json():
            user = peer.get("username", "")
            for directory in peer.get("directories", []):
                for f in directory.get("files", []):
                    flat_transfers.append({
                        "id": f.get("id", ""),
                        "username": f.get("username", user),
                        "direction": f.get("direction", default_dir),
                        "filename": f.get("filename", ""),
                        "size": f.get("size", 0),
                        "state": f.get("state", "Unknown"),
                        "percent_complete": float(f.get("percentComplete", 0.0)),
                        "bytes_transferred": f.get("bytesTransferred", 0),
                        "bytes_remaining": f.get("bytesRemaining", 0),
                        "average_speed": float(f.get("averageSpeed", 0.0)),
                        "elapsed_time": f.get("elapsedTime"),
                        "remaining_time": f.get("remainingTime"),
                    })

        return flat_transfers

    async def cancel_download(self, username: str, transfer_id: str) -> Dict[str, Any]:
        """Cancel or remove a download transfer."""
        resp = await self.request(
            "DELETE",
            f"/api/v0/transfers/downloads/{username}/{transfer_id}",
        )

        if resp.status_code in (200, 204):
            return {
                "success": True,
                "username": username,
                "id": transfer_id,
                "message": "Transfer successfully removed or canceled",
            }

        return {
            "success": False,
            "username": username,
            "id": transfer_id,
            "message": f"Failed to cancel transfer ({resp.status_code}): {resp.text}",
        }

    # -------------------------------------------------------------------------
    # Browse
    # -------------------------------------------------------------------------

    async def browse_user(
        self,
        username: str,
        directory: Optional[str] = None,
    ) -> Any:
        """Browse a peer's shared directories or inspect a specific directory."""
        if directory:
            # Specific directory request
            payload = {"directory": directory}
            resp = await self.request(
                "POST",
                f"/api/v0/users/{username}/directory",
                json=payload,
                timeout=20.0,
            )
            if resp.status_code == 200:
                return resp.json()
            return {
                "error": f"Failed to retrieve directory contents ({resp.status_code}): {resp.text}",
                "username": username,
                "directory": directory,
            }

        # Full library browse over Soulseek P2P
        try:
            resp = await self.request(
                "GET",
                f"/api/v0/users/{username}/browse",
                timeout=25.0,
            )
            if resp.status_code == 200:
                return resp.json()
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning("Full browse request for %s timed out or failed: %s", username, exc)

        # Fallback to user status & info when full browse is slow or not cached
        info_resp = await self.request("GET", f"/api/v0/users/{username}/info")
        status_resp = await self.request("GET", f"/api/v0/users/{username}/status")

        peer_info = info_resp.json() if info_resp.status_code == 200 else {}
        peer_status = status_resp.json() if status_resp.status_code == 200 else {}

        return {
            "username": username,
            "status": peer_status.get("presence", "Unknown"),
            "has_free_upload_slot": peer_info.get("hasFreeUploadSlot", False),
            "queue_length": peer_info.get("queueLength", 0),
            "description": peer_info.get("description", ""),
            "notice": (
                "Full library browse timed out over P2P network. "
                "Specify a directory path in 'directory' parameter to retrieve files inside that folder."
            ),
        }
