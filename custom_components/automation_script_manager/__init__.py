"""The Automation & Script Manager integration."""

import logging
import os
import uuid
import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    CONF_ID,
    SERVICE_RELOAD,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.exceptions import HomeAssistantError

# For YAML loading and writing
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

# Paths for automations and scripts
from homeassistant.config import AUTOMATION_CONFIG_PATH, SCRIPT_CONFIG_PATH

# Domains
from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN

# Config validators
from homeassistant.components.automation.config import (
    async_validate_config_item as async_validate_automation_item,
)
from homeassistant.components.script.config import (
    async_validate_config_item as async_validate_script_item,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CREATE_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("config"): dict,
        vol.Optional("alias"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("trigger"): cv.match_all,
        vol.Optional("triggers"): cv.match_all,
        vol.Optional("condition"): cv.match_all,
        vol.Optional("conditions"): cv.match_all,
        vol.Optional("action"): cv.match_all,
        vol.Optional("actions"): cv.match_all,
        vol.Optional("mode"): cv.string,
        vol.Optional("on_completion", default="persist"): vol.In(
            ["delete_self", "disable_self", "persist"]
        ),
    }
)

DELETE_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
    }
)

CREATE_SCRIPT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("config"): dict,
        vol.Optional("alias"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("sequence"): cv.match_all,
        vol.Optional("mode"): cv.string,
        vol.Optional("on_completion", default="persist"): vol.In(
            ["delete_self", "persist"]
        ),
    }
)

DELETE_SCRIPT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
    }
)

def _read_yaml(path: str) -> Any:
    """Read YAML helper."""
    if not os.path.isfile(path):
        return None
    return load_yaml(path)

def _write_yaml(path: str, data: Any) -> None:
    """Write YAML helper atomically."""
    contents = dump(data)
    write_utf8_file_atomic(path, contents)

async def _async_assign_tag(
    hass: HomeAssistant, domain: str, config_key: str, tag: str
) -> None:
    """Assign a tag to the newly created entity in the registry."""
    if not tag:
        return

    label_reg = lr.async_get(hass)
    label = label_reg.async_get_label_by_name(tag)
    if label is None:
        try:
            label = label_reg.async_create(tag)
        except ValueError:
            # Fallback if label is already in use by name (concurrency)
            label = next(
                (l for l in label_reg.labels.values() if l.name.lower() == tag.lower()),
                None,
            )
            if label is None:
                _LOGGER.error("Failed to find or create label '%s'", tag)
                return

    label_id = label.label_id

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(domain, domain, config_key)

    # Retry loop since reload is async and entity might not register instantly
    for _ in range(5):
        if entity_id:
            break
        await asyncio.sleep(0.5)
        entity_id = ent_reg.async_get_entity_id(domain, domain, config_key)

    if not entity_id:
        _LOGGER.warning(
            "Could not find registered entity for %s.%s to assign tag",
            domain,
            config_key,
        )
        return

    reg_entry = ent_reg.async_get(entity_id)
    if reg_entry:
        new_labels = reg_entry.labels | {label_id}
        ent_reg.async_update_entity(entity_id, labels=new_labels)
        _LOGGER.info("Assigned tag '%s' to entity '%s'", tag, entity_id)

def _verify_deletion_restriction(
    hass: HomeAssistant, domain: str, config_key: str
) -> None:
    """Verify if deletion is restricted based on options."""
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    if not entry:
        return

    restrict_deletion = entry.options.get("restrict_deletion", False)
    tag = entry.options.get("tag", "").strip()

    if not restrict_deletion or not tag:
        return

    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(domain, domain, config_key)

    if not entity_id:
        raise HomeAssistantError(
            f"Deletion restricted: Entity registry entry for {domain}.{config_key} not found, "
            f"cannot verify required tag '{tag}'."
        )

    reg_entry = ent_reg.async_get(entity_id)
    if not reg_entry:
        raise HomeAssistantError(
            f"Deletion restricted: Entity registry entry for {domain}.{config_key} not found, "
            f"cannot verify required tag '{tag}'."
        )

    label_reg = lr.async_get(hass)
    label = label_reg.async_get_label_by_name(tag)
    label_id = label.label_id if label else None

    if not label_id or label_id not in reg_entry.labels:
        raise HomeAssistantError(
            f"Deletion restricted: {domain.capitalize()} '{config_key}' does not have the required tag '{tag}'"
        )

