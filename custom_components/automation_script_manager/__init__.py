"""The Automation & Script Manager integration."""

import logging
import os
import uuid
import asyncio
import json
import ast
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.const import CONF_ID, SERVICE_RELOAD
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
        vol.Optional("expose_to_ai", default=False): cv.boolean,
        vol.Optional("validate_only", default=False): cv.boolean,
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
        vol.Optional("expose_to_ai", default=False): cv.boolean,
        vol.Optional("validate_only", default=False): cv.boolean,
    }
)

DELETE_SCRIPT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
    }
)

def _parse_json_fallback(value: Any) -> Any:
    """Parse JSON/Python string if value is wrapped in a dict or is a string itself."""
    if isinstance(value, dict) and "json" in value:
        val_json = value["json"]
        if isinstance(val_json, str):
            try:
                return json.loads(val_json)
            except Exception:
                try:
                    return ast.literal_eval(val_json)
                except Exception:
                    pass
    elif isinstance(value, str):
        trimmed = value.strip()
        is_list = trimmed.startswith("[") and trimmed.endswith("]")
        is_dict = trimmed.startswith("{") and trimmed.endswith("}")
        if is_list or is_dict:
            try:
                return json.loads(trimmed)
            except Exception:
                try:
                    return ast.literal_eval(trimmed)
                except Exception:
                    pass
    return value

