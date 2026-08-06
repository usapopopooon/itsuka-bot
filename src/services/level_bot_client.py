"""level-botのitsuka連携APIクライアント。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx


@dataclass(frozen=True)
class MessageComboXpAward:
    event_id: str
    streak_days: int
    awarded_xp: int
    duplicate: bool


async def award_message_combo_xp(
    *,
    api_url: str,
    api_token: str,
    event_id: str,
    guild_id: str,
    channel_id: str,
    user_id: str,
    config_id: int,
    streak_days: int,
    observed_at: datetime,
) -> MessageComboXpAward:
    if not api_url or not api_token:
        raise RuntimeError("level-bot API is not configured")
    normalized_observed_at = (
        observed_at.replace(tzinfo=UTC) if observed_at.tzinfo is None else observed_at
    )
    payload = {
        "event_id": event_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "config_id": str(config_id),
        "streak_days": streak_days,
        "observed_at": normalized_observed_at.isoformat(),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{api_url}/api/v1/integrations/itsuka/message-combo-xp-events",
            json=payload,
            headers={"Authorization": f"Bearer {api_token}"},
        )
    response.raise_for_status()
    data = response.json()
    return MessageComboXpAward(
        event_id=str(data["event_id"]),
        streak_days=int(data["streak_days"]),
        awarded_xp=int(data["awarded_xp"]),
        duplicate=bool(data["duplicate"]),
    )
