"""Bot setup behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.bot import ItsukaBot


@pytest.mark.asyncio
async def test_setup_hook_starts_retry_when_command_sync_fails(monkeypatch) -> None:
    bot = ItsukaBot()
    monkeypatch.setattr(bot, "load_extension", AsyncMock())
    monkeypatch.setattr(
        bot, "_sync_application_commands", AsyncMock(return_value=False)
    )
    retry = MagicMock()
    monkeypatch.setattr(bot, "_start_command_sync_retry", retry)

    try:
        await bot.setup_hook()
    finally:
        await bot.close()

    assert bot.load_extension.await_count == 3
    retry.assert_called_once_with()


@pytest.mark.asyncio
async def test_sync_application_commands_returns_false_on_http_error(
    monkeypatch,
) -> None:
    bot = ItsukaBot()
    response = MagicMock(status=503, reason="Service Unavailable")
    monkeypatch.setattr(
        bot.tree,
        "sync",
        AsyncMock(side_effect=discord.HTTPException(response, "boom")),
    )

    try:
        ok = await bot._sync_application_commands()
    finally:
        await bot.close()

    assert ok is False
