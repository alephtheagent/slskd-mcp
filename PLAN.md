# SLSKD MCP Server — Architecture & Implementation Plan

## 1. Overview & Goals
Build a lightweight, production-ready Model Context Protocol (MCP) server for **slskd** (modern Soulseek daemon).
The server will allow AI agents (Hermes Agent, Claude, etc.) to:
1. Check Soulseek network connection & server health.
2. Search for music releases, tracks, and discographies across the Soulseek P2P network.
3. Filter & rank search results by bitrate, format (FLAC/MP3), user speed, and queue length.
4. Enqueue downloads directly to the server's music repository.
5. Monitor real-time transfer progress (speeds, ETA, queue positions, stuck downloads).
6. Browse shared folders of specific Soulseek peers.

---

## 2. Target Environment & slskd API
- **Target Daemon:** `slskd` running locally on `http://127.0.0.1:5030` (or configurable via env `SLSKD_URL`).
- **Auth Strategy:**
  - Endpoint: `POST /api/v0/session`
  - Credentials: `username: "slskd"`, `password: "slskd"` (configurable via env `SLSKD_USERNAME`, `SLSKD_PASSWORD`).
  - Response: JWT Bearer token with expiration (`expires` Unix timestamp).
  - Also support optional static `SLSKD_API_KEY` via `X-API-Key` header.
  - Client must maintain cached JWT and automatically refresh it when expired or upon receiving `401 Unauthorized`.

### Key slskd Endpoints to Wrap:
* `GET /api/v0/application` — Daemon version, server status, health metrics.
* `GET /api/v0/server` — Soulseek login status, peer count, connection state.
* `POST /api/v0/searches` — Initiate search (`{"searchText": query, "searchTimeout": timeout_ms}`).
  * *Note:* `searchTimeout` in current slskd is in milliseconds (e.g. `15000` for 15s).
* `GET /api/v0/searches/{id}` — Poll search status (`InProgress`, `Completed`).
* `GET /api/v0/searches/{id}/responses` — Retrieve list of peer responses and matched files.
* `POST /api/v0/transfers/downloads/{username}` — Enqueue files for download.
* `GET /api/v0/transfers/downloads` — Active and queued downloads with speed/progress.
* `DELETE /api/v0/transfers/downloads/{username}/{id}` — Cancel/abort a download.
* `GET /api/v0/users/{username}/directory` — Browse peer's shared directories.

---

## 3. Technology Stack
* **Language:** Python 3.11+ / 3.14.
* **MCP Framework:** `FastMCP` (fastmcp / mcp SDK).
* **HTTP Client:** `httpx` (async, keep-alive, connection pooling).
* **Config:** `pydantic-settings` (reads environment variables with prefix `SLSKD_`).
* **Transport:** `stdio` (standard JSON-RPC via stdin/stdout, zero port footprint).

---

## 4. Repository File Structure

```
slskd-mcp/
├── pyproject.toml              # Build & dependency metadata
├── README.md                   # Documentation, setup & tool list
├── PLAN.md                     # This specification
├── main.py                     # Entry point for stdio execution
└── src/
    └── slskd_mcp/
        ├── __init__.py         # Package export
        ├── config.py           # Settings (URL, credentials, defaults)
        ├── client.py           # Async SlskdClient (auth, retry, polling)
        ├── models.py           # Pydantic schemas for cleaner tool returns
        └── server.py           # FastMCP server & tool definitions
```

---

## 5. Tool Specifications

### `slskd_status()`
* **Description:** Check slskd connection to Soulseek, connected peers, and transfer stats.
* **Returns:** Summary object containing `connected`, `username`, `version`, `upload_speed`, `download_speed`, `peer_count`.

### `slskd_search(query: str, timeout_seconds: int = 15, max_results: int = 50, format_filter: str = None, min_bitrate: int = 0)`
* **Description:** Search the Soulseek network for music files, albums, or artists. Polls until responses arrive or timeout expires.
* **Parameters:**
  * `query`: Search string (e.g., `"Sewerslvt Draining Love Story"`).
  * `timeout_seconds`: Search duration (default: 15s).
  * `max_results`: Maximum items to return (default: 50).
  * `format_filter`: Optional extension filter (e.g., `"flac"` or `"mp3"`).
  * `min_bitrate`: Filter out files below this bitrate (e.g., `320`).
* **Returns:** List of ranked results: `[{"user": "...", "filename": "...", "size_mb": 42.1, "bitrate": 320, "has_free_upload_slot": true, "upload_speed": 1048576}]`.

### `slskd_download(username: str, filename: str, size: int = 0)`
* **Description:** Enqueue a file from a specific user for download.
* **Returns:** Enqueue status (`queued`, `started`, or error message).

### `slskd_get_transfers(direction: str = "downloads")`
* **Description:** List current downloads or uploads with speeds, bytes transferred, queue position, and status.
* **Parameters:** `direction`: `"downloads"` (default) or `"uploads"`.

### `slskd_cancel_download(username: str, id: str)`
* **Description:** Cancel or remove a transfer.

### `slskd_browse_user(username: str)`
* **Description:** Browse shared directory structure of a Soulseek user.

---

## 6. Implementation Workflow for Autonomous Agent (`agy`)

1. **Venv & Dependencies:**
   * Create Python virtual environment: `python3 -m venv venv` or using `uv venv`.
   * Install `fastmcp`, `httpx`, `pydantic`, `pydantic-settings`.
2. **Implementation:**
   * Write `src/slskd_mcp/config.py` with environment variable loading.
   * Write `src/slskd_mcp/client.py` with robust authentication & session token caching.
   * Write `src/slskd_mcp/server.py` with FastMCP tool registrations.
   * Write `main.py` entrypoint.
3. **Smoke Verification:**
   * Run standalone test against live local `http://127.0.0.1:5030`.
   * Verify `slskd_status` returns online Soulseek connection.
   * Verify `slskd_search` receives live query responses.
4. **Git Operations:**
   * Configure commit author:
     ```bash
     git config user.name "Aleph the Agent"
     git config user.email "ilya2accpidor@gmail.com"
     ```
   * Write clean `README.md`.
   * Commit all files with descriptive messages.
   * Push to remote: `git push -u origin main`.
