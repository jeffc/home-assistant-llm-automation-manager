"""Intent handlers for the Automation & Script Manager."""

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class CreateAutomationIntent(intent.IntentHandler):
    """Handle CreateAutomation intent."""

    intent_type = "CreateAutomation"
    description = """Create or update an automation.
Exposes triggers, conditions, and actions.

DECISION GUIDELINE: Creating an automation is appropriate when the user wants
event-driven, conditional, or scheduled behavior (e.g. if the user says 'whenever X, do Y',
'when X occurs, do Y', or 'schedule action Z at time T'). For immediate, on-demand
action execution, prefer creating or running scripts instead.

TEMPLATE GUIDELINE: Always prefer using built-in, non-templated options
(such as numeric state trigger thresholds or standard state triggers) if a
built-in equivalent exists that can accomplish the goal. However, if templates
are necessary for complex triggers, conditions, or other automation logic, you
may write them. If you need to search or inspect the available Jinja2 template
functions, filters, or tests registered in Home Assistant, you must call
`GetTemplateHelperDocs`.

ONE-TIME VS EVERY-TIME GUIDELINE: In your response to the user, you must be clear
about whether the automation is a one-time action or runs every time. If the user
says 'when' or 'next time', assume a one-time automation (and use 'on_completion':
'delete_self' or 'disable_self') unless they explicitly say otherwise. If the user
says 'every time' or 'whenever', that is a cue to make a persistent automation that
runs every time (with 'on_completion': 'persist').

REQUIRED FIELDS GUIDELINE: When calling this tool to create or update an automation,
you MUST always include the trigger(s), any relevant condition(s), AND the action(s)
in the tool call. An automation is invalid and will fail validation if it doesn't
contain at least one action. You must translate the user's requested action outcome
(e.g. 'ping my phone', 'notify me', 'turn on light') into concrete, valid Home Assistant
service action calls and populate the 'action' field. When creating a notification
action, ALWAYS use the `notify.send_message` action (never `notify.notify` or service
names like `notify.jeff`) unless explicitly requested by the user, and target the
correct notify entity ID from the entity registry/list (e.g. targeting
`notify.mobile_app_jeff` or `notify.jeff`).

GATHER THEN ACT GUIDELINE: You MUST NOT call this tool until all relevant details (such
as entity IDs and action argument structures) have been confirmed. If you do not know the
required parameters for an action, you must first call `GetActionDetails` or check exposed
entities rather than guessing or calling `CreateAutomation` with incomplete details.

ATOMICITY & ID PROPAGATION GUIDELINE: Do not call this tool incrementally to construct
or update an automation in parts. If you are modifying/updating an existing automation
created in a previous turn, you MUST pass the `id` field of that automation (using the
ID returned in the previous tool output or retrieved from the registry). Otherwise, a duplicate
automation will be created.

DRY-RUN VALIDATION GUIDELINE: You can test if your parameters are valid (including syntax,
verifying that all entity IDs exist, and verifying that all actions exist) without saving
by setting 'validate_only' to True. You are strongly encouraged to use validation mode
first, and only call the actual creation/update operation (setting 'validate_only' to False or
omitting it) once it successfully passes in validation mode.

SELF-DESTRUCTING / SCHEDULED ACTIONS HINT: You can create a 'self-destructing'
automation by setting 'on_completion' to 'delete_self' or 'disable_self'. This is
highly useful for performing a delayed action in the future.
IMPORTANT: Disabling or deleting a one-shot automation after it runs must be handled
solely by setting the 'on_completion' parameter (e.g., to 'delete_self' or 'disable_self').
You MUST NOT manually include any self-delete/disable action (such as calling
`automation_script_manager.delete_automation` or turning off the automation) inside the
action list. Doing so will fail validation because the automation entity does not
exist in Home Assistant yet when the tool is called.

CONDITIONS VS IF-THEN BLOCKS IN ONE-SHOTS:
For persistent automations ('on_completion': 'persist'), top-level 'condition' blocks are
perfectly fine. However, for one-shot automations ('on_completion': 'delete_self' or
'disable_self'), you must think critically:
- Use a top-level 'condition' block if the automation must stick around checking
  the condition on every trigger until it finally runs the actions once (e.g. "turn off heater
  when temperature is reported, if temp is > 75"). The automation will not self-destruct
  until the condition is satisfied and the actions run.
- Use an 'if-then' conditional action block (an action with 'if' and 'then' keys) if the
  automation must trigger exactly once and clean itself up immediately, regardless of
  whether the condition was met and the actions ran (e.g. "send notification at 10 PM
  if the door is open, then self-destruct").
If there is any uncertainty about this choice, you must explicitly mention which of these
two options you chose in your final response to the user.

IMPORTANT: Triggers, conditions, and actions must be valid Home Assistant structures.

EXAMPLES OF VALID ACTIONS IN AUTOMATION action LIST:
- Call service: [{'action': 'light.turn_on', 'target': {'entity_id': 'light.living_room'},
  'data': {'brightness_pct': 50}}]
- Send notification: [{'action': 'notify.send_message', 'target': {'entity_id': 'notify.jeff'},
  'data': {'message': 'Intrusion!', 'title': 'Alert'}}]
- Delay sequence: [{'delay': '00:01:00'}] (delay for 1 minute)
- Conditional Action (If-Then): [{'if': [{'condition': 'state', 'entity_id': 'sun.sun',
  'state': 'below_horizon'}], 'then': [{'action': 'light.turn_on',
  'target': {'entity_id': 'light.hallway'}}]}]"""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        schema = {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("alias"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Required("trigger"): vol.Any(list, dict),
            vol.Optional("condition"): vol.Any(list, dict),
            vol.Required("action"): vol.Any(list, dict),
            vol.Optional("mode"): cv.string,
            vol.Optional("on_completion"): vol.In(
                ["delete_self", "disable_self", "persist"]
            ),
            vol.Optional("validate_only"): cv.boolean,
        }

        # Check if debug mode is enabled. If so, add optional reasoning slot.
        entry = next(iter(self.hass.config_entries.async_entries(DOMAIN)), None)
        options = entry.options if entry else {}
        if options.get("debug_mode", False):
            schema[vol.Optional("reasoning")] = cv.string

        return schema

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent by calling our service."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        service_data = {}
        for key in (
            "id",
            "entity_id",
            "alias",
            "description",
            "trigger",
            "condition",
            "action",
            "mode",
            "on_completion",
            "validate_only",
        ):
            if key in slots:
                service_data[key] = slots[key]["value"]

        # Force exposing the created automation to the AI
        service_data["expose_to_ai"] = True

        # Extract and log reasoning if debug mode is enabled
        reasoning = None
        entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
        options = entry.options if entry else {}
        if options.get("debug_mode", False) and "reasoning" in slots:
            reasoning = slots["reasoning"]["value"]
            _LOGGER.info("CreateAutomation reasoning: %s", reasoning)

        # Append generation timestamp and optional reasoning to the description
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        generated_info = f"Generated on {now_str}."

        orig_desc = service_data.get("description", "")
        desc_parts = []
        if orig_desc:
            desc_parts.append(orig_desc.strip())
        desc_parts.append(generated_info)
        if reasoning:
            desc_parts.append(f"Reasoning: {reasoning}")

        service_data["description"] = " ".join(desc_parts)

        result = await hass.services.async_call(
            DOMAIN,
            "create_automation",
            service_data,
            context=intent_obj.context,
            blocking=True,
            return_response=True,
        )

        response = intent_obj.create_response()
        if result and result.get("success"):
            msg = f"Automation '{result.get('id')}' created successfully."
            if reasoning:
                msg += f" Reasoning: {reasoning}"
                response.async_set_speech(msg, extra_data={"reasoning": reasoning})
            else:
                response.async_set_speech(msg)
        else:
            error_msg = result.get("error") if result else "Unknown error"
            msg = f"Failed to create automation: {error_msg}"
            if reasoning:
                msg += f" Reasoning: {reasoning}"
                response.async_set_speech(msg, extra_data={"reasoning": reasoning})
            else:
                response.async_set_speech(msg)
        return response


class DeleteAutomationIntent(intent.IntentHandler):
    """Handle DeleteAutomation intent."""

    intent_type = "DeleteAutomation"
    description = (
        "Delete an automation from Home Assistant. Restricts to specific "
        "tag if configured."
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent by calling our service."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        service_data = {}
        for key in ("id", "entity_id"):
            if key in slots:
                service_data[key] = slots[key]["value"]

        result = await hass.services.async_call(
            DOMAIN,
            "delete_automation",
            service_data,
            context=intent_obj.context,
            blocking=True,
            return_response=True,
        )

        response = intent_obj.create_response()
        if result and result.get("success"):
            response.async_set_speech(f"Automation '{result.get('id')}' deleted successfully.")
        else:
            error_msg = result.get("error") if result else "Unknown error"
            response.async_set_speech(f"Failed to delete automation: {error_msg}")
        return response


class CreateScriptIntent(intent.IntentHandler):
    """Handle CreateScript intent."""

    intent_type = "CreateScript"
    description = """Create or update a script in Home Assistant. Scripts define a sequence
of actions.

GATHER THEN ACT GUIDELINE: You MUST NOT call this tool until all relevant details (such
as entity IDs and action argument structures) have been confirmed. If you do not know the
required parameters for an action, you must first call `GetActionDetails` or check exposed
entities rather than guessing or calling `CreateScript` with incomplete details.

TEMPLATE GUIDELINE: Always prefer using built-in, non-templated options
(such as numeric state trigger thresholds or standard state triggers) if a
built-in equivalent exists that can accomplish the goal. However, if templates
are necessary for complex triggers, conditions, or other automation logic, you
may write them. If you need to search or inspect the available Jinja2 template
functions, filters, or tests registered in Home Assistant, you must call
`GetTemplateHelperDocs`.

ATOMICITY & ID PROPAGATION GUIDELINE: Do not call this tool incrementally to construct
or update a script in parts. If you are modifying/updating an existing script created
in a previous turn, you MUST pass the `id` field of that script (using the ID returned
in the previous tool output or retrieved from the registry). Otherwise, a duplicate
script will be created.

DRY-RUN VALIDATION GUIDELINE: You can test if your parameters are valid (including syntax,
verifying that all entity IDs exist, and verifying that all actions exist) without saving
by setting 'validate_only' to True. You are strongly encouraged to use validation mode
first, and only call the actual creation/update operation (setting 'validate_only' to False or
omitting it) once it successfully passes in validation mode.

ONE-SHOT / SELF-DESTRUCTING SCRIPTS HINT: You can create a 'self-destructing' script by
setting 'on_completion' to 'delete_self'.
IMPORTANT: Deleting a one-shot script after it runs must be handled solely by setting
the 'on_completion' parameter to 'delete_self'. You MUST NOT manually include any self-delete
action (such as calling `automation_script_manager.delete_script` targeting the script itself)
inside the sequence list. Doing so will fail validation because the script entity does not
exist in Home Assistant yet when the tool is called.

IMPORTANT: The sequence must be a valid Home Assistant sequence structure.

NOTIFICATION GUIDELINE: When creating a notification action in your sequence, ALWAYS
use the `notify.send_message` action (never `notify.notify` or service names like
`notify.jeff`), and target the correct notify entity ID from the entity registry/list
(e.g. targeting `notify.mobile_app_jeff` or `notify.jeff`).

EXAMPLES OF VALID ACTIONS IN SEQUENCE:
- Call service: [{'action': 'light.turn_on', 'target': {'entity_id': 'light.living_room'},
  'data': {'brightness_pct': 50}}]
- Send notification: [{'action': 'notify.send_message', 'target': {'entity_id': 'notify.jeff'},
  'data': {'message': 'Alert!'}}]
- Media Player: [{'action': 'media_player.volume_set',
  'target': {'entity_id': 'media_player.lounge'}, 'data': {'volume_level': 0.5}}]
- Run script: [{'action': 'script.flash_light'}]
- Delay: [{'delay': '00:00:05'}] (delay for 5 seconds)
- Conditional sequence (If-Then): [{'if': [{'condition': 'state', 'entity_id': 'sun.sun',
  'state': 'below_horizon'}], 'then': [{'action': 'light.turn_on',
  'target': {'entity_id': 'light.hallway'}}]}]
- Choose logic: [{'choose': [{'conditions': [{'condition': 'state',
  'entity_id': 'binary_sensor.motion', 'state': 'on'}], 'sequence': [{'action': 'light.turn_on',
  'target': {'entity_id': 'light.living_room'}}]}]}]"""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        schema = {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("alias"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Required("sequence"): vol.Any(list, dict),
            vol.Optional("mode"): cv.string,
            vol.Optional("on_completion"): vol.In(["delete_self", "persist"]),
            vol.Optional("validate_only"): cv.boolean,
        }

        # Check if debug mode is enabled. If so, add optional reasoning slot.
        entry = next(iter(self.hass.config_entries.async_entries(DOMAIN)), None)
        options = entry.options if entry else {}
        if options.get("debug_mode", False):
            schema[vol.Optional("reasoning")] = cv.string

        return schema

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent by calling our service."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        service_data = {}
        for key in (
            "id",
            "entity_id",
            "alias",
            "description",
            "sequence",
            "mode",
            "on_completion",
            "validate_only",
        ):
            if key in slots:
                service_data[key] = slots[key]["value"]

        # Force exposing the created script to the AI
        service_data["expose_to_ai"] = True

        # Extract and log reasoning if debug mode is enabled
        reasoning = None
        entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
        options = entry.options if entry else {}
        if options.get("debug_mode", False) and "reasoning" in slots:
            reasoning = slots["reasoning"]["value"]
            _LOGGER.info("CreateScript reasoning: %s", reasoning)

        # Append generation timestamp and optional reasoning to the description
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        generated_info = f"Generated on {now_str}."

        orig_desc = service_data.get("description", "")
        desc_parts = []
        if orig_desc:
            desc_parts.append(orig_desc.strip())
        desc_parts.append(generated_info)
        if reasoning:
            desc_parts.append(f"Reasoning: {reasoning}")

        service_data["description"] = " ".join(desc_parts)

        result = await hass.services.async_call(
            DOMAIN,
            "create_script",
            service_data,
            context=intent_obj.context,
            blocking=True,
            return_response=True,
        )

        response = intent_obj.create_response()
        if result and result.get("success"):
            msg = f"Script '{result.get('id')}' created successfully."
            if reasoning:
                msg += f" Reasoning: {reasoning}"
                response.async_set_speech(msg, extra_data={"reasoning": reasoning})
            else:
                response.async_set_speech(msg)
        else:
            error_msg = result.get("error") if result else "Unknown error"
            msg = f"Failed to create script: {error_msg}"
            if reasoning:
                msg += f" Reasoning: {reasoning}"
                response.async_set_speech(msg, extra_data={"reasoning": reasoning})
            else:
                response.async_set_speech(msg)
        return response


class DeleteScriptIntent(intent.IntentHandler):
    """Handle DeleteScript intent."""

    intent_type = "DeleteScript"
    description = "Delete a script from Home Assistant. Restricts to specific tag if configured."

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent by calling our service."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        service_data = {}
        for key in ("id", "entity_id"):
            if key in slots:
                service_data[key] = slots[key]["value"]

        result = await hass.services.async_call(
            DOMAIN,
            "delete_script",
            service_data,
            context=intent_obj.context,
            blocking=True,
            return_response=True,
        )

        response = intent_obj.create_response()
        if result and result.get("success"):
            response.async_set_speech(f"Script '{result.get('id')}' deleted successfully.")
        else:
            error_msg = result.get("error") if result else "Unknown error"
            response.async_set_speech(f"Failed to delete script: {error_msg}")
        return response


class GetExposedNotifyEntitiesIntent(intent.IntentHandler):
    """Handle GetExposedNotifyEntities intent."""

    intent_type = "GetExposedNotifyEntities"
    description = (
        "Get the list of notify entities that are exposed to the "
        "AI/conversation assistant."
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass

        try:
            from homeassistant.components.homeassistant.exposed_entities import async_should_expose
            has_expose_helper = True
        except ImportError:
            has_expose_helper = False

        exposed_entities = []

        if has_expose_helper:
            for state in hass.states.async_all("notify"):
                entity_id = state.entity_id
                if async_should_expose(hass, "conversation", entity_id):
                    exposed_entities.append(f"- {entity_id} ({state.name})")

        response = intent_obj.create_response()

        if exposed_entities:
            entities_str = "\n".join(exposed_entities)
            response.async_set_speech(
                f"The following notify entities are exposed to AI/Assist:\n{entities_str}"
            )
        else:
            response.async_set_speech(
                "No notify entities are currently exposed to the "
                "AI/conversation assistant."
            )

        return response


class EnumerateActionsIntent(intent.IntentHandler):
    """Handle EnumerateActions intent."""

    intent_type = "EnumerateActions"
    description = (
        "List all available actions (services) registered in Home "
        "Assistant with a short description."
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass

        from homeassistant.helpers.service import async_get_all_descriptions
        descriptions = await async_get_all_descriptions(hass)

        entry = next(iter(hass.config_entries.async_entries(DOMAIN)), None)
        options = entry.options if entry else {}

        lines = []
        for domain, services in sorted(descriptions.items()):
            for service_name, service_info in sorted(services.items()):
                from . import is_action_allowed
                if not is_action_allowed(domain, service_name, options):
                    continue
                desc = service_info.get("description", "No description available.")
                lines.append(f"- {domain}.{service_name}: {desc}")

        response = intent_obj.create_response()
        if lines:
            actions_list = "\n".join(lines)
            response.async_set_speech(
                f"Here are all available actions:\n{actions_list}"
            )
        else:
            response.async_set_speech("No actions found.")

        return response


class GetActionDetailsIntent(intent.IntentHandler):
    """Handle GetActionDetails intent."""

    intent_type = "GetActionDetails"
    description = "Get detailed information about an action (service) and its arguments."

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Required("action_name"): cv.string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        action_name = slots["action_name"]["value"].strip()

        if "." not in action_name:
            response = intent_obj.create_response()
            response.async_set_speech(
                f"Invalid action name '{action_name}'. Please specify it in the format "
                "'domain.action' (e.g. 'light.turn_on')."
            )
            return response

        domain, service = action_name.split(".", 1)

        from homeassistant.helpers.service import async_get_all_descriptions
        descriptions = await async_get_all_descriptions(hass)

        response = intent_obj.create_response()

        domain_services = descriptions.get(domain)
        if not domain_services or service not in domain_services:
            response.async_set_speech(
                f"Action '{action_name}' was not found."
            )
            return response

        service_info = domain_services[service]
        desc = service_info.get("description", "No description available.")

        speech_parts = [
            f"Action: {action_name}",
            f"Description: {desc}",
        ]

        fields = service_info.get("fields", {})
        if fields:
            speech_parts.append("Arguments:")
            for field_name, field_info in fields.items():
                field_desc = field_info.get("description", "No description available.")
                field_required = "Required" if field_info.get("required") else "Optional"
                field_example = field_info.get("example")
                example_str = f" (Example: {field_example})" if field_example is not None else ""
                speech_parts.append(
                    f"- {field_name} ({field_required}): {field_desc}{example_str}"
                )
        else:
            speech_parts.append("This action takes no arguments.")

        response.async_set_speech("\n".join(speech_parts))
        return response


class GetEntityTracesIntent(intent.IntentHandler):
    """Handle GetEntityTraces intent."""

    intent_type = "GetEntityTraces"
    description = (
        "Get execution traces and recent run details for a specific "
        "automation or script entity. Only exposed entities are allowed."
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("run_id"): cv.string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        entity_id = slots["entity_id"]["value"].strip()
        run_id = slots["run_id"]["value"].strip() if "run_id" in slots else None

        response = intent_obj.create_response()

        # Enforce exposed-only restriction for conversation/LLM
        from homeassistant.components.homeassistant.exposed_entities import (
            async_should_expose,
        )
        if not async_should_expose(hass, "conversation", entity_id):
            response.async_set_speech(
                f"Entity '{entity_id}' is not exposed to the AI assistant. "
                "You cannot query its execution traces."
            )
            return response

        from . import async_fetch_entity_traces
        try:
            traces_data = await async_fetch_entity_traces(hass, entity_id, run_id)
        except Exception as err:
            response.async_set_speech(
                f"Failed to fetch execution traces for '{entity_id}': {err}"
            )
            return response

        recent_runs = traces_data.get("recent_runs", [])
        detailed_run = traces_data.get("detailed_run")

        speech_parts = [f"Execution traces for {entity_id}:"]

        if recent_runs:
            speech_parts.append("\nRecent runs (up to 5):")
            for r in recent_runs:
                err_str = f" (Error: {r['error']})" if r.get("error") else ""
                speech_parts.append(
                    f"- Run ID: {r['run_id']} | State: {r['state']} | "
                    f"Start Time: {r['start_time']}{err_str}"
                )
        else:
            speech_parts.append("\nNo recent runs found.")

        if detailed_run:
            speech_parts.append(
                f"\nDetailed steps for Run ID {detailed_run['run_id']}:"
            )
            steps = detailed_run.get("steps", [])
            if steps:
                for step in steps:
                    step_err = f" | Error: {step['error']}" if step.get("error") else ""
                    step_res = f" | Result: {step['result']}" if step.get("result") else ""
                    speech_parts.append(
                        f"- Path: {step['path']} | "
                        f"Timestamp: {step['timestamp']}{step_err}{step_res}"
                    )
            else:
                speech_parts.append("No detailed steps recorded for this run.")
        elif run_id:
            speech_parts.append(f"\nDetailed steps for Run ID '{run_id}' not found.")

        response.async_set_speech("\n".join(speech_parts))
        return response


class GetTemplateHelperDocsIntent(intent.IntentHandler):
    """Handle GetTemplateHelperDocs intent."""

    intent_type = "GetTemplateHelperDocs"
    description = (
        "Get documentation for available Jinja2 template helper functions, "
        "filters, and tests registered in Home Assistant."
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Optional("search_term"): cv.string,
            vol.Optional("only_custom"): cv.boolean,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        search_term = (
            slots["search_term"]["value"].strip()
            if "search_term" in slots
            else None
        )
        only_custom = (
            slots["only_custom"]["value"] if "only_custom" in slots else True
        )

        response = intent_obj.create_response()

        from . import async_get_template_helper_docs
        try:
            docs = await async_get_template_helper_docs(
                hass, search_term, only_custom
            )
        except Exception as err:
            response.async_set_speech(
                f"Failed to fetch template helper documentation: {err}"
            )
            return response

        speech_parts = ["Jinja2 Template Helper Documentation:"]

        for category in ("globals", "filters", "tests"):
            helpers = docs.get(category, [])
            if helpers:
                speech_parts.append(f"\n{category.capitalize()}:")
                for h in helpers:
                    desc_first_line = h["description"].split("\n")[0]
                    speech_parts.append(
                        f"- `{h['name']}{h['signature']}`: {desc_first_line}"
                    )

        if len(speech_parts) == 1:
            speech_parts.append("No matching template helpers found.")

        response.async_set_speech("\n".join(speech_parts))
        return response


class RenderTemplateIntent(intent.IntentHandler):
    """Handle RenderTemplate intent."""

    intent_type = "RenderTemplate"
    description = (
        "Evaluate (render) a Jinja2 template and return the result. "
        "Useful for testing template expressions or rendering dynamic outputs "
        "to return to the user."
    )

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__()
        self.hass = hass

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Required("template"): cv.string,
            vol.Optional("variables"): dict,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass
        slots = intent_obj.slots

        template_str = slots["template"]["value"]
        variables = slots["variables"]["value"] if "variables" in slots else None

        response = intent_obj.create_response()

        from . import async_evaluate_template
        try:
            result = await async_evaluate_template(
                hass, template_str, variables
            )
            response.async_set_speech(
                f"Template rendered successfully:\n{result}"
            )
        except Exception as err:
            response.async_set_speech(
                f"Failed to render template: {err}"
            )

        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register intents with the Home Assistant intent system."""
    intent.async_register(hass, CreateAutomationIntent(hass))
    intent.async_register(hass, DeleteAutomationIntent(hass))
    intent.async_register(hass, CreateScriptIntent(hass))
    intent.async_register(hass, DeleteScriptIntent(hass))
    intent.async_register(hass, GetExposedNotifyEntitiesIntent(hass))
    intent.async_register(hass, EnumerateActionsIntent(hass))
    intent.async_register(hass, GetActionDetailsIntent(hass))
    intent.async_register(hass, GetEntityTracesIntent(hass))
    intent.async_register(hass, GetTemplateHelperDocsIntent(hass))
    intent.async_register(hass, RenderTemplateIntent(hass))
