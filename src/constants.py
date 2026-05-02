"""アプリ全体で使う定数。"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# セッション / 認証
# ---------------------------------------------------------------------------

SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 7  # 7 日
TOKEN_BYTE_LENGTH: int = 32

# ---------------------------------------------------------------------------
# レート制限 / クールタイム
# ---------------------------------------------------------------------------

LOGIN_MAX_ATTEMPTS: int = 5
LOGIN_WINDOW_SECONDS: int = 60 * 5
RATE_LIMIT_CLEANUP_INTERVAL_SECONDS: int = 60 * 10

FORM_SUBMIT_COOLDOWN_SECONDS: int = 1
FORM_COOLDOWN_CLEANUP_INTERVAL_SECONDS: int = 60 * 10