def _extract_entity_ids(data: Any) -> set[str]:
    """Recursively extract all entity IDs from triggers, conditions, or actions."""
    entity_ids = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("entity_id", "entity_ids"):
                if isinstance(value, str):
                    entity_ids.add(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            entity_ids.add(item)
            else:
                entity_ids.update(_extract_entity_ids(value))
    elif isinstance(data, list):
        for item in data:
            entity_ids.update(_extract_entity_ids(item))

    # Skip templates and 'this' references
    valid_entity_ids = set()
    for ent in entity_ids:
        if isinstance(ent, str):
            ent = ent.strip()
            if "{" in ent or "}" in ent:
                continue
            if ent.startswith("this.") or ent == "this":
                continue
            valid_entity_ids.add(ent)
    return valid_entity_ids


def _extract_actions(data: Any) -> set[str]:
    """Recursively extract all action names from actions list."""
    actions = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("action", "service"):
                if isinstance(value, str) and "." in value:
                    actions.add(value)
            else:
                actions.update(_extract_actions(value))
    elif isinstance(data, list):
        for item in data:
            actions.update(_extract_actions(item))
    return actions


def _read_yaml(path: str) -> Any:
    """Read YAML helper."""
    if not os.path.isfile(path):
        return None
    return load_yaml(path)

def _write_yaml(path: str, data: Any) -> None:
    """Write YAML helper atomically."""
    contents = dump(data)
    write_utf8_file_atomic(path, contents)

async def _async_post_create_processing(
    hass: HomeAssistant,
    domain: str,
    config_key: str,
    expose_to_ai: bool,
    is_one_shot: bool = False,
) -> None:
    """Assign tag and expose entity to AI helper."""
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
            "Could not find registered entity for %s.%s to assign tag/expose",
            domain,
            config_key,
        )
        return

    # Retrieve options
    entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
    tag = ""
    one_shot_tag = ""
    disable_instead_of_delete = False
    would_be_deleted_tag = "would-be-deleted"
    if entry:
        tag = entry.options.get("tag", "").strip()
        one_shot_tag = entry.options.get("one_shot_tag", "").strip()
        disable_instead_of_delete = entry.options.get(
            "disable_instead_of_delete", False
        )
        would_be_deleted_tag = entry.options.get(
            "would_be_deleted_tag", "would-be-deleted"
        ).strip()

    tags = []
    if tag:
        tags.append(tag)
    if is_one_shot and one_shot_tag:
        tags.append(one_shot_tag)
    if is_one_shot and disable_instead_of_delete and would_be_deleted_tag:
        tags.append(would_be_deleted_tag)

    # Assign tags if configured
    if tags:
        label_reg = lr.async_get(hass)
        label_ids = set()
        for t in tags:
            label = label_reg.async_get_label_by_name(t)
            if label is None:
                try:
                    label = label_reg.async_create(t)
                except ValueError:
                    # Fallback if label is already in use by name (concurrency)
                    label = next(
                        (
                            l
                            for l in label_reg.labels.values()
                            if l.name.lower() == t.lower()
                        ),
                        None,
                    )
            if label:
                label_ids.add(label.label_id)

        if label_ids:
            reg_entry = ent_reg.async_get(entity_id)
            if reg_entry:
                new_labels = reg_entry.labels | label_ids
                ent_reg.async_update_entity(entity_id, labels=new_labels)
                _LOGGER.info("Assigned tags %s to entity '%s'", tags, entity_id)

    # Expose to voice assistant/AI if requested
    if expose_to_ai:
        try:
            from homeassistant.components.homeassistant.exposed_entities import (
                async_expose_entity,
            )
            async_expose_entity(hass, "conversation", entity_id, True)
            _LOGGER.info("Exposed entity '%s' to AI (conversation)", entity_id)
        except Exception as err:
            _LOGGER.error("Failed to expose entity '%s' to AI: %s", entity_id, err)

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
            f"Deletion restricted: {domain.capitalize()} '{config_key}' "
            f"does not have the required tag '{tag}'"
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
            validate_only = call.data.get("validate_only", False)
            config_data = {}

            if "config" in call.data:
                parsed_config = _parse_json_fallback(call.data["config"])
                if isinstance(parsed_config, dict):
                    config_data.update(parsed_config)

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
                    config_data[key] = _parse_json_fallback(call.data[key])

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

            # Validate trigger is provided and not empty
            user_triggers = config_data.get("trigger") or config_data.get("triggers")
            if not user_triggers:
                raise ValueError("Automation must contain at least one trigger.")
            if isinstance(user_triggers, list) and not user_triggers:
                raise ValueError("Automation must contain at least one trigger.")

            # Validate action is provided and not empty
            user_actions = config_data.get("action") or config_data.get("actions")
            if not user_actions:
                raise ValueError("Automation must contain at least one action.")
            if isinstance(user_actions, list) and not user_actions:
                raise ValueError("Automation must contain at least one action.")

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

            # Extract and validate all entity IDs referenced
            entity_ids = _extract_entity_ids(config_data)
            ent_reg = er.async_get(hass)
            for ent in entity_ids:
                if "." not in ent:
                    raise ValueError(f"Entity ID '{ent}' is invalid")
                if (
                    hass.states.get(ent) is None
                    and ent_reg.async_get(ent) is None
                ):
                    raise ValueError(
                        f"Entity ID '{ent}' does not exist in Home Assistant"
                    )

            # Extract and validate all action names referenced
            actions_list = _extract_actions(config_data)
            domain_services = hass.services.async_services()
            for act in actions_list:
                if "." not in act:
                    raise ValueError(
                        f"Action '{act}' must be in the format 'domain.action'"
                    )
                domain, service = act.split(".", 1)
                if (
                    domain not in domain_services
                    or service not in domain_services[domain]
                ):
                    raise ValueError(
                        f"Action '{act}' is not registered in Home Assistant"
                    )

            # Validate the configuration
            await async_validate_automation_item(hass, config_key, config_data)

            if validate_only:
                _LOGGER.info(
                    "Dry-run validation successful for automation '%s'",
                    config_key,
                )
                return {"success": True, "id": config_key}

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

            # Assign tag and expose if configured
            is_one_shot = on_completion != "persist"
            expose_to_ai = call.data.get("expose_to_ai", False)
            await _async_post_create_processing(
                hass,
                AUTOMATION_DOMAIN,
                config_key,
                expose_to_ai,
                is_one_shot=is_one_shot,
            )

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

            disable_instead_of_delete = entry.options.get(
                "disable_instead_of_delete", False
            )
            would_be_deleted_tag = entry.options.get(
                "would_be_deleted_tag", "would-be-deleted"
            ).strip()

            if disable_instead_of_delete:
                path = hass.config.path(AUTOMATION_CONFIG_PATH)
                lock = hass.data[DOMAIN]["automation_lock"]

                async with lock:
                    current = await hass.async_add_executor_job(_read_yaml, path)
                    if current is None:
                        current = []
                    elif not isinstance(current, list):
                        raise ValueError("automations.yaml is not a list")

                    found = False
                    for index, cur_value in enumerate(current):
                        if (
                            isinstance(cur_value, dict)
                            and cur_value.get("id") == config_key
                        ):
                            cur_value["initial_state"] = False
                            found = True
                            break

                    if not found:
                        raise ValueError(
                            f"Automation with ID '{config_key}' not found"
                        )

                    await hass.async_add_executor_job(_write_yaml, path, current)

                # Reload automations
                await hass.services.async_call(AUTOMATION_DOMAIN, SERVICE_RELOAD)

                # Resolve entity_id to turn it off and apply the tag
                ent_reg = er.async_get(hass)
                reg_entity_id = entity_id or ent_reg.async_get_entity_id(
                    AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, config_key
                )

                if reg_entity_id:
                    # Turn off automation
                    await hass.services.async_call(
                        AUTOMATION_DOMAIN,
                        "turn_off",
                        {"entity_id": reg_entity_id},
                    )

                    # Add override tag if configured
                    if would_be_deleted_tag:
                        label_reg = lr.async_get(hass)
                        label = label_reg.async_get_label_by_name(
                            would_be_deleted_tag
                        )
                        if label is None:
                            try:
                                label = label_reg.async_create(
                                    would_be_deleted_tag
                                )
                            except ValueError:
                                label = next(
                                    (
                                        l
                                        for l in label_reg.labels.values()
                                        if l.name.lower()
                                        == would_be_deleted_tag.lower()
                                    ),
                                    None,
                                )
                        if label:
                            label_id = label.label_id
                            reg_entry = ent_reg.async_get(reg_entity_id)
                            if reg_entry:
                                new_labels = reg_entry.labels | {label_id}
                                ent_reg.async_update_entity(
                                    reg_entity_id, labels=new_labels
                                )

                _LOGGER.info(
                    "Delete override: Disabled automation '%s' instead of deleting",
                    config_key,
                )
                return {"success": True, "id": config_key}

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
            validate_only = call.data.get("validate_only", False)

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
                    f"Script ID '{config_key}' is not a valid slug (use only "
                    f"lowercase letters, numbers, and underscores): {err}"
                ) from err

            config_data = {}
            if "config" in call.data:
                parsed_config = _parse_json_fallback(call.data["config"])
                if isinstance(parsed_config, dict):
                    config_data.update(parsed_config)

            # Override or set individual fields if provided
            for key in ("alias", "description", "sequence", "mode"):
                if key in call.data:
                    config_data[key] = _parse_json_fallback(call.data[key])

            # Validate sequence is provided and not empty
            user_sequence = config_data.get("sequence")
            if not user_sequence:
                raise ValueError("Script sequence must contain at least one action.")
            if isinstance(user_sequence, list) and not user_sequence:
                raise ValueError("Script sequence must contain at least one action.")

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

            # Extract and validate all entity IDs referenced
            entity_ids = _extract_entity_ids(config_data)
            ent_reg = er.async_get(hass)
            for ent in entity_ids:
                if "." not in ent:
                    raise ValueError(f"Entity ID '{ent}' is invalid")
                if (
                    hass.states.get(ent) is None
                    and ent_reg.async_get(ent) is None
                ):
                    raise ValueError(
                        f"Entity ID '{ent}' does not exist in Home Assistant"
                    )

            # Extract and validate all action names referenced
            actions_list = _extract_actions(config_data)
            domain_services = hass.services.async_services()
            for act in actions_list:
                if "." not in act:
                    raise ValueError(
                        f"Action '{act}' must be in the format 'domain.action'"
                    )
                domain, service = act.split(".", 1)
                if (
                    domain not in domain_services
                    or service not in domain_services[domain]
                ):
                    raise ValueError(
                        f"Action '{act}' is not registered in Home Assistant"
                    )

            # Validate the configuration
            await async_validate_script_item(hass, config_key, config_data)

            if validate_only:
                _LOGGER.info(
                    "Dry-run validation successful for script '%s'",
                    config_key,
                )
                return {"success": True, "id": config_key}

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

            # Assign tag and expose if configured
            is_one_shot = on_completion != "persist"
            expose_to_ai = call.data.get("expose_to_ai", False)
            await _async_post_create_processing(
                hass,
                SCRIPT_DOMAIN,
                config_key,
                expose_to_ai,
                is_one_shot=is_one_shot,
            )

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

            disable_instead_of_delete = entry.options.get(
                "disable_instead_of_delete", False
            )
            would_be_deleted_tag = entry.options.get(
                "would_be_deleted_tag", "would-be-deleted"
            ).strip()

            if disable_instead_of_delete:
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

                    script_config = current[config_key]
                    sequence = script_config.get("sequence") or []
                    if isinstance(sequence, dict):
                        sequence = [sequence]
                    elif not isinstance(sequence, list):
                        sequence = []

                    notification_action = {
                        "action": "persistent_notification.create",
                        "data": {
                            "title": "Disabled Script Called",
                            "message": (
                                f"Warning: Disabled script "
                                f"'{config_key}' was called."
                            ),
                        },
                    }
                    stop_action = {
                        "stop": "Disabled by delete override",
                    }

                    # Check if already modified to prevent double prepend
                    has_notification = False
                    if sequence and isinstance(sequence[0], dict):
                        act_name = sequence[0].get("action")
                        if act_name == "persistent_notification.create":
                            has_notification = True

                    if not has_notification:
                        script_config["sequence"] = [
                            notification_action,
                            stop_action,
                        ] + sequence

                    await hass.async_add_executor_job(_write_yaml, path, current)

                # Reload scripts
                await hass.services.async_call(SCRIPT_DOMAIN, SERVICE_RELOAD)

                # Resolve entity_id to apply the tag
                ent_reg = er.async_get(hass)
                reg_entity_id = entity_id or ent_reg.async_get_entity_id(
                    SCRIPT_DOMAIN, SCRIPT_DOMAIN, config_key
                )

                if reg_entity_id:
                    # Add override tag if configured
                    if would_be_deleted_tag:
                        label_reg = lr.async_get(hass)
                        label = label_reg.async_get_label_by_name(
                            would_be_deleted_tag
                        )
                        if label is None:
                            try:
                                label = label_reg.async_create(
                                    would_be_deleted_tag
                                )
                            except ValueError:
                                label = next(
                                    (
                                        l
                                        for l in label_reg.labels.values()
                                        if l.name.lower()
                                        == would_be_deleted_tag.lower()
                                    ),
                                    None,
                                )
                        if label:
                            label_id = label.label_id
                            reg_entry = ent_reg.async_get(reg_entity_id)
                            if reg_entry:
                                new_labels = reg_entry.labels | {label_id}
                                ent_reg.async_update_entity(
                                    reg_entity_id, labels=new_labels
                                )

                _LOGGER.info(
                    "Delete override: Disabled script '%s' instead of deleting",
                    config_key,
                )
                return {"success": True, "id": config_key}

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
