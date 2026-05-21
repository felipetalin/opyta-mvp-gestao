import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("app"))

# Evita dependência real de streamlit na suíte unitária.
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = SimpleNamespace(
        secrets={},
        session_state={},
        stop=lambda: None,
        error=lambda _msg: None,
    )

import services.finance_guard as fg


class StopCalled(Exception):
    pass


class FinanceGuardTests(unittest.TestCase):
    def _fake_st(self, secrets=None, session_state=None):
        return SimpleNamespace(
            secrets=secrets or {},
            session_state=session_state or {},
            stop=lambda: (_ for _ in ()).throw(StopCalled()),
            error=lambda _msg: None,
        )

    def test_default_policy_read_and_write(self):
        fake_st = self._fake_st()
        with patch.object(fg, "st", fake_st):
            self.assertTrue(fg.has_finance_read_access("felipetalin@opyta.com.br"))
            self.assertTrue(fg.can_finance_write("felipetalin@opyta.com.br"))
            self.assertTrue(fg.has_finance_read_access("yurisimoes@opyta.com.br"))
            self.assertFalse(fg.can_finance_write("yurisimoes@opyta.com.br"))

    def test_policy_from_env_json(self):
        fake_st = self._fake_st(secrets={})
        env_payload = '{"alpha@opyta.com.br": {"read": true, "write": false}}'
        with patch.object(fg, "st", fake_st):
            with patch.dict(os.environ, {"FINANCE_ACCESS_POLICY_JSON": env_payload}, clear=False):
                self.assertTrue(fg.has_finance_read_access("alpha@opyta.com.br"))
                self.assertFalse(fg.can_finance_write("alpha@opyta.com.br"))

    def test_policy_from_secrets_has_priority_over_env(self):
        fake_st = self._fake_st(
            secrets={
                "FINANCE_ACCESS_POLICY": {
                    "beta@opyta.com.br": {"read": True, "write": True},
                }
            }
        )
        env_payload = '{"beta@opyta.com.br": {"read": true, "write": false}}'
        with patch.object(fg, "st", fake_st):
            with patch.dict(os.environ, {"FINANCE_ACCESS_POLICY_JSON": env_payload}, clear=False):
                self.assertTrue(fg.has_finance_read_access("beta@opyta.com.br"))
                self.assertTrue(fg.can_finance_write("beta@opyta.com.br"))

    def test_require_finance_access_returns_email_when_authorized(self):
        fake_st = self._fake_st(
            session_state={"user_email": "FelipeTalin@opyta.com.br"},
        )
        with patch.object(fg, "st", fake_st):
            self.assertEqual(fg.require_finance_access(silent=True), "felipetalin@opyta.com.br")

    def test_require_finance_access_stops_when_unauthorized(self):
        fake_st = self._fake_st(
            session_state={"user_email": "naoautorizado@opyta.com.br"},
        )
        with patch.object(fg, "st", fake_st):
            with self.assertRaises(StopCalled):
                fg.require_finance_access(silent=True)


if __name__ == "__main__":
    unittest.main()
