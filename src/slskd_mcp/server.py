"""FastMCP server definition and tool registration for slskd."""

import logging
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

from .client import SlskdClient
from .config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("slskd_mcp.server")

# Initialize FastMCP server
mcp = FastMCP(
    "slskd-mcp",
    instructions=(
        "Model Context Protocol server for slskd (Soulseek daemon). "
        "Allows searching the Soulseek P2P network for music releases, tracks, and discographies, "
        "filtering by format/bitrate, excluding locked/inaccessible files, enqueuing single files or "
        "entire directories/albums in batch, tracking transfer progress, managing local shares, "
        "and inspecting peer and local account profiles."
    ),
)

# Shared client instance
client = SlskdClient(config=settings)


@mcp.tool()
async def slskd_status() -> Dict[str, Any]:
    """Check slskd connection to Soulseek, connected peers, and transfer stats.

    Returns:
        Summary object containing:
            connected: Soulseek server connection state (boolean)
            logged_in: Soulseek login state (boolean)
            username: Logged-in Soulseek username
            version: slskd daemon version string
            upload_speed: Average upload speed (bytes/sec)
            download_speed: Current download speed (bytes/sec)
            peer_count: Number of connected peers
            shares_directories: Shared directory count
            shares_files: Shared file count
            server_address: Soulseek server IP and port
    """
    try:
        return await client.get_status()
    except Exception as exc:
        logger.error("slskd_status failed: %s", exc)
        return {
            "connected": False,
            "logged_in": False,
            "error": str(exc),
        }


@mcp.tool()
async def slskd_search(
    query: str,
    timeout_seconds: int = 15,
    max_results: int = 50,
    format_filter: Optional[str] = None,
    min_bitrate: int = 0,
    exclude_locked: bool = True,
    max_queue_length: Optional[int] = 500,
) -> List[Dict[str, Any]]:
    """Search the Soulseek network for music files, albums, or artists.

    Polls until responses arrive or timeout expires. Filters and ranks matches
    prioritizing peers with open upload slots, shorter queues, and higher speeds,
    while automatically excluding locked files and peers known to reject transfers.

    Args:
        query: Search string (e.g. 'Aphex Twin Selected Ambient Works' or 'Renard').
        timeout_seconds: Search duration in seconds (default: 15, minimum: 5).
        max_results: Maximum number of ranked file results to return (default: 50).
        format_filter: Optional file extension filter (e.g. 'flac', 'mp3', 'wav').
        min_bitrate: Minimum bitrate in kbps for audio files (e.g. 320). Lossless files are preserved.
        exclude_locked: Automatically exclude password-locked files and peers with closed/rejected transfers (default: True).
        max_queue_length: Filter out peers whose upload queue exceeds this number (default: 500). Set None to disable.

    Returns:
        List of ranked file results with peer username, filename, size_mb, bitrate,
        has_free_upload_slot, upload_speed, queue_length, and lock status.
    """
    try:
        return await client.search(
            query=query,
            timeout_seconds=timeout_seconds,
            max_results=max_results,
            format_filter=format_filter,
            min_bitrate=min_bitrate,
            exclude_locked=exclude_locked,
            max_queue_length=max_queue_length,
        )
    except Exception as exc:
        logger.error("slskd_search failed: %s", exc)
        return [{"error": f"Search failed: {exc}", "query": query}]


@mcp.tool()
async def slskd_download(
    username: str,
    filename: str,
    size: int = 0,
) -> Dict[str, Any]:
    """Enqueue a single file from a specific user for download.

    Args:
        username: The Soulseek peer's username holding the file.
        filename: The exact remote file path as returned by search or browse.
        size: File size in bytes (optional but recommended, from search results).

    Returns:
        Status object confirming download queuing or error message.
    """
    try:
        return await client.enqueue_download(username=username, filename=filename, size=size)
    except Exception as exc:
        logger.error("slskd_download failed: %s", exc)
        return {
            "success": False,
            "username": username,
            "filename": filename,
            "status": "error",
            "message": str(exc),
        }


