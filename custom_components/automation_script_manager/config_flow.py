"""Config flow for Automation & Script Manager."""

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automation & Script Manager."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Automation & Script Manager", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Manage the initial options."""
        if not hasattr(self, "_options_data"):
            self._options_data = dict(self.config_entry.options)

        if user_input is not None:
            self._options_data.update(user_input)
            if user_input.get("expose_actions_mode") == "allow_all":
                if user_input.get("use_regex_rules"):
                    return await self.async_step_regex()
                return self.async_create_entry(title="", data=self._options_data)
            return await self.async_step_domains()

        from homeassistant.helpers import selector

        schema = vol.Schema(
            {
                vol.Optional(
                    "tag",
                    default=self._options_data.get("tag", ""),
                ): str,
                vol.Optional(
                    "one_shot_tag",
                    default=self._options_data.get("one_shot_tag", "one-shot"),
                ): str,
                vol.Optional(
                    "restrict_deletion",
                    default=self._options_data.get("restrict_deletion", False),
                ): bool,
                vol.Optional(
                    "disable_instead_of_delete",
                    default=self._options_data.get(
                        "disable_instead_of_delete", False
                    ),
                ): bool,
                vol.Optional(
                    "would_be_deleted_tag",
                    default=self._options_data.get(
                        "would_be_deleted_tag", "would-be-deleted"
                    ),
                ): str,
                vol.Optional(
                    "expose_llm_tools",
                    default=self._options_data.get("expose_llm_tools", True),
                ): bool,
                vol.Optional(
                    "expose_actions_mode",
                    default=self._options_data.get(
                        "expose_actions_mode", "allow_all"
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": "allow_all",
                                "label": "Allow all actions",
                            },
                            {
                                "value": "expose_all_except",
                                "label": "Allow all except selected...",
                            },
                            {
                                "value": "expose_only_these",
                                "label": "Allow only selected...",
                            },
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    "use_regex_rules",
                    default=self._options_data.get("use_regex_rules", False),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )

    async def async_step_domains(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Configure domain-level choices."""
        if user_input is not None:
            self._options_data.update(user_input)
            has_per_action = any(
                v == "per_action"
                for k, v in user_input.items()
                if k.startswith("domain_config_")
            )
            if has_per_action:
                return await self.async_step_actions()
            if self._options_data.get("use_regex_rules"):
                return await self.async_step_regex()
            return self.async_create_entry(title="", data=self._options_data)

        # Retrieve registered domains
        domains = sorted(self.hass.services.async_services().keys())
        schema_dict = {}
        for domain in domains:
            schema_dict[
                vol.Optional(
                    f"domain_config_{domain}",
                    default=self._options_data.get(
                        f"domain_config_{domain}", "global"
                    ),
                )
            ] = vol.In(
                {
                    "global": "Use global choice",
                    "allow": "Allow",
                    "deny": "Deny",
                    "per_action": "Choose per-action",
                }
            )

        return self.async_show_form(
            step_id="domains",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Configure action-level choices."""
        if user_input is not None:
            self._options_data.update(user_input)
            if self._options_data.get("use_regex_rules"):
                return await self.async_step_regex()
            return self.async_create_entry(title="", data=self._options_data)

        # Retrieve action domains marked as per_action
        per_action_domains = [
            k[len("domain_config_") :]
            for k, v in self._options_data.items()
            if k.startswith("domain_config_") and v == "per_action"
        ]

        services_dict = self.hass.services.async_services()
        schema_dict = {}
        for domain in sorted(per_action_domains):
            if domain not in services_dict:
                continue
            for service in sorted(services_dict[domain].keys()):
                schema_dict[
                    vol.Optional(
                        f"action_config_{domain}_{service}",
                        default=self._options_data.get(
                            f"action_config_{domain}_{service}", "global"
                        ),
                    )
                ] = vol.In(
                    {
                        "global": "Use global choice",
                        "allow": "Allow",
                        "deny": "Deny",
                    }
                )

        return self.async_show_form(
            step_id="actions",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_regex(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Configure regular expression rules."""
        if user_input is not None:
            self._options_data.update(user_input)
            return self.async_create_entry(title="", data=self._options_data)

        from homeassistant.helpers import selector

        schema = vol.Schema(
            {
                vol.Optional(
                    "allow_regexes",
                    default=self._options_data.get("allow_regexes", ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Optional(
                    "disallow_regexes",
                    default=self._options_data.get("disallow_regexes", ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )

        return self.async_show_form(
            step_id="regex",
            data_schema=schema,
        )
