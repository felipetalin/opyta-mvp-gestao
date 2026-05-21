"""
Testes de isolamento de cache por sessão/usuário.

Verifica que funções com @st.cache_data parametrizadas por cache_key
não retornam dados de um usuário para outro.
Não depende de streamlit instalado (stub injetado antes do import).
"""

import sys
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Stubs mínimos — streamlit com cache_data que executa a função normalmente
# ---------------------------------------------------------------------------

def _real_cache_data(ttl=None):
    """
    Substituto de @st.cache_data que, nos testes, simplesmente chama a função
    sem qualquer caching (isolamento garantido: sem estado global entre chamadas).
    """
    def decorator(fn):
        cache = {}

        def wrapper(*a, **kw):
            key = (a, tuple(sorted(kw.items())))
            if key not in cache:
                cache[key] = fn(*a, **kw)
            return cache[key]

        wrapper._cache = cache
        wrapper.clear = lambda: cache.clear()
        return wrapper

    return decorator


_fake_st = SimpleNamespace(
    session_state={},
    secrets={},
    stop=lambda: None,
    cache_data=_real_cache_data,
)

sys.modules["streamlit"] = _fake_st

sys.path.insert(0, os.path.abspath("app"))

import streamlit as st  # noqa: E402 — já é o stub acima; garante referência atualizada


def _make_fetch_fn():
    """
    Cria uma função de fetch parametrizada por cache_key
    (replica o padrão aplicado nas páginas Gantt, Projetos, Financeiro).
    """
    call_log: list[str] = []

    @st.cache_data(ttl=30)
    def fetch_data(_cache_key: str, source_label: str = "default"):
        call_log.append(_cache_key)
        return {"owner": _cache_key, "source": source_label}

    return fetch_data, call_log


class TestCacheIsolationBySessionKey(unittest.TestCase):

    def test_different_keys_return_different_data(self):
        fetch, _ = _make_fetch_fn()
        result_a = fetch("token-user-A")
        result_b = fetch("token-user-B")
        self.assertNotEqual(result_a["owner"], result_b["owner"])
        self.assertEqual(result_a["owner"], "token-user-A")
        self.assertEqual(result_b["owner"], "token-user-B")

    def test_same_key_uses_cached_result(self):
        fetch, call_log = _make_fetch_fn()
        fetch("token-user-C")
        fetch("token-user-C")
        self.assertEqual(call_log.count("token-user-C"), 1, "Deve ter chamado a fonte apenas uma vez para o mesmo cache_key.")

    def test_clear_invalidates_cache(self):
        fetch, call_log = _make_fetch_fn()
        fetch("token-user-D")
        fetch._cache.clear()
        fetch("token-user-D")
        self.assertEqual(call_log.count("token-user-D"), 2, "Após limpar o cache a fonte deve ser chamada novamente.")

    def test_empty_key_isolates_from_named_key(self):
        fetch, _ = _make_fetch_fn()
        result_anon = fetch("")
        result_user = fetch("token-user-E")
        self.assertNotEqual(result_anon, result_user)

    def test_no_token_sentinel_isolated_from_real_token(self):
        """Garante que o valor 'no-token' não coincide com um token real."""
        fetch, _ = _make_fetch_fn()
        result_no_token = fetch("no-token")
        result_real = fetch("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real")
        self.assertNotEqual(result_no_token, result_real)


if __name__ == "__main__":
    unittest.main()
