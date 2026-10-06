"""Pydantic data models for slskd-mcp."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ServerStatus(BaseModel):
    """slskd and Soulseek server status overview."""

    connected: bool = Field(description="Soulseek server connection status")
    logged_in: bool = Field(description="Soulseek login status")
    username: str = Field(description="Logged in Soulseek username")
    version: str = Field(description="slskd daemon version")
    upload_speed: float = Field(default=0.0, description="Average upload speed in bytes/sec")
    download_speed: float = Field(default=0.0, description="Average download speed in bytes/sec")
    peer_count: int = Field(default=0, description="Active peer connections")
    shares_directories: int = Field(default=0, description="Number of shared directories")
    shares_files: int = Field(default=0, description="Number of shared files")
    server_address: str = Field(default="", description="Soulseek server address and port")


class SearchResultFile(BaseModel):
    """File match result returned from a Soulseek search."""

    user: str = Field(description="Username of the peer sharing the file")
    filename: str = Field(description="Full path of the file as shared by the peer")
    size: int = Field(description="File size in bytes")
    size_mb: float = Field(description="File size in megabytes")
    bitrate: Optional[int] = Field(default=None, description="Audio bitrate in kbps, if available")
    bit_depth: Optional[int] = Field(default=None, description="Audio bit depth, if available")
    sample_rate: Optional[int] = Field(default=None, description="Audio sample rate in Hz, if available")
    length: Optional[int] = Field(default=None, description="Audio duration in seconds, if available")
    has_free_upload_slot: bool = Field(default=False, description="Whether peer has an open upload slot")
    upload_speed: int = Field(default=0, description="Peer upload speed in bytes/sec")
    queue_length: int = Field(default=0, description="Peer download queue length")
    is_locked: bool = Field(default=False, description="Whether the file is locked by the peer")


class TransferFile(BaseModel):
    """Transfer status item for an active or past download/upload."""

    id: str = Field(description="Unique transfer identifier")
    username: str = Field(description="Peer username")
    direction: str = Field(description="Transfer direction ('Download' or 'Upload')")
    filename: str = Field(description="File path being transferred")
    size: int = Field(description="File size in bytes")
    state: str = Field(description="Current transfer state (e.g. InProgress, Completed, Succeeded, Queued)")
    percent_complete: float = Field(default=0.0, description="Transfer completion percentage (0-100)")
    bytes_transferred: int = Field(default=0, description="Bytes transferred so far")
    bytes_remaining: int = Field(default=0, description="Bytes remaining")
    average_speed: float = Field(default=0.0, description="Transfer speed in bytes/sec")
    elapsed_time: Optional[str] = Field(default=None, description="Elapsed time duration string")
    remaining_time: Optional[str] = Field(default=None, description="Estimated remaining time string")


class DownloadResult(BaseModel):
    """Result of enqueuing a download."""

    success: bool = Field(description="Whether the file was successfully enqueued")
    username: str = Field(description="Soulseek username to download from")
    filename: str = Field(description="Requested filename")
    size: int = Field(default=0, description="File size in bytes")
    status: str = Field(description="Status description (e.g. 'queued', 'started')")
    message: Optional[str] = Field(default=None, description="Additional status message or error details")


class CancelResult(BaseModel):
    """Result of canceling a transfer."""

    success: bool = Field(description="Whether the cancellation succeeded")
    username: str = Field(description="Peer username")
    id: str = Field(description="Transfer ID")
    message: str = Field(description="Status message")


class DirectoryFile(BaseModel):
    """File item inside a peer's directory listing."""

    filename: str = Field(description="File name / path")
    size: int = Field(description="File size in bytes")
    bitrate: Optional[int] = Field(default=None, description="Audio bitrate")
    length: Optional[int] = Field(default=None, description="Duration in seconds")


class DirectoryListing(BaseModel):
    """Directory contents response."""

    name: str = Field(description="Directory name or path")
    file_count: int = Field(default=0, description="Number of files in directory")
    files: List[Dict[str, Any]] = Field(default_factory=list, description="Files in directory")
