"""slskd-mcp: Model Context Protocol (MCP) server for slskd Soulseek daemon."""

__version__ = "0.1.0"

from .client import SlskdClient
from .config import Settings, settings

__all__ = ["SlskdClient", "Settings", "settings", "__version__"]
