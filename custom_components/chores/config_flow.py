"""Config flow for the Chores integration - YAML import only."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class ChoresConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chores - YAML import only."""

    VERSION = 2

    async def async_step_import(
        self, import_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle import from YAML configuration."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Chores",
            data={},
        )
