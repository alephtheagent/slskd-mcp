# slskd-mcp

A production-ready [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for [slskd](https://github.com/slskd/slskd) (the modern Soulseek client daemon).

`slskd-mcp` allows AI agents (such as Hermes Agent, Claude, etc.) to interact with the Soulseek P2P music sharing network directly: searching for artists, releases, and tracks, filtering by format and bitrate, managing downloads, monitoring active transfers, and browsing peer libraries.

---

## Features

- **Soulseek Health & Status**: Monitor Soulseek daemon connection, login status, server address, peer stats, and shared library size.
- **P2P Search & Smart Ranking**: Search the global Soulseek network. Results are automatically ranked prioritizing peers with free upload slots, lowest queue lengths, and highest transfer speeds.
- **Format & Quality Filtering**: Filter results by audio format (`flac`, `mp3`, `ogg`, `wav`, etc.) and minimum bitrate (e.g. `320` kbps).
- **Download Management**: Enqueue releases or tracks directly into the slskd download directory.
- **Real-Time Transfer Tracking**: Monitor live progress, download/upload speeds, percent complete, remaining bytes, and ETAs.
- **Peer Library Browsing**: Browse directories and examine shared music collections of specific Soulseek users.
- **Resilient Auth & Session Handling**: Native JWT authentication with automatic token caching and seamless re-authentication on expiration (`401 Unauthorized`), plus optional static API key support.
- **Zero-Port stdio Transport**: Communicates via standard I/O streams using FastMCP for secure, local agent integration.

---

## Requirements

- Python 3.10+ (tested up to Python 3.14)
- A running [slskd](https://github.com/slskd/slskd) daemon with API enabled (default: `http://127.0.0.1:5030`)

---

## Installation

### Option 1: Using `uv` (Recommended)

```bash
git clone https://github.com/alephtheagent/slskd-mcp.git
cd slskd-mcp
uv venv venv
uv pip install -e .
```

### Option 2: Standard Python `venv`

```bash
git clone https://github.com/alephtheagent/slskd-mcp.git
cd slskd-mcp
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

---

## Configuration

The server is configured via environment variables (or a local `.env` file). All variables use the `SLSKD_` prefix:

| Environment Variable | Default Value | Description |
|----------------------|---------------|-------------|
| `SLSKD_URL` | `http://127.0.0.1:5030` | Base URL of the slskd daemon |
| `SLSKD_USERNAME` | `slskd` | slskd Web UI / API username |
| `SLSKD_PASSWORD` | `slskd` | slskd Web UI / API password |
| `SLSKD_API_KEY` | *(None)* | Optional static API key (`X-API-Key` header) |
| `SLSKD_TIMEOUT` | `30.0` | Default HTTP request timeout (seconds) |
| `SLSKD_SEARCH_TIMEOUT`| `15` | Default duration for search network polling (seconds) |

---

## Tool Reference

### 1. `slskd_status`
Check slskd connection to Soulseek, connected peers, and transfer stats.

- **Parameters**: None
- **Returns**:
  ```json
  {
    "connected": true,
    "logged_in": true,
    "username": "polymatic",
    "version": "0.26.0.0",
    "upload_speed": 8737820.0,
    "download_speed": 0.0,
    "peer_count": 0,
    "shares_directories": 18,
    "shares_files": 266,
    "server_address": "208.76.170.59:2242"
  }
  ```

---

### 2. `slskd_search`
Search the Soulseek network for music files, albums, or artists. Polls until responses arrive or timeout expires, then ranks and filters the results.

- **Parameters**:
  - `query` (`str`, required): Search string (e.g. `"Aphex Twin Selected Ambient Works"` or `"Sewerslvt"`).
  - `timeout_seconds` (`int`, optional, default: `15`): Search duration (minimum 5s).
  - `max_results` (`int`, optional, default: `50`): Maximum ranked results to return.
  - `format_filter` (`str`, optional): File extension filter (e.g. `"flac"`, `"mp3"`).
  - `min_bitrate` (`int`, optional, default: `0`): Minimum bitrate threshold in kbps (e.g. `320`). Lossless audio (FLAC/WAV) is preserved.
  - `exclude_locked` (`bool`, optional, default: `True`): Automatically exclude password-locked files and peers with closed/rejected transfers.
  - `max_queue_length` (`int`, optional, default: `500`): Exclude peers whose queue exceeds this threshold. Set `None` to disable.
- **Returns**: List of ranked file entries:
  ```json
  [
    {
      "user": "plexusnexus",
      "filename": "share\\Aphex Twin FLAC\\1991 - Analogue Bubblebath 2\\01. Digeridoo.flac",
      "size": 52758120,
      "size_mb": 50.31,
      "bitrate": null,
      "has_free_upload_slot": true,
      "upload_speed": 9850632,
      "queue_length": 0,
      "is_locked": false
    }
  ]
  ```

---

### 3. `slskd_download`
Enqueue a file from a specific user for download.

- **Parameters**:
  - `username` (`str`, required): The Soulseek peer holding the file.
  - `filename` (`str`, required): Remote file path as returned by search or browse.
  - `size` (`int`, optional, default: `0`): File size in bytes.
- **Returns**:
  ```json
  {
    "success": true,
    "username": "plexusnexus",
    "filename": "share\\Aphex Twin FLAC\\1991 - Analogue Bubblebath 2\\01. Digeridoo.flac",
    "size": 52758120,
    "status": "queued",
    "message": "File successfully enqueued for download"
  }
  ```

---

### 4. `slskd_get_transfers`
List current downloads or uploads with speeds, bytes transferred, queue position, and status.

- **Parameters**:
  - `direction` (`str`, optional, default: `"downloads"`): Either `"downloads"` or `"uploads"`.
- **Returns**:
  ```json
  [
    {
      "id": "d7673046-70e9-4092-82f5-51739790754c",
      "username": "deathalchemy",
      "direction": "Download",
      "filename": "music\\Linkin Park\\Hybrid Theory (2000)\\01 - Papercut.flac",
      "size": 45082764,
      "state": "Completed, Succeeded",
      "percent_complete": 100.0,
      "bytes_transferred": 45082764,
      "bytes_remaining": 0,
      "average_speed": 293394.51,
      "elapsed_time": "00:02:33.6591936",
      "remaining_time": "00:00:00"
    }
  ]
  ```

---

### 5. `slskd_cancel_download`
Cancel or remove an active/queued transfer.

- **Parameters**:
  - `username` (`str`, required): Soulseek peer username.
  - `id` (`str`, required): Transfer ID (from `slskd_get_transfers`).
- **Returns**:
  ```json
  {
    "success": true,
    "username": "deathalchemy",
    "id": "d7673046-70e9-4092-82f5-51739790754c",
    "message": "Transfer successfully removed or canceled"
  }
  ```

---

### 6. `slskd_browse_user`
Browse shared directory structure of a Soulseek peer.

- **Parameters**:
  - `username` (`str`, required): Peer username.
  - `directory` (`str`, optional): Specific remote directory path to list. If omitted, queries the peer's root library or returns share availability.
- **Returns**: Directory listing containing files, sizes, bitrates, and track lengths.

---

### 7. `slskd_download_directory`
Download an entire album or directory from a peer in a single batch request.

- **Parameters**:
  - `username` (`str`, required): Peer username.
  - `directory` (`str`, required): Remote directory path as shared by the peer.
  - `format_filter` (`str`, optional): Extension filter (e.g. `"flac"`, `"mp3"`).

---

### 8. `slskd_clear_transfers`
Clear all completed, succeeded, or failed transfers from the download or upload transfer lists.

- **Parameters**:
  - `direction` (`str`, optional, default: `"downloads"`): `"downloads"` or `"uploads"`.

---

### 9. `slskd_get_me`
Get detailed metrics and statistics for our own Soulseek account (`polymatic`).

---

### 10. `slskd_get_user_info`
Fetch presence status, profile bio, free upload slots, and queue length for any Soulseek peer.

- **Parameters**:
  - `username` (`str`, required): Peer username.

---

### 11. `slskd_get_shares` & `slskd_rescan_shares`
Inspect local shared folders (`/var/music/flac/main`, etc.) and trigger background library re-indexing.

---

## Hermes Agent Integration

To register `slskd-mcp` with **Hermes Agent**:

```bash
echo "y" | hermes mcp add slskd-mcp \
  --command /home/aleph/slskd-mcp/venv/bin/python \
  --args /home/aleph/slskd-mcp/main.py
```

If slskd runs on a custom URL or credentials, pass `--env` before `--args`:

```bash
echo "y" | hermes mcp add slskd-mcp \
  --command /home/aleph/slskd-mcp/venv/bin/python \
  --env SLSKD_URL=http://127.0.0.1:5030 \
  --env SLSKD_USERNAME=slskd \
  --env SLSKD_PASSWORD=slskd \
  --args /home/aleph/slskd-mcp/main.py
```

Verify connection:

```bash
hermes mcp test slskd-mcp
hermes mcp list
```

---

## Claude Desktop Integration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "slskd": {
      "command": "/path/to/slskd-mcp/venv/bin/python",
      "args": ["/path/to/slskd-mcp/main.py"],
      "env": {
        "SLSKD_URL": "http://127.0.0.1:5030",
        "SLSKD_USERNAME": "slskd",
        "SLSKD_PASSWORD": "slskd"
      }
    }
  }
}
```

---

## Testing

Run the test suite against a live or local slskd daemon:

```bash
./venv/bin/pytest tests/
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