@mcp.tool()
async def slskd_download_directory(
    username: str,
    directory: str,
    format_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Download an entire folder / album from a peer in a single batch request.

    Inspects the remote directory contents and enqueues all matching files at once.

    Args:
        username: Soulseek peer username.
        directory: Full remote directory path as shared by the peer (e.g. 'Music\\\\Artist\\\\Album').
        format_filter: Optional file extension filter (e.g. 'flac' or 'mp3') to only enqueue audio files.

    Returns:
        Summary object containing files_enqueued count, total_size_mb, and file list.
    """
    try:
        return await client.download_directory(
            username=username,
            directory=directory,
            format_filter=format_filter,
        )
    except Exception as exc:
        logger.error("slskd_download_directory failed: %s", exc)
        return {
            "success": False,
            "username": username,
            "directory": directory,
            "files_enqueued": 0,
            "total_size_mb": 0.0,
            "message": str(exc),
        }


@mcp.tool()
async def slskd_get_transfers(
    direction: str = "downloads",
) -> List[Dict[str, Any]]:
    """List current downloads or uploads with speeds, bytes transferred, queue position, and status.

    Args:
        direction: Transfer direction to query, either 'downloads' (default) or 'uploads'.

    Returns:
        List of transfer items containing id, username, filename, size, state,
        percent_complete, bytes_transferred, average_speed, remaining_time, and error exception.
    """
    try:
        return await client.get_transfers(direction=direction)
    except Exception as exc:
        logger.error("slskd_get_transfers failed: %s", exc)
        return [{"error": f"Failed to retrieve transfers: {exc}", "direction": direction}]


@mcp.tool()
async def slskd_cancel_download(
    username: str,
    id: str,
) -> Dict[str, Any]:
    """Cancel or remove an active/queued transfer.

    Args:
        username: Soulseek peer username associated with the transfer.
        id: Transfer ID (as returned by slskd_get_transfers).

    Returns:
        Result object confirming transfer removal.
    """
    try:
        return await client.cancel_download(username=username, transfer_id=id)
    except Exception as exc:
        logger.error("slskd_cancel_download failed: %s", exc)
        return {
            "success": False,
            "username": username,
            "id": id,
            "message": str(exc),
        }


@mcp.tool()
async def slskd_clear_transfers(
    direction: str = "downloads",
) -> Dict[str, Any]:
    """Clear all completed, succeeded, or failed transfers from the transfer history.

    Args:
        direction: Which transfer list to clear: 'downloads' (default) or 'uploads'.

    Returns:
        Confirmation status message.
    """
    try:
        return await client.clear_completed_transfers(direction=direction)
    except Exception as exc:
        logger.error("slskd_clear_transfers failed: %s", exc)
        return {
            "success": False,
            "direction": direction,
            "message": str(exc),
        }


@mcp.tool()
async def slskd_browse_user(
    username: str,
    directory: Optional[str] = None,
) -> Any:
    """Browse shared directory structure of a Soulseek peer.

    Args:
        username: Soulseek peer username.
        directory: Optional specific directory path to list (e.g. 'music\\\\AlbumName').
                   If omitted, attempts full peer library browse or returns peer share info.

    Returns:
        List of files and subdirectories, or user sharing status and queue information.
    """
    try:
        return await client.browse_user(username=username, directory=directory)
    except Exception as exc:
        logger.error("slskd_browse_user failed: %s", exc)
        return {
            "error": f"Browse failed: {exc}",
            "username": username,
            "directory": directory,
        }


@mcp.tool()
async def slskd_get_user_info(
    username: str,
) -> Dict[str, Any]:
    """Fetch profile bio, online presence, upload slots, and queue length for any Soulseek peer.

    Args:
        username: Soulseek username of the peer.

    Returns:
        Object containing presence ('Online'/'Offline'), description, has_free_upload_slot,
        queue_length, upload_slots, and is_privileged.
    """
    try:
        return await client.get_user_info(username=username)
    except Exception as exc:
        logger.error("slskd_get_user_info failed: %s", exc)
        return {
            "username": username,
            "presence": "Unknown",
            "error": str(exc),
        }


@mcp.tool()
async def slskd_get_me() -> Dict[str, Any]:
    """Get detailed account metrics, upload counts, speeds, and share counts for our own Soulseek account.

    Returns:
        Object containing username, connection status, supporter privileges, average upload speed,
        shared directory count, shared file count, and total upload count.
    """
    try:
        return await client.get_me()
    except Exception as exc:
        logger.error("slskd_get_me failed: %s", exc)
        return {
            "username": "unknown",
            "is_connected": False,
            "error": str(exc),
        }


@mcp.tool()
async def slskd_get_shares() -> Dict[str, Any]:
    """List our locally configured shared music folders, file counts, and library scan status.

    Returns:
        Object containing is_scanning (bool), scan_progress (float), directories_count,
        files_count, and list of shared folder roots.
    """
    try:
        return await client.get_shares()
    except Exception as exc:
        logger.error("slskd_get_shares failed: %s", exc)
        return {
            "is_scanning": False,
            "error": str(exc),
        }


@mcp.tool()
async def slskd_rescan_shares() -> Dict[str, Any]:
    """Trigger an immediate background re-scan and indexing of all local shared music libraries.

    Use when new music files have been added to the disk and need to be shared with the network.

    Returns:
        Confirmation status message.
    """
    try:
        return await client.rescan_shares()
    except Exception as exc:
        logger.error("slskd_rescan_shares failed: %s", exc)
        return {
            "success": False,
            "message": str(exc),
        }


@mcp.tool()
async def slskd_get_rejected_peers() -> List[Dict[str, Any]]:
    """List peers currently in the rejection cache (peers that refused downloads or closed shares).

    Returns:
        List of objects containing username, rejection reason, and expiration timestamps.
    """
    try:
        return client.get_rejected_peers()
    except Exception as exc:
        logger.error("slskd_get_rejected_peers failed: %s", exc)
        return []


def main():
    """Run FastMCP server over standard I/O transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
