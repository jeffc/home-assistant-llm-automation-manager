"""Config flow for Automation & Script Manager.

Handles setup and options flow for configuring the custom integration.
Allows users to specify tags, deletion restrictions, override policies,
and allowed/denied action lists using regular expressions.
"""

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automation & Script Manager.

    This manages the initial installation/configuration entry creation
    when the user first adds the integration.
    """

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Handle the initial setup step.

        Aborts if an instance is already configured since only a single
        instance of the manager is supported.
        """
        # Ensure only a single config entry is ever created.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # If user confirmed installation, create config entry with empty data.
        # Options flow handles all actual parameters.
        if user_input is not None:
            return self.async_create_entry(
                title="Automation & Script Manager", data={}
            )

        # Show the confirmation form to the user.
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow handler.

        This connects the config entry to our OptionsFlowHandler.
        """
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for the integration.

    Provides a form to configure behavioral options including labels,
    deletion policies, LLM exposure settings, and regex permission rules.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Manage the initial options page.

        Builds the options configuration schema, parses user inputs, and saves
        them into the ConfigEntry's options dictionary.
        """
        # Initialize internal storage for config flow options.
        if not hasattr(self, "_options_data"):
            self._options_data = dict(self.config_entry.options)

        # Save config changes and exit the flow when user submits the form.
        if user_input is not None:
            self._options_data.update(user_input)
            return self.async_create_entry(title="", data=self._options_data)

        from homeassistant.helpers import selector

        # Build schema for all configurable options with defaults.
        schema = vol.Schema(
            {
                # Tag (label) auto-assigned to all created entities.
                vol.Optional(
                    "tag",
                    default=self._options_data.get(
                        "tag", "CREATED_WITH_AUTOMATION"
                    ),
                ): str,
                # Tag (label) auto-assigned to temporary/one-shot entities.
                vol.Optional(
                    "one_shot_tag",
                    default=self._options_data.get("one_shot_tag", "one-shot"),
                ): str,
                # Force delete validation (only allow deleting tagged entities).
                vol.Optional(
                    "restrict_deletion",
                    default=self._options_data.get("restrict_deletion", False),
                ): bool,
                # Intercept deletions, disabling entities instead of removing them.
                vol.Optional(
                    "disable_instead_of_delete",
                    default=self._options_data.get(
                        "disable_instead_of_delete", False
                    ),
                ): bool,
                # Tag applied to entities that were disabled instead of deleted.
                vol.Optional(
                    "would_be_deleted_tag",
                    default=self._options_data.get(
                        "would_be_deleted_tag", "would-be-deleted"
                    ),
                ): str,
                # Expose creation/deletion actions as intent tools to Assist/LLM.
                vol.Optional(
                    "expose_llm_tools",
                    default=self._options_data.get("expose_llm_tools", True),
                ): bool,
                # Enable debug mode to log and return LLM reasoning.
                vol.Optional(
                    "debug_mode",
                    default=self._options_data.get("debug_mode", False),
                ): bool,
                # Regular expression patterns for blocked service actions.
                vol.Optional(
                    "disallow_regexes",
                    default=self._options_data.get(
                        "disallow_regexes", "homeassistant\\..*"
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                # Regular expression patterns for allowed service actions.
                vol.Optional(
                    "allow_regexes",
                    default=self._options_data.get("allow_regexes", ".*"),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )

        # Render the options form with the constructed schema.
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
