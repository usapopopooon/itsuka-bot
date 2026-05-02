"""pytest fixtures.

CI / ローカルで Discord トークンや管理者パスワードが無くてもインポートが
通るように、テスト読み込み前に環境変数を埋める。
"""

from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "test_token")
os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test_password")
os.environ.setdefault("SESSION_SECRET_KEY", "test_session_secret_key_for_pytest")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
