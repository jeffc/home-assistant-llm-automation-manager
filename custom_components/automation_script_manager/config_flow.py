"""Config flow for Automation & Script Manager.

Handles setup and options flow for configuring the custom integration.
Allows users to specify tags, deletion restrictions, override policies,
and allowed/denied action lists using regular expressions.
"""

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

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

        import homeassistant.helpers.category_registry as cr
        category_reg = cr.async_get(self.hass)

        automation_categories = list(
            category_reg.async_list_categories(scope="automation")
        )
        script_categories = list(
            category_reg.async_list_categories(scope="script")
        )

        has_categories = len(automation_categories) > 0 or len(script_categories) > 0

        categorize_modes = {
            "leave_uncategorized": "Leave uncategorized",
        }
        if has_categories:
            categorize_modes["put_in_specified"] = "Put in specified category"
            categorize_modes["auto_categorize"] = "Auto-categorize"

        # Save config changes and transition to category steps or security step.
        if user_input is not None:
            self._options_data.update(user_input)

            mode = self._options_data.get("categorize_mode", "leave_uncategorized")
            if mode == "put_in_specified" and has_categories:
                return await self.async_step_category_specified()
            if mode == "auto_categorize" and has_categories:
                return await self.async_step_category_auto()

            return await self.async_step_security()

        # Build schema for all configurable options with defaults.
        schema = vol.Schema(
            {
                # Tag (label) auto-assigned to all created entities.
                vol.Optional(
                    "tag",
                    default=self._options_data.get(
                        "tag", "CREATED_WITH_AUTOMATION"
                    ),
                ): vol.All(cv.string, vol.Match(r"^[a-zA-Z0-9_\-\s]*$")),
                # Tag (label) auto-assigned to temporary/one-shot entities.
                vol.Optional(
                    "one_shot_tag",
                    default=self._options_data.get("one_shot_tag", "one-shot"),
                ): vol.All(cv.string, vol.Match(r"^[a-zA-Z0-9_\-\s]*$")),
                # Expose creation/deletion actions as intent tools to Assist/LLM.
                vol.Optional(
                    "expose_llm_tools",
                    default=self._options_data.get("expose_llm_tools", True),
                ): bool,
                # Let the AI assistant choose custom icons for entities.
                vol.Optional(
                    "let_llm_assign_icon",
                    default=self._options_data.get("let_llm_assign_icon", True),
                ): bool,
                # Settings to control if the LLM should be prompted to be explicit.
                vol.Optional(
                    "prompt_one_time_vs_recurring",
                    default=self._options_data.get(
                        "prompt_one_time_vs_recurring", True
                    ),
                ): bool,
                # Enable debug mode to log and return LLM reasoning.
                vol.Optional(
                    "debug_mode",
                    default=self._options_data.get("debug_mode", False),
                ): bool,
                # Categorization modes
                vol.Optional(
                    "categorize_mode",
                    default=self._options_data.get(
                        "categorize_mode", "leave_uncategorized"
                    ),
                ): vol.In(categorize_modes),
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
                ): vol.All(cv.string, vol.Match(r"^[a-zA-Z0-9_\-\s]*$")),
            }
        )

        # Render the options form with the constructed schema.
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )

    async def async_step_category_specified(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle specified category configuration step."""
        if user_input is not None:
            self._options_data.update(user_input)
            return await self.async_step_security()

        import homeassistant.helpers.category_registry as cr
        category_reg = cr.async_get(self.hass)

        automation_categories = {
            cat.category_id: cat.name
            for cat in category_reg.async_list_categories(scope="automation")
        }
        script_categories = {
            cat.category_id: cat.name
            for cat in category_reg.async_list_categories(scope="script")
        }

        # Add a default/no-category option
        automation_cat_options = {"": "None"}
        automation_cat_options.update(automation_categories)

        script_cat_options = {"": "None"}
        script_cat_options.update(script_categories)

        schema = vol.Schema(
            {
                vol.Optional(
                    "specified_automation_category",
                    default=self._options_data.get(
                        "specified_automation_category", ""
                    ),
                ): vol.In(automation_cat_options),
                vol.Optional(
                    "specified_script_category",
                    default=self._options_data.get(
                        "specified_script_category", ""
                    ),
                ): vol.In(script_cat_options),
            }
        )

        return self.async_show_form(
            step_id="category_specified",
            data_schema=schema,
        )

    async def async_step_category_auto(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle auto-categorize configuration step."""
        if user_input is not None:
            self._options_data.update(user_input)
            return await self.async_step_security()

        schema = vol.Schema(
            {
                vol.Optional(
                    "always_assign_category",
                    default=self._options_data.get(
                        "always_assign_category", False
                    ),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="category_auto",
            data_schema=schema,
        )

    async def async_step_security(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle security configuration step."""
        if user_input is not None:
            self._options_data.update(user_input)
            return self.async_create_entry(title="", data=self._options_data)

        from homeassistant.helpers import selector

        schema = vol.Schema(
            {
                vol.Optional(
                    "disallow_regexes",
                    default=self._options_data.get(
                        "disallow_regexes", "homeassistant\\..*"
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Optional(
                    "allow_regexes",
                    default=self._options_data.get("allow_regexes", ".*"),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )

        return self.async_show_form(
            step_id="security",
            data_schema=schema,
        )
