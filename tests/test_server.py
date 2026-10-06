"""Test suite for slskd-mcp."""

import pytest
from slskd_mcp.server import (
    slskd_status,
    slskd_search,
    slskd_get_transfers,
    slskd_download,
    slskd_download_directory,
    slskd_cancel_download,
    slskd_clear_transfers,
    slskd_browse_user,
    slskd_get_user_info,
    slskd_get_me,
    slskd_get_shares,
    slskd_rescan_shares,
    slskd_get_rejected_peers,
)


@pytest.mark.asyncio
async def test_slskd_status():
    status = await slskd_status()
    assert isinstance(status, dict)
    assert status.get("connected") is True
    assert status.get("logged_in") is True
    assert "version" in status


@pytest.mark.asyncio
async def test_slskd_get_me():
    me = await slskd_get_me()
    assert isinstance(me, dict)
    assert me.get("is_connected") is True
    assert me.get("username") != "unknown"


@pytest.mark.asyncio
async def test_slskd_get_shares():
    shares = await slskd_get_shares()
    assert isinstance(shares, dict)
    assert "shares" in shares
    assert "files_count" in shares


@pytest.mark.asyncio
async def test_slskd_get_user_info():
    user = await slskd_get_user_info(username="ValdikSS2")
    assert isinstance(user, dict)
    assert user.get("username") == "ValdikSS2"
    assert "presence" in user


@pytest.mark.asyncio
async def test_slskd_get_transfers():
    downloads = await slskd_get_transfers(direction="downloads")
    assert isinstance(downloads, list)
    uploads = await slskd_get_transfers(direction="uploads")
    assert isinstance(uploads, list)


@pytest.mark.asyncio
async def test_slskd_search():
    results = await slskd_search(
        query="Boards of Canada",
        timeout_seconds=5,
        max_results=5,
        format_filter="flac",
        exclude_locked=True,
    )
    assert isinstance(results, list)
    if results and "error" not in results[0]:
        assert len(results) <= 5
        assert all(r["filename"].lower().endswith(".flac") for r in results)


@pytest.mark.asyncio
async def test_slskd_browse_user():
    res = await slskd_browse_user(username="ValdikSS2")
    assert isinstance(res, (dict, list))


@pytest.mark.asyncio
async def test_slskd_download_and_cancel():
    dl_res = await slskd_download(username="testdummyuser", filename="test.mp3", size=1024)
    assert isinstance(dl_res, dict)
    assert dl_res.get("username") == "testdummyuser"

    cancel_res = await slskd_cancel_download(
        username="testdummyuser",
        id="00000000-0000-0000-0000-000000000000",
    )
    assert isinstance(cancel_res, dict)
    assert cancel_res.get("success") is True


@pytest.mark.asyncio
async def test_slskd_clear_transfers():
    res = await slskd_clear_transfers(direction="downloads")
    assert isinstance(res, dict)
    assert res.get("success") is True
