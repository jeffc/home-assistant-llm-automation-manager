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
        vol.Optional("icon"): cv.string,
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
        vol.Optional("category_id"): cv.string,
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
        vol.Optional("icon"): cv.string,
        vol.Optional("sequence"): cv.match_all,
        vol.Optional("mode"): cv.string,
        vol.Optional("on_completion", default="persist"): vol.In(
            ["delete_self", "persist"]
        ),
        vol.Optional("expose_to_ai", default=False): cv.boolean,
        vol.Optional("validate_only", default=False): cv.boolean,
        vol.Optional("category_id"): cv.string,
    }
)

DELETE_SCRIPT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
    }
)
GET_ALLOWED_ACTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("verbose", default=False): cv.boolean,
    }
)

GET_ENTITY_TRACES_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("run_id"): cv.string,
    }
)

GET_TEMPLATE_HELPER_DOCS_SCHEMA = vol.Schema(
    {
        vol.Optional("search_term"): cv.string,
        vol.Optional("only_custom", default=True): cv.boolean,
    }
)

RENDER_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required("template"): cv.string,
        vol.Optional("variables"): dict,
    }
)

GET_COMMON_ICONS_SCHEMA = vol.Schema(
    {
        vol.Optional("search_term"): cv.string,
        vol.Optional("icon_to_validate"): cv.string,
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


def is_action_allowed_by_regex(
    action: str, allow_regexes_str: str, disallow_regexes_str: str
) -> bool:
    """Check action name against allow/deny lists using regular expressions."""
    import re

    allow_lines = [
        line.strip()
        for line in allow_regexes_str.splitlines()
        if line.strip()
    ]
    disallow_lines = [
        line.strip()
        for line in disallow_regexes_str.splitlines()
        if line.strip()
    ]

    has_allow = len(allow_lines) > 0
    has_disallow = len(disallow_lines) > 0

    def matches_any(patterns: list[str]) -> bool:
        for pat in patterns:
            try:
                if re.search(pat, action):
                    return True
            except re.error:
                pass
        return False

    if has_allow and not has_disallow:
        return matches_any(allow_lines)

    if has_disallow and not has_allow:
        return not matches_any(disallow_lines)

    if has_allow and has_disallow:
        if matches_any(disallow_lines):
            return False
        return matches_any(allow_lines)

    return True


def is_action_allowed_by_regex_with_reason(
    action: str, allow_regexes_str: str, disallow_regexes_str: str
) -> tuple[bool, str]:
    """Check an action name against allow/deny lists of regular expressions.

    Splits the allow and deny multiline strings into individual lines,
    ignores empty lines and lines starting with '#' (comments), and matches the
    action string against each pattern.

    Returns:
        A tuple of (bool, str) representing (is_allowed, reason_for_decision).
    """
    import re

    # Parse and clean the allowed regular expressions list.
    # We strip whitespace and filter out any comments or empty lines.
    allow_lines = [
        line.strip()
        for line in allow_regexes_str.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # Parse and clean the denied regular expressions list.
    disallow_lines = [
        line.strip()
        for line in disallow_regexes_str.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    has_allow = len(allow_lines) > 0
    has_disallow = len(disallow_lines) > 0

    # Helper function to find the first pattern matching the action name.
    def find_matching_pattern(patterns: list[str]) -> str | None:
        for pat in patterns:
            try:
                if re.search(pat, action):
                    return pat
            except re.error:
                # Silently ignore invalid regular expressions in configuration.
                pass
        return None

    # Scenario 1: Only the allow list is specified.
    # The action must match at least one allow pattern to be permitted.
    if has_allow and not has_disallow:
        match = find_matching_pattern(allow_lines)
        if match:
            return True, f"Allowed by regex allowlist (matched '{match}')"
        return (
            False,
            "Blocked because it did not match any pattern in the regex allowlist",
        )

    # Scenario 2: Only the disallow/deny list is specified.
    # The action is allowed unless it matches at least one deny pattern.
    if has_disallow and not has_allow:
        match = find_matching_pattern(disallow_lines)
        if match:
            return False, f"Blocked by regex denylist (matched '{match}')"
        return (
            True,
            "Allowed because it did not match any pattern in the regex denylist",
        )

    # Scenario 3: Both allow and disallow lists are specified.
    # 1. Deny list is checked first. If matched, the action is blocked.
    # 2. Allow list is checked second. If matched, the action is allowed.
    # 3. If it matches neither, it is blocked.
    if has_allow and has_disallow:
        match_deny = find_matching_pattern(disallow_lines)
        if match_deny:
            return False, f"Blocked by regex denylist (matched '{match_deny}')"
        match_allow = find_matching_pattern(allow_lines)
        if match_allow:
            return True, f"Allowed by regex allowlist (matched '{match_allow}')"
        return (
            False,
            "Blocked because it did not match any pattern in either regex list",
        )

    # Scenario 4: Neither list is specified.
    # All actions are permitted by default.
    return True, "Allowed by default (no regex lists specified)"


def is_action_allowed_with_reason(
    domain: str, service: str, options: dict[str, Any]
) -> tuple[bool, str]:
    """Determine whether an action is allowed based on the integration options.

    Constructs the full action identifier (domain.service) and checks it
    against the configured regular expression filters.

    Returns:
        A tuple of (bool, str) representing (is_allowed, reason).
    """
    action = f"{domain}.{service}"
    # Retrieve the allow and disallow lists from options (defaulting to empty strings).
    allow_regexes = options.get("allow_regexes", "")
    disallow_regexes = options.get("disallow_regexes", "")

    # Delegate the evaluation to the regex check function.
    return is_action_allowed_by_regex_with_reason(
        action, allow_regexes, disallow_regexes
    )


def is_action_allowed(
    domain: str, service: str, options: dict[str, Any]
) -> bool:
    """Resolve allowed/denied action based on config options."""
    allowed, _ = is_action_allowed_with_reason(domain, service, options)
    return allowed


async def async_fetch_entity_traces(
    hass: HomeAssistant, entity_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Fetch trace history and detailed trace steps for an automation/script."""
    if "." not in entity_id:
        raise HomeAssistantError(f"Invalid entity ID '{entity_id}'")

    domain, _ = entity_id.split(".", 1)
    if domain not in ("automation", "script"):
        raise HomeAssistantError(
            f"Entity domain '{domain}' is not supported for tracing. "
            "Only 'automation' and 'script' are supported."
        )

    # Check if trace component is active
    from homeassistant.components.trace import DATA_TRACE
    if DATA_TRACE not in hass.data:
        raise HomeAssistantError("Trace component is not active or loaded")

    from homeassistant.components.trace.websocket_api import (
        async_list_traces,
        async_get_trace,
    )
    import datetime

    # Fetch traces list
    try:
        traces = await async_list_traces(hass, domain, entity_id)
    except Exception as err:
        raise HomeAssistantError(
            f"Failed to list traces for {entity_id}: {err}"
        ) from err

    # Sort traces descending by start timestamp (newest first)
    def get_start_time(t: dict[str, Any]) -> datetime.datetime:
        ts = t.get("timestamp", {})
        dt = ts.get("start") if ts else None
        if isinstance(dt, datetime.datetime):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        return datetime.datetime(1, 1, 1, tzinfo=datetime.timezone.utc)

    traces.sort(key=get_start_time, reverse=True)

    # 5 most recent runs
    recent_runs = []
    for t in traces[:5]:
        start_time = None
        ts = t.get("timestamp", {})
        if ts and ts.get("start"):
            dt = ts["start"]
            if hasattr(dt, "isoformat"):
                start_time = dt.isoformat()
            else:
                start_time = str(dt)
        recent_runs.append({
            "run_id": t.get("run_id"),
            "state": t.get("state"),
            "start_time": start_time,
            "error": t.get("error"),
        })

    # Find detailed run
    detailed_run_data = None
    selected_run_id = run_id
    if not selected_run_id and traces:
        selected_run_id = traces[0].get("run_id")

    if selected_run_id:
        try:
            detailed_run_data = await async_get_trace(
                hass, entity_id, selected_run_id
            )
        except KeyError:
            pass
        except Exception as err:
            _LOGGER.warning(
                "Error getting detailed trace for %s and run_id %s: %s",
                entity_id,
                selected_run_id,
                err,
            )

    steps = []
    config = None
    blueprint_inputs = None
    if detailed_run_data:
        config = detailed_run_data.get("config")
        blueprint_inputs = detailed_run_data.get("blueprint_inputs")

        raw_trace_steps = detailed_run_data.get("trace", {})
        for path_key, trace_list in raw_trace_steps.items():
            for item in trace_list:
                t_val = item.get("timestamp")
                timestamp_str = None
                if t_val:
                    if hasattr(t_val, "isoformat"):
                        timestamp_str = t_val.isoformat()
                    else:
                        timestamp_str = str(t_val)

                step_info = {
                    "path": item.get("path"),
                    "timestamp": timestamp_str,
                }
                if item.get("changed_variables"):
                    step_info["changed_variables"] = item["changed_variables"]
                if item.get("error"):
                    step_info["error"] = item["error"]
                if item.get("template_errors"):
                    step_info["template_errors"] = item["template_errors"]
                if item.get("result"):
                    step_info["result"] = item["result"]

                # Sort key helper
                def get_t_val(val: Any) -> datetime.datetime:
                    if isinstance(val, datetime.datetime):
                        if val.tzinfo is None:
                            return val.replace(tzinfo=datetime.timezone.utc)
                        return val
                    return datetime.datetime(
                        1, 1, 1, tzinfo=datetime.timezone.utc
                    )

                steps.append((get_t_val(t_val), step_info))

        steps.sort(key=lambda x: x[0])
        steps = [x[1] for x in steps]

    detailed_run = None
    if selected_run_id:
        detailed_run = {
            "run_id": selected_run_id,
            "steps": steps,
        }
        if config:
            detailed_run["config"] = config
        if blueprint_inputs:
            detailed_run["blueprint_inputs"] = blueprint_inputs

    return {
        "recent_runs": recent_runs,
        "detailed_run": detailed_run,
    }


def _validate_templates(hass: HomeAssistant, data: Any) -> None:
    """Recursively validate Jinja2 template strings in config data."""
    from homeassistant.helpers.template import is_template_string, Template

    if isinstance(data, dict):
        for val in data.values():
            _validate_templates(hass, val)
    elif isinstance(data, list):
        for item in data:
            _validate_templates(hass, item)
    elif isinstance(data, str):
        if is_template_string(data):
            try:
                Template(data, hass).ensure_valid()
            except Exception as err:
                raise ValueError(
                    f"Invalid Jinja2 template '{data}': {err}"
                ) from err


async def async_get_template_helper_docs(
    hass: HomeAssistant,
    search_term: str | None = None,
    only_custom: bool = True,
) -> dict[str, Any]:
    """Compile documentation for available Jinja2 template helpers."""
    from homeassistant.helpers.template import TemplateEnvironment
    import jinja2.defaults
    import inspect

    env = TemplateEnvironment(hass)

    # Standard Jinja2 defaults
    std_filters = set(jinja2.defaults.DEFAULT_FILTERS.keys())
    std_tests = set(jinja2.defaults.DEFAULT_TESTS.keys())
    std_globals = {"range", "dict", "lipsum", "cycler", "joiner", "namespace"}

    categories = {
        "globals": env.globals,
        "filters": env.filters,
        "tests": env.tests,
    }

    result = {
        "globals": [],
        "filters": [],
        "tests": [],
    }

    for cat_name, helpers in categories.items():
        for name, func in helpers.items():
            # Apply only_custom filter
            if only_custom:
                if cat_name == "filters" and name in std_filters:
                    continue
                if cat_name == "tests" and name in std_tests:
                    continue
                if cat_name == "globals" and name in std_globals:
                    continue

            # Get description and signature
            doc = "No description available."
            sig = "(...)"
            if callable(func):
                if func.__doc__:
                    doc = func.__doc__.strip()
                try:
                    sig = str(inspect.signature(func))
                except (ValueError, TypeError):
                    pass

            # Apply search_term filter
            if search_term:
                term = search_term.lower()
                if term not in name.lower() and term not in doc.lower():
                    continue

            result[cat_name].append({
                "name": name,
                "signature": sig,
                "description": doc,
            })

    # Sort results alphabetically
    for key in result:
        result[key].sort(key=lambda x: x["name"])

    return result


COMMON_ICONS = [
    {
        "icon": "mdi:lightbulb",
        "description": "Standard light bulb, good for lights and lamps",
        "category": "lights",
    },
    {
        "icon": "mdi:lightbulb-outline",
        "description": "Outlined light bulb, good for ambient lights",
        "category": "lights",
    },
    {
        "icon": "mdi:led-strip",
        "description": "LED strip light, good for accent/strip lighting",
        "category": "lights",
    },
    {
        "icon": "mdi:switch",
        "description": "Generic switch or toggle",
        "category": "switches",
    },
    {
        "icon": "mdi:power-socket-us",
        "description": "Wall outlet/plug, good for smart plugs",
        "category": "switches",
    },
    {
        "icon": "mdi:thermostat",
        "description": "Thermostat, good for climate controls",
        "category": "climate",
    },
    {
        "icon": "mdi:air-conditioner",
        "description": "Air conditioner",
        "category": "climate",
    },
    {
        "icon": "mdi:fan",
        "description": "Ceiling or floor fan",
        "category": "climate",
    },
    {
        "icon": "mdi:fire",
        "description": "Flame, good for heaters or fireplaces",
        "category": "climate",
    },
    {
        "icon": "mdi:snowflake",
        "description": "Snowflake, good for cooling/AC",
        "category": "climate",
    },
    {
        "icon": "mdi:door-closed",
        "description": "Closed door, good for door sensors",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:door-open",
        "description": "Open door, good for entry alerts",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:window-closed",
        "description": "Closed window",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:window-open",
        "description": "Open window",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:garage",
        "description": "Closed garage door",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:garage-open",
        "description": "Open garage door",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:blinds",
        "description": "Window blinds or shades",
        "category": "doors_windows",
    },
    {
        "icon": "mdi:television",
        "description": "TV/Television",
        "category": "media",
    },
    {
        "icon": "mdi:speaker",
        "description": "Smart speaker or sound system",
        "category": "media",
    },
    {
        "icon": "mdi:volume-high",
        "description": "Speaker icon with waves, good for volume/audio",
        "category": "media",
    },
    {
        "icon": "mdi:remote",
        "description": "Remote control",
        "category": "media",
    },
    {
        "icon": "mdi:camera",
        "description": "Security camera feed",
        "category": "security",
    },
    {
        "icon": "mdi:shield-home",
        "description": "Home shield, good for alarm status",
        "category": "security",
    },
    {
        "icon": "mdi:lock",
        "description": "Locked padlock, good for smart locks",
        "category": "security",
    },
    {
        "icon": "mdi:lock-open",
        "description": "Unlocked padlock",
        "category": "security",
    },
    {
        "icon": "mdi:alarm-bell",
        "description": "Ringing bell, good for alarms and alerts",
        "category": "security",
    },
    {
        "icon": "mdi:motion-sensor",
        "description": "Motion sensor, good for occupancy detection",
        "category": "security",
    },
    {
        "icon": "mdi:account",
        "description": "User/person profile, good for presence detection",
        "category": "presence",
    },
    {
        "icon": "mdi:walk",
        "description": "Walking person, good for motion/presence",
        "category": "presence",
    },
    {
        "icon": "mdi:car",
        "description": "Car, good for vehicle tracking/garage automation",
        "category": "presence",
    },
    {
        "icon": "mdi:home-assistant",
        "description": "Home Assistant logo icon",
        "category": "general",
    },
    {
        "icon": "mdi:cog",
        "description": "Gear, good for settings or system scripts",
        "category": "general",
    },
    {
        "icon": "mdi:bell",
        "description": "Notification bell, good for announcements",
        "category": "general",
    },
    {
        "icon": "mdi:alert",
        "description": "Warning triangle, good for error notifications",
        "category": "general",
    },
    {
        "icon": "mdi:check-circle",
        "description": "Checkmark in circle, good for success scripts",
        "category": "general",
    },
    {
        "icon": "mdi:refresh",
        "description": "Circular refresh arrows, good for reloads/updates",
        "category": "general",
    },
    {
        "icon": "mdi:clock",
        "description": "Clock, good for time-based automations",
        "category": "general",
    },
    {
        "icon": "mdi:weather-sunny",
        "description": "Sun, good for daytime/sunset automations",
        "category": "general",
    },
]


def async_get_common_icons(
    hass: HomeAssistant,
    search_term: str | None = None,
    icon_to_validate: str | None = None,
) -> dict[str, Any]:
    """Search common home automation icons and active server icons, or validate an icon."""
    # Collect and count frequencies of active icons from current server states and entity registry
    active_icon_counts = {}
    try:
        for state in hass.states.async_all():
            icon = state.attributes.get("icon")
            if icon and isinstance(icon, str) and icon.startswith("mdi:"):
                active_icon_counts[icon] = active_icon_counts.get(icon, 0) + 1

        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        if hasattr(ent_reg, "entities"):
            for entry in ent_reg.entities.values():
                icon = entry.icon or entry.original_icon
                if icon and isinstance(icon, str) and icon.startswith("mdi:"):
                    active_icon_counts[icon] = active_icon_counts.get(icon, 0) + 1
    except Exception as err:
        _LOGGER.warning("Failed to collect active server icons: %s", err)

    # Sort active icons by frequency (highest first) and cap at 30 to avoid context clutter
    sorted_active = sorted(active_icon_counts.items(), key=lambda x: x[1], reverse=True)
    top_active = [icon for icon, _ in sorted_active[:30]]

    combined_list = list(COMMON_ICONS)
    existing_icons = {item["icon"] for item in combined_list}
    for active_icon in top_active:
        if active_icon not in existing_icons:
            combined_list.append(
                {
                    "icon": active_icon,
                    "description": "Active icon in use on this server",
                    "category": "active_server_icon",
                }
            )

    result = {}

    if icon_to_validate:
        import json
        import os
        import hass_frontend

        name = icon_to_validate.lower()
        if name.startswith("mdi:"):
            name = name[4:]

        frontend_path = hass_frontend.__path__[0]
        json_path = os.path.join(frontend_path, "static", "mdi", "iconList.json")

        valid = False
        if os.path.exists(json_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    all_icons = json.load(f)
                valid = any(item.get("name") == name for item in all_icons)
            except Exception as err:
                _LOGGER.warning("Failed to load iconList.json for validation: %s", err)
                valid = ":" in icon_to_validate
        else:
            valid = ":" in icon_to_validate
        result["valid"] = valid

    if search_term is not None or not icon_to_validate:
        term = (search_term or "").strip().lower()
        matches = []
        for item in combined_list:
            if (
                not term
                or term in item["icon"].lower()
                or term in item["description"].lower()
                or term in item["category"].lower()
            ):
                matches.append(item)
                if len(matches) >= 50:
                    break
        result["icons"] = matches

    return result


async def async_evaluate_template(
    hass: HomeAssistant,
    template_str: str,
    variables: dict[str, Any] | None = None,
) -> str:
    """Evaluate a Jinja2 template and return the rendered string result."""
    from homeassistant.helpers.template import Template
    try:
        res = Template(template_str, hass).async_render(variables)
        return str(res)
    except Exception as err:
        raise HomeAssistantError(
            f"Failed to render template: {err}"
        ) from err


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
    category_id: str | None = None,
    icon: str | None = None,
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
    if entry:
        tag = entry.options.get("tag", "").strip()
        one_shot_tag = entry.options.get("one_shot_tag", "").strip()

    tags = []
    if tag:
        tags.append(tag)
    if is_one_shot and one_shot_tag:
        tags.append(one_shot_tag)

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

    # Assign category if configured
    options = entry.options if entry else {}
    target_category_id = None
    categorize_mode = options.get("categorize_mode", "leave_uncategorized")

    if categorize_mode == "put_in_specified":
        if domain == AUTOMATION_DOMAIN:
            target_category_id = options.get("specified_automation_category")
        elif domain == SCRIPT_DOMAIN:
            target_category_id = options.get("specified_script_category")
    elif categorize_mode == "auto_categorize" and category_id:
        target_category_id = category_id

    if target_category_id:
        import homeassistant.helpers.category_registry as cr
        category_reg = cr.async_get(hass)
        category = category_reg.async_get_category(
            scope=domain, category_id=target_category_id
        )
        if category:
            ent_reg.async_update_entity(
                entity_id,
                categories={domain: target_category_id}
            )
            _LOGGER.info(
                "Assigned category '%s' (%s) to entity '%s'",
                category.name,
                target_category_id,
                entity_id,
            )
        else:
            _LOGGER.warning(
                "Category ID '%s' not found for scope '%s', skipped assignment",
                target_category_id,
                domain,
            )

    # Set icon if configured
    if icon:
        try:
            ent_reg.async_update_entity(entity_id, icon=icon)
            _LOGGER.info("Set icon '%s' for entity '%s'", icon, entity_id)
        except Exception as err:
            _LOGGER.warning(
                "Failed to set icon '%s' for entity '%s': %s",
                icon,
                entity_id,
                err,
            )

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

            entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
            options = entry.options if entry else {}

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
                if not is_action_allowed(domain, service, options):
                    raise ValueError(
                        f"Action '{act}' is blocked by security policy"
                    )

            # Validate any template syntax recursively
            _validate_templates(hass, config_data)

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
            category_id = call.data.get("category_id")
            icon = call.data.get("icon")
            await _async_post_create_processing(
                hass,
                AUTOMATION_DOMAIN,
                config_key,
                expose_to_ai,
                is_one_shot=is_one_shot,
                category_id=category_id,
                icon=icon,
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

            # Turn off automation before deleting it from YAML/registry
            ent_reg = er.async_get(hass)
            reg_entity_id = entity_id or ent_reg.async_get_entity_id(
                AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, config_key
            )
            if reg_entity_id:
                try:
                    await hass.services.async_call(
                        AUTOMATION_DOMAIN,
                        "turn_off",
                        {"entity_id": reg_entity_id},
                    )
                    _LOGGER.info(
                        "Turned off automation '%s' before deletion",
                        reg_entity_id,
                    )
                except Exception as err:
                    _LOGGER.warning(
                        "Failed to turn off automation '%s' before deletion: %s",
                        reg_entity_id,
                        err,
                    )

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
            for key in ("alias", "description", "sequence", "mode", "icon"):
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

            entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
            options = entry.options if entry else {}

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
                if not is_action_allowed(domain, service, options):
                    raise ValueError(
                        f"Action '{act}' is blocked by security policy"
                    )

            # Validate any template syntax recursively
            _validate_templates(hass, config_data)

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
            category_id = call.data.get("category_id")
            icon = call.data.get("icon")
            await _async_post_create_processing(
                hass,
                SCRIPT_DOMAIN,
                config_key,
                expose_to_ai,
                is_one_shot=is_one_shot,
                category_id=category_id,
                icon=icon,
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

    async def async_get_allowed_actions(call: ServiceCall) -> ServiceResponse:
        """Retrieve allowed and blocked actions."""
        domain_services = hass.services.async_services()
        verbose = call.data.get("verbose", False)

        allowed = {}
        blocked = {}

        for dom, svcs in sorted(domain_services.items()):
            for svc in sorted(svcs.keys()):
                is_allowed, reason = is_action_allowed_with_reason(
                    dom, svc, entry.options
                )
                if is_allowed:
                    if dom not in allowed:
                        allowed[dom] = {} if verbose else []
                    if verbose:
                        allowed[dom][svc] = reason
                    else:
                        allowed[dom].append(svc)
                else:
                    if dom not in blocked:
                        blocked[dom] = {} if verbose else []
                    if verbose:
                        blocked[dom][svc] = reason
                    else:
                        blocked[dom].append(svc)

        return {"allowed": allowed, "blocked": blocked}

    hass.services.async_register(
        DOMAIN,
        "get_allowed_actions",
        async_get_allowed_actions,
        schema=GET_ALLOWED_ACTIONS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def async_get_entity_traces(call: ServiceCall) -> ServiceResponse:
        """Fetch trace history and logs for a specific automation/script."""
        entity_id = call.data["entity_id"]
        run_id = call.data.get("run_id")
        try:
            return await async_fetch_entity_traces(hass, entity_id, run_id)
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to fetch traces: {err}"
            ) from err

    hass.services.async_register(
        DOMAIN,
        "get_entity_traces",
        async_get_entity_traces,
        schema=GET_ENTITY_TRACES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def async_get_template_helper_docs_service(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Fetch documentation for Jinja2 template helpers."""
        search_term = call.data.get("search_term")
        only_custom = call.data.get("only_custom", True)
        try:
            return await async_get_template_helper_docs(
                hass, search_term, only_custom
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to fetch template helper docs: {err}"
            ) from err

    hass.services.async_register(
        DOMAIN,
        "get_template_helper_docs",
        async_get_template_helper_docs_service,
        schema=GET_TEMPLATE_HELPER_DOCS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def async_render_template_service(call: ServiceCall) -> ServiceResponse:
        """Render a Jinja2 template with optional variables."""
        template_str = call.data["template"]
        variables = call.data.get("variables")
        try:
            rendered = await async_evaluate_template(
                hass, template_str, variables
            )
            return {"result": rendered}
        except Exception as err:
            raise HomeAssistantError(
                f"Template rendering failed: {err}"
            ) from err

    hass.services.async_register(
        DOMAIN,
        "render_template",
        async_render_template_service,
        schema=RENDER_TEMPLATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def async_get_common_icons_service(call: ServiceCall) -> ServiceResponse:
        """Get common or active home automation icons, or validate an icon."""
        search_term = call.data.get("search_term")
        icon_to_validate = call.data.get("icon_to_validate")
        results = async_get_common_icons(hass, search_term, icon_to_validate)
        return results

    hass.services.async_register(
        DOMAIN,
        "get_common_icons",
        async_get_common_icons_service,
        schema=GET_COMMON_ICONS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
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
    for service in (
        "create_automation",
        "delete_automation",
        "create_script",
        "delete_script",
        "get_allowed_actions",
        "get_entity_traces",
        "get_template_helper_docs",
        "render_template",
        "get_common_icons",
    ):
        hass.services.async_remove(DOMAIN, service)

    # Unregister intents
    from homeassistant.helpers import intent
    for intent_type in (
        "CreateAutomation",
        "DeleteAutomation",
        "CreateScript",
        "DeleteScript",
        "GetEntityTraces",
        "GetTemplateHelperDocs",
        "RenderTemplate",
        "GetCommonIcons",
    ):
        try:
            intent.async_remove(hass, intent_type)
        except HomeAssistantError:
            pass

    hass.data.pop(DOMAIN, None)
    return True
