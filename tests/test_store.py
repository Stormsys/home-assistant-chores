"""Tests for store.py — ChoreStore persistence."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.chores.store import ChoreStore


class TestChoreStore:
    def _make(self):
        hass = MagicMock()
        store = ChoreStore(hass)
        # Override the internal _store to avoid real HA storage
        store._store = MagicMock()
        store._store.async_load = AsyncMock(return_value=None)
        store._store.async_save = AsyncMock()
        store._store.async_remove = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_load_empty(self):
        store = self._make()
        await store.async_load()
        assert store._data == {"chores": {}}

    @pytest.mark.asyncio
    async def test_load_existing_data(self):
        store = self._make()
        store._store.async_load = AsyncMock(return_value={
            "chores": {"chore1": {"state": "due"}},
        })
        await store.async_load()
        assert store.get_chore_state("chore1") == {"state": "due"}

    def test_set_and_get_chore_state(self):
        store = self._make()
        store._data = {"chores": {}}
        store.set_chore_state("test_chore", {"state": "completed"})
        result = store.get_chore_state("test_chore")
        assert result == {"state": "completed"}

    def test_get_nonexistent_returns_none(self):
        store = self._make()
        store._data = {"chores": {}}
        assert store.get_chore_state("nonexistent") is None

    def test_remove_chore_state(self):
        store = self._make()
        store._data = {"chores": {"chore1": {"state": "due"}}}
        store.remove_chore_state("chore1")
        assert store.get_chore_state("chore1") is None

    def test_remove_nonexistent_no_error(self):
        store = self._make()
        store._data = {"chores": {}}
        store.remove_chore_state("nonexistent")  # Should not raise

    def test_chore_ids(self):
        store = self._make()
        store._data = {"chores": {"a": {}, "b": {}, "c": {}}}
        assert sorted(store.chore_ids) == ["a", "b", "c"]

    def test_chore_ids_empty(self):
        store = self._make()
        store._data = {"chores": {}}
        assert store.chore_ids == []

    @pytest.mark.asyncio
    async def test_save(self):
        store = self._make()
        store._data = {"chores": {"test": {"state": "due"}}}
        await store.async_save()
        store._store.async_save.assert_called_once_with(store._data)

    def test_set_creates_chores_key(self):
        store = self._make()
        store._data = {}
        store.set_chore_state("test", {"state": "idle"})
        assert "chores" in store._data
        assert store._data["chores"]["test"] == {"state": "idle"}

    @pytest.mark.asyncio
    async def test_load_non_dict_uses_default(self):
        store = self._make()
        store._store.async_load = AsyncMock(return_value="invalid")
        await store.async_load()
        assert store._data == {"chores": {}}
