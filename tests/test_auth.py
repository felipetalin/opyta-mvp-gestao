"""
Testes unitários para app/services/auth.py
Cobre: is_logged_in, _clear_auth_state, logout.
Não depende de streamlit instalado (stub injetado antes do import).
"""

import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Stub streamlit e supabase_client antes de importar o módulo de auth
# ---------------------------------------------------------------------------
_session: dict = {}

_fake_st = SimpleNamespace(
    session_state=_session,
    secrets={},
    stop=lambda: None,
    error=lambda _msg: None,
    success=lambda _msg: None,
    subheader=lambda _t: None,
    text_input=lambda *a, **kw: "",
    button=lambda *a, **kw: False,
    rerun=lambda: None,
)

if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = _fake_st

if "services.supabase_client" not in sys.modules:
    sys.modules["services.supabase_client"] = SimpleNamespace(
        get_anon_client=lambda: MagicMock(),
        get_authed_client=lambda: MagicMock(),
    )

import sys, os  # noqa: E402,F401
sys.path.insert(0, os.path.abspath("app"))

import services.auth as auth  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _set_session(**kwargs):
    _session.clear()
    _session.update(kwargs)


class TestIsLoggedIn(unittest.TestCase):

    def test_false_when_no_token(self):
        _set_session()
        with patch.object(auth, "st", _fake_st):
            self.assertFalse(auth.is_logged_in())

    def test_true_with_valid_token_no_expiry(self):
        _set_session(access_token="tok")
        with patch.object(auth, "st", _fake_st):
            self.assertTrue(auth.is_logged_in())

    def test_true_with_future_expiry(self):
        _set_session(access_token="tok", expires_at=int(time.time()) + 3600)
        with patch.object(auth, "st", _fake_st):
            self.assertTrue(auth.is_logged_in())

    def test_false_when_expired(self):
        _set_session(access_token="tok", expires_at=int(time.time()) - 10)
        with patch.object(auth, "st", _fake_st):
            self.assertFalse(auth.is_logged_in())

    def test_false_cleared_on_expired(self):
        _set_session(access_token="tok", expires_at=int(time.time()) - 10, user_email="a@b.com")
        with patch.object(auth, "st", _fake_st):
            auth.is_logged_in()
        self.assertNotIn("access_token", _session)
        self.assertNotIn("user_email", _session)

    def test_false_cleared_on_invalid_expires_at(self):
        _set_session(access_token="tok", expires_at="NaN")
        with patch.object(auth, "st", _fake_st):
            self.assertFalse(auth.is_logged_in())
        self.assertNotIn("access_token", _session)


class TestLogout(unittest.TestCase):

    def test_logout_clears_all_auth_keys(self):
        _set_session(
            access_token="tok",
            refresh_token="ref",
            expires_at=9999999999,
            user_email="x@y.com",
        )
        with patch.object(auth, "st", _fake_st):
            auth.logout()
        for key in ["access_token", "refresh_token", "expires_at", "user_email"]:
            self.assertNotIn(key, _session, f"Chave '{key}' deveria ter sido removida após logout.")

    def test_logout_is_idempotent(self):
        _set_session()
        with patch.object(auth, "st", _fake_st):
            auth.logout()
            auth.logout()  # não deve lançar exceção


if __name__ == "__main__":
    unittest.main()
