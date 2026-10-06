"""Asynchronous HTTP client for interacting with slskd daemon API."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from .config import Settings, settings as default_settings
from .models import RejectedPeer

logger = logging.getLogger("slskd_mcp.client")


class SlskdClient:
    """Async client for slskd REST API with JWT auto-refresh and connection pooling."""

    def __init__(self, config: Optional[Settings] = None):
        self.config = config or default_settings
        self.base_url = self.config.url.rstrip("/")
        self.username = self.config.username
        self.password = self.password = self.config.password
        self.api_key = self.config.api_key
        self.timeout = self.config.timeout

        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None

        # In-memory cache for peers known to reject transfers or have inaccessible shares
        # Mapping: username -> RejectedPeer
        self._rejected_peers: Dict[str, RejectedPeer] = {}

    def _get_lock(self) -> asyncio.Lock:
        current_loop = asyncio.get_running_loop()
        if self._lock is None or self._client_loop != current_loop:
            self._lock = asyncio.Lock()
        return self._lock

    async def _get_client(self) -> httpx.AsyncClient:
        current_loop = asyncio.get_running_loop()
        if (
            self._client is None
            or self._client.is_closed
            or self._client_loop != current_loop
        ):
            if self._client and not self._client.is_closed:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
            )
            self._client_loop = current_loop
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
            return

        now = time.time()
        if not force and self._token and now < (self._token_expires - 60):
            return

        lock = self._get_lock()
        async with lock:
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
    # Rejection Cache Helpers
    # -------------------------------------------------------------------------

    def record_rejected_peer(self, username: str, reason: str, ttl_seconds: float = 3600.0) -> None:
        """Record a peer that rejected transfers or has locked/inaccessible files."""
        now = time.time()
        self._rejected_peers[username] = RejectedPeer(
            username=username,
            reason=reason,
            recorded_at=now,
            expires_at=now + ttl_seconds,
        )
        logger.info("Recorded rejected peer '%s': %s (TTL: %ds)", username, reason, int(ttl_seconds))

    def is_peer_rejected(self, username: str) -> bool:
        """Check if a peer is in the rejected peers cache and still within TTL."""
        entry = self._rejected_peers.get(username)
        if not entry:
            return False
        if time.time() > entry.expires_at:
            del self._rejected_peers[username]
            return False
        return True

    def get_rejected_peers(self) -> List[Dict[str, Any]]:
        """Return currently active rejected peers."""
        now = time.time()
        active = {}
        for u, entry in list(self._rejected_peers.items()):
            if now <= entry.expires_at:
                active[u] = entry.dict()
            else:
                del self._rejected_peers[u]
        return list(active.values())

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
        exclude_locked: bool = True,
        max_queue_length: Optional[int] = 500,
    ) -> List[Dict[str, Any]]:
        """Search Soulseek network, poll until responses arrive or timeout, rank & filter results."""
        # Also refresh rejected peers from active transfer history first
        try:
            await self.get_transfers("downloads")
        except Exception:
            pass

        search_id = await self.initiate_search(query, timeout_seconds=timeout_seconds)
        start_time = time.time()
        max_wait = max(5, int(timeout_seconds)) + 5

        responses: List[Dict[str, Any]] = []
        try:
            while (time.time() - start_time) < max_wait:
                await asyncio.sleep(1.0)
                state_data = await self.get_search_state(search_id)
                is_complete = state_data.get("isComplete", False)
                response_count = state_data.get("responseCount", 0)

                if is_complete or ((time.time() - start_time) >= timeout_seconds and response_count > 0):
                    break

            resp_wait_start = time.time()
            while (time.time() - resp_wait_start) < 10.0:
                responses = await self.get_search_responses(search_id)
                if responses:
                    break
                await asyncio.sleep(1.0)
        finally:
            asyncio.create_task(self.delete_search(search_id))

        results: List[Dict[str, Any]] = []
        ext_clean = format_filter.lower().lstrip(".") if format_filter else None

        for resp in responses:
            username = resp.get("username", "")
            has_free_slot = resp.get("hasFreeUploadSlot", False)
            upload_speed = resp.get("uploadSpeed", 0)
            queue_length = resp.get("queueLength", 0)

            # Filter by queue length if threshold specified
            if max_queue_length is not None and queue_length > max_queue_length:
                continue

            is_rejected = self.is_peer_rejected(username)
            if exclude_locked and is_rejected:
                continue

            for f in resp.get("files", []):
                filename = f.get("filename", "")
                if not filename:
                    continue

                size = f.get("size", 0)
                if size <= 0:
                    continue

                is_file_locked = bool(f.get("isLocked") or f.get("locked", False))
                if exclude_locked and is_file_locked:
                    continue

                if ext_clean and not filename.lower().endswith(f".{ext_clean}"):
                    continue

                bitrate = f.get("bitRate")
                if min_bitrate > 0 and bitrate is not None and bitrate > 0 and bitrate < min_bitrate:
                    continue

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
                    "is_locked": is_file_locked,
                    "is_rejected_peer": is_rejected,
                })

        # Smart ranking:
        # 1. Non-rejected peers first
        # 2. Non-locked files first
        # 3. Peer has open upload slot (True before False)
        # 4. Lowest queue length
        # 5. Highest upload speed
        results.sort(
            key=lambda r: (
                r["is_rejected_peer"],
                r["is_locked"],
                not r["has_free_upload_slot"],
                r["queue_length"],
                -r["upload_speed"],
            )
        )

        return results[:max_results]

    # -------------------------------------------------------------------------
    # Transfers & Downloads
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

    async def download_directory(
        self,
        username: str,
        directory: str,
        format_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download an entire directory / album from a peer in a single batch request."""
        # 1. Inspect directory files
        dir_res = await self.browse_user(username=username, directory=directory)
        if isinstance(dir_res, dict) and "error" in dir_res:
            return {
                "success": False,
                "username": username,
                "directory": directory,
                "files_enqueued": 0,
                "total_size_mb": 0.0,
                "files": [],
                "message": dir_res["error"],
            }

        file_list: List[Dict[str, Any]] = []
        if isinstance(dir_res, list) and dir_res:
            target_dir = dir_res[0]
            dir_name = target_dir.get("name", directory)
            raw_files = target_dir.get("files", [])
            ext_clean = format_filter.lower().lstrip(".") if format_filter else None

            for rf in raw_files:
                fn = rf.get("filename", "")
                if not fn:
                    continue
                if ext_clean and not fn.lower().endswith(f".{ext_clean}"):
                    continue
                sz = rf.get("size", 0)
                # Combine directory and filename if not already included
                full_fn = fn if ("\\" in fn or "/" in fn) else f"{dir_name}\\{fn}"
                file_list.append({"filename": full_fn, "size": sz})

        if not file_list:
            return {
                "success": False,
                "username": username,
                "directory": directory,
                "files_enqueued": 0,
                "total_size_mb": 0.0,
                "files": [],
                "message": "No matching files found in the specified directory",
            }

        # 2. Enqueue all files in one batch request
        resp = await self.request(
            "POST",
            f"/api/v0/transfers/downloads/{username}",
            json=file_list,
        )

        total_bytes = sum(f["size"] for f in file_list)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        filenames = [f["filename"] for f in file_list]

        if resp.status_code in (200, 201, 204):
            return {
                "success": True,
                "username": username,
                "directory": directory,
                "files_enqueued": len(file_list),
                "total_size_mb": total_mb,
                "files": filenames,
                "message": f"Successfully enqueued {len(file_list)} files ({total_mb} MB) from '{directory}'",
            }

        return {
            "success": False,
            "username": username,
            "directory": directory,
            "files_enqueued": 0,
            "total_size_mb": total_mb,
            "files": filenames,
            "message": f"Failed to enqueue directory download ({resp.status_code}): {resp.text}",
        }

    async def get_transfers(self, direction: str = "downloads") -> List[Dict[str, Any]]:
        """List active or queued downloads or uploads and update rejection cache."""
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
                    st = f.get("state", "Unknown")
                    exc = f.get("exception")

                    # If download rejected / file not shared, record peer in rejection cache
                    if normalized_dir in ("download", "downloads") and (
                        "Rejected" in st or "Errored" in st or (exc and "not shared" in exc.lower())
                    ):
                        reason = exc or st
                        self.record_rejected_peer(user, reason)

                    flat_transfers.append({
                        "id": f.get("id", ""),
                        "username": f.get("username", user),
                        "direction": f.get("direction", default_dir),
                        "filename": f.get("filename", ""),
                        "size": f.get("size", 0),
                        "state": st,
                        "percent_complete": float(f.get("percentComplete", 0.0)),
                        "bytes_transferred": f.get("bytesTransferred", 0),
                        "bytes_remaining": f.get("bytesRemaining", 0),
                        "average_speed": float(f.get("averageSpeed", 0.0)),
                        "elapsed_time": f.get("elapsedTime"),
                        "remaining_time": f.get("remainingTime"),
                        "exception": exc,
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

    async def clear_completed_transfers(self, direction: str = "downloads") -> Dict[str, Any]:
        """Clear all completed or failed transfers from the download/upload history."""
        normalized_dir = direction.lower().strip()
        endpoint = "/api/v0/transfers/downloads/all/completed" if normalized_dir in ("download", "downloads") else "/api/v0/transfers/uploads/all/completed"
        resp = await self.request("DELETE", endpoint)
        if resp.status_code in (200, 204):
            return {
                "success": True,
                "direction": normalized_dir,
                "message": f"Successfully cleared all completed {normalized_dir}",
            }
        return {
            "success": False,
            "direction": normalized_dir,
            "message": f"Failed to clear completed transfers ({resp.status_code}): {resp.text}",
        }

    # -------------------------------------------------------------------------
    # Browse & Users
    # -------------------------------------------------------------------------

    async def browse_user(
        self,
        username: str,
        directory: Optional[str] = None,
    ) -> Any:
        """Browse a peer's shared directories or inspect a specific directory."""
        if directory:
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

    async def get_user_info(self, username: str) -> Dict[str, Any]:
        """Fetch presence status, bio, and upload queue metrics for a Soulseek peer."""
        info_resp = await self.request("GET", f"/api/v0/users/{username}/info")
        status_resp = await self.request("GET", f"/api/v0/users/{username}/status")

        peer_info = info_resp.json() if info_resp.status_code == 200 else {}
        peer_status = status_resp.json() if status_resp.status_code == 200 else {}

        return {
            "username": username,
            "presence": peer_status.get("presence", "Offline"),
            "description": peer_info.get("description"),
            "has_free_upload_slot": peer_info.get("hasFreeUploadSlot", False),
            "queue_length": peer_info.get("queueLength", 0),
            "upload_slots": peer_info.get("uploadSlots", 0),
            "is_privileged": peer_status.get("isPrivileged", False),
        }

    async def get_me(self) -> Dict[str, Any]:
        """Fetch detailed information about our own configured Soulseek account."""
        app_info = await self.get_application()
        srv_info = await self.get_server()

        user_info = app_info.get("user") or {}
        user_stats = user_info.get("statistics") or {}
        privileges = user_info.get("privileges") or {}

        return {
            "username": user_info.get("username", srv_info.get("username", "")),
            "is_connected": srv_info.get("isConnected", False),
            "is_logged_in": srv_info.get("isLoggedIn", False),
            "is_privileged": privileges.get("isPrivileged", False),
            "privileges_remaining": privileges.get("privilegesRemaining", 0),
            "average_speed": float(user_stats.get("averageSpeed", 0.0)),
            "directory_count": int(user_stats.get("directoryCount", 0)),
            "file_count": int(user_stats.get("fileCount", 0)),
            "upload_count": int(user_stats.get("uploadCount", 0)),
        }

    # -------------------------------------------------------------------------
    # Shares Management
    # -------------------------------------------------------------------------

    async def get_shares(self) -> Dict[str, Any]:
        """Fetch local shared music library directories and indexing status."""
        shares_resp = await self.request("GET", "/api/v0/shares")
        app_resp = await self.request("GET", "/api/v0/application")

        shares_data = shares_resp.json() if shares_resp.status_code == 200 else {}
        app_data = app_resp.json() if app_resp.status_code == 200 else {}
        shares_meta = app_data.get("shares") or {}

        local_shares = shares_data.get("local", [])
        return {
            "is_scanning": shares_meta.get("scanning", False),
            "scan_progress": float(shares_meta.get("scanProgress", 1.0)),
            "directories_count": shares_meta.get("directories", 0),
            "files_count": shares_meta.get("files", 0),
            "shares": local_shares,
        }

    async def rescan_shares(self) -> Dict[str, Any]:
        """Trigger an immediate re-scan and indexing of local shared music folders."""
        resp = await self.request("PUT", "/api/v0/shares")
        if resp.status_code in (200, 202, 204):
            return {
                "success": True,
                "message": "Local shares re-scan successfully triggered and started in background",
            }
        return {
            "success": False,
            "message": f"Failed to start shares re-scan ({resp.status_code}): {resp.text}",
        }