async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Automation & Script Manager component."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Automation & Script Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["automation_lock"] = asyncio.Lock()
    hass.data[DOMAIN]["script_lock"] = asyncio.Lock()

    async def async_create_automation(call: ServiceCall) -> ServiceResponse:
        """Create or update an automation."""
        try:
            config_key = call.data.get("id")
            entity_id = call.data.get("entity_id")
            on_completion = call.data.get("on_completion", "persist")
            config_data = {}

            if "config" in call.data:
                config_data.update(call.data["config"])

            # Override or set individual fields if provided
            for key in (
                "alias",
                "description",
                "trigger",
                "triggers",
                "condition",
                "conditions",
                "action",
                "actions",
                "mode",
            ):
                if key in call.data:
                    config_data[key] = call.data[key]

            # Resolve config key from entity_id if id is not specified
            if not config_key:
                if entity_id:
                    ent_reg = er.async_get(hass)
                    reg_entry = ent_reg.async_get(entity_id)
                    if reg_entry is not None:
                        config_key = reg_entry.unique_id
                    else:
                        config_key = entity_id.split(".", 1)[1]
                else:
                    config_key = config_data.get("id")

            if not config_key:
                config_key = uuid.uuid4().hex

            # Ensure config has the id key
            config_data["id"] = config_key

            # Append completion action if specified
            if on_completion != "persist":
                actions = config_data.get("action") or config_data.get("actions") or []
                if isinstance(actions, dict):
                    actions = [actions]
                elif not isinstance(actions, list):
                    actions = []

                if on_completion == "delete_self":
                    completion_action = {
                        "action": "automation_script_manager.delete_automation",
                        "data": {
                            "entity_id": "{{ this.entity_id }}"
                        }
                    }
                elif on_completion == "disable_self":
                    completion_action = {
                        "action": "automation.turn_off",
                        "target": {
                            "entity_id": "{{ this.entity_id }}"
                        }
                    }

                # Pop 'actions' if present and unify into 'action' list
                config_data.pop("actions", None)
                actions.append(completion_action)
                config_data["action"] = actions

            # Validate the configuration
            await async_validate_automation_item(hass, config_key, config_data)

            # Order fields standardly like EditAutomationConfigView
            updated_value = {"id": config_key}
            for key in (
                "alias",
                "description",
                "triggers",
                "trigger",
                "conditions",
                "condition",
                "actions",
                "action",
            ):
                if key in config_data:
                    updated_value[key] = config_data[key]
            updated_value.update(config_data)

            path = hass.config.path(AUTOMATION_CONFIG_PATH)
            lock = hass.data[DOMAIN]["automation_lock"]

            async with lock:
                current = await hass.async_add_executor_job(_read_yaml, path)
                if current is None:
                    current = []
                elif not isinstance(current, list):
                    raise ValueError("automations.yaml is not a list")

                updated = False
                for index, cur_value in enumerate(current):
                    if not isinstance(cur_value, dict):
                        continue
                    # Generate unique ID for items missing it
                    if "id" not in cur_value:
                        cur_value["id"] = uuid.uuid4().hex

                    if cur_value["id"] == config_key:
                        current[index] = updated_value
                        updated = True
                        break

                if not updated:
                    current.append(updated_value)

                await hass.async_add_executor_job(_write_yaml, path, current)

            # Reload the automation
            await hass.services.async_call(
                AUTOMATION_DOMAIN, SERVICE_RELOAD, {CONF_ID: config_key}, blocking=True
            )
            _LOGGER.info("Successfully created/updated automation '%s'", config_key)

            # Assign tag if configured
            tag = entry.options.get("tag", "").strip()
            if tag:
                await _async_assign_tag(hass, AUTOMATION_DOMAIN, config_key, tag)

            return {"success": True, "id": config_key}

        except Exception as err:
            _LOGGER.error("Failed to create/update automation: %s", err)
            return {"success": False, "error": str(err)}

    async def async_delete_automation(call: ServiceCall) -> ServiceResponse:
        """Delete an automation."""
        try:
            config_key = call.data.get("id")
            entity_id = call.data.get("entity_id")

            if not config_key and not entity_id:
                raise ValueError("Either 'id' or 'entity_id' must be provided")

            if not config_key:
                ent_reg = er.async_get(hass)
                reg_entry = ent_reg.async_get(entity_id)
                if reg_entry is not None:
                    config_key = reg_entry.unique_id
                else:
                    config_key = entity_id.split(".", 1)[1]

            # Verify deletion restriction
            _verify_deletion_restriction(hass, AUTOMATION_DOMAIN, config_key)

            path = hass.config.path(AUTOMATION_CONFIG_PATH)
            lock = hass.data[DOMAIN]["automation_lock"]

            async with lock:
                current = await hass.async_add_executor_job(_read_yaml, path)
                if current is None:
                    current = []
                elif not isinstance(current, list):
                    raise ValueError("automations.yaml is not a list")

                index_to_delete = None
                for index, cur_value in enumerate(current):
                    if isinstance(cur_value, dict) and cur_value.get("id") == config_key:
                        index_to_delete = index
                        break

            if index_to_delete is None:
                raise ValueError(f"Automation with ID '{config_key}' not found")

            async with lock:
                current.pop(index_to_delete)
                await hass.async_add_executor_job(_write_yaml, path, current)

            # Remove from entity registry
            ent_reg = er.async_get(hass)
            reg_entity_id = ent_reg.async_get_entity_id(
                AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, config_key
            )
            if reg_entity_id is not None:
                ent_reg.async_remove(reg_entity_id)

            # Reload automations to apply deletion
            await hass.services.async_call(AUTOMATION_DOMAIN, SERVICE_RELOAD)
            _LOGGER.info("Successfully deleted automation '%s'", config_key)
            return {"success": True, "id": config_key}

        except Exception as err:
            _LOGGER.error("Failed to delete automation: %s", err)
            return {"success": False, "error": str(err)}

    async def async_create_script(call: ServiceCall) -> ServiceResponse:
        """Create or update a script."""
        try:
            config_key = call.data.get("id")
            entity_id = call.data.get("entity_id")
            on_completion = call.data.get("on_completion", "persist")

            if not config_key and not entity_id:
                raise ValueError("Either 'id' or 'entity_id' must be provided")

            if not config_key:
                ent_reg = er.async_get(hass)
                reg_entry = ent_reg.async_get(entity_id)
                if reg_entry is not None:
                    config_key = reg_entry.unique_id
                else:
                    config_key = entity_id.split(".", 1)[1]

            # Validate that the ID is a valid slug
            try:
                cv.slug(config_key)
            except vol.Invalid as err:
                raise ValueError(
                    f"Script ID '{config_key}' is not a valid slug (use only lowercase letters, numbers, and underscores): {err}"
                ) from err

            config_data = {}
            if "config" in call.data:
                config_data.update(call.data["config"])

            # Override or set individual fields if provided
            for key in ("alias", "description", "sequence", "mode"):
                if key in call.data:
                    config_data[key] = call.data[key]

            # Append completion action if specified
            if on_completion != "persist":
                sequence = config_data.get("sequence") or []
                if isinstance(sequence, dict):
                    sequence = [sequence]
                elif not isinstance(sequence, list):
                    sequence = []

                if on_completion == "delete_self":
                    completion_action = {
                        "action": "automation_script_manager.delete_script",
                        "data": {
                            "entity_id": "{{ this.entity_id }}"
                        }
                    }

                sequence.append(completion_action)
                config_data["sequence"] = sequence

            # Validate the configuration
            await async_validate_script_item(hass, config_key, config_data)

            path = hass.config.path(SCRIPT_CONFIG_PATH)
            lock = hass.data[DOMAIN]["script_lock"]

            async with lock:
                current = await hass.async_add_executor_job(_read_yaml, path)
                if current is None:
                    current = {}
                elif not isinstance(current, dict):
                    raise ValueError("scripts.yaml is not a dictionary")

                current[config_key] = config_data
                await hass.async_add_executor_job(_write_yaml, path, current)

            # Reload scripts
            await hass.services.async_call(SCRIPT_DOMAIN, SERVICE_RELOAD, blocking=True)
            _LOGGER.info("Successfully created/updated script '%s'", config_key)

            # Assign tag if configured
            tag = entry.options.get("tag", "").strip()
            if tag:
                await _async_assign_tag(hass, SCRIPT_DOMAIN, config_key, tag)

            return {"success": True, "id": config_key}

        except Exception as err:
            _LOGGER.error("Failed to create/update script: %s", err)
            return {"success": False, "error": str(err)}

    async def async_delete_script(call: ServiceCall) -> ServiceResponse:
        """Delete a script."""
        try:
            config_key = call.data.get("id")
            entity_id = call.data.get("entity_id")

            if not config_key and not entity_id:
                raise ValueError("Either 'id' or 'entity_id' must be provided")

            if not config_key:
                ent_reg = er.async_get(hass)
                reg_entry = ent_reg.async_get(entity_id)
                if reg_entry is not None:
                    config_key = reg_entry.unique_id
                else:
                    config_key = entity_id.split(".", 1)[1]

            # Verify deletion restriction
            _verify_deletion_restriction(hass, SCRIPT_DOMAIN, config_key)

            path = hass.config.path(SCRIPT_CONFIG_PATH)
            lock = hass.data[DOMAIN]["script_lock"]

            async with lock:
                current = await hass.async_add_executor_job(_read_yaml, path)
                if current is None:
                    current = {}
                elif not isinstance(current, dict):
                    raise ValueError("scripts.yaml is not a dictionary")

                if config_key not in current:
                    raise ValueError(f"Script with ID '{config_key}' not found")

                current.pop(config_key)
                await hass.async_add_executor_job(_write_yaml, path, current)

            # Remove from entity registry
            ent_reg = er.async_get(hass)
            reg_entity_id = ent_reg.async_get_entity_id(
                SCRIPT_DOMAIN, SCRIPT_DOMAIN, config_key
            )
            if reg_entity_id is not None:
                ent_reg.async_remove(reg_entity_id)

            # Reload scripts to apply deletion
            await hass.services.async_call(SCRIPT_DOMAIN, SERVICE_RELOAD)
            _LOGGER.info("Successfully deleted script '%s'", config_key)
            return {"success": True, "id": config_key}

        except Exception as err:
            _LOGGER.error("Failed to delete script: %s", err)
            return {"success": False, "error": str(err)}

    # Register services
    hass.services.async_register(
        DOMAIN,
        "create_automation",
        async_create_automation,
        schema=CREATE_AUTOMATION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "delete_automation",
        async_delete_automation,
        schema=DELETE_AUTOMATION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "create_script",
        async_create_script,
        schema=CREATE_SCRIPT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "delete_script",
        async_delete_script,
        schema=DELETE_SCRIPT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Setup intents for LLM tools conditionally
    expose_llm_tools = entry.options.get("expose_llm_tools", True)
    if expose_llm_tools:
        from .intent import async_setup_intents
        await async_setup_intents(hass)

    # Register update listener for option changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options listener, reloads the config entry to apply changes."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    for service in ("create_automation", "delete_automation", "create_script", "delete_script"):
        hass.services.async_remove(DOMAIN, service)

    # Unregister intents
    from homeassistant.helpers import intent
    for intent_type in ("CreateAutomation", "DeleteAutomation", "CreateScript", "DeleteScript"):
        try:
            intent.async_remove(hass, intent_type)
        except HomeAssistantError:
            pass

    hass.data.pop(DOMAIN, None)
    return True
