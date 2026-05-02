"""JWT 発行 / 検証のユニットテスト。"""

from __future__ import annotations

import time

from src.web.jwt_auth import create_jwt_token, verify_jwt_token


def test_round_trip() -> None:
    token = create_jwt_token("admin")
    payload = verify_jwt_token(token)
    assert payload is not None
    assert payload["sub"] == "admin"
    assert payload["iat"] <= int(time.time())
    assert payload["exp"] > payload["iat"]


def test_verify_garbage_returns_none() -> None:
    assert verify_jwt_token("not-a-jwt") is None
    assert verify_jwt_token("") is None
    assert verify_jwt_token("   ") is None


def test_verify_tampered_returns_none() -> None:
    token = create_jwt_token("admin")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert verify_jwt_token(tampered) is None
