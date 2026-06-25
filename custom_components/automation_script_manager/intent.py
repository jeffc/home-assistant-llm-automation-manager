"""Intent handlers for the Automation & Script Manager."""

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, config_validation as cv

from .const import DOMAIN

class CreateAutomationIntent(intent.IntentHandler):
    """Handle CreateAutomation intent."""

    intent_type = "CreateAutomation"
    description = """Create or update an automation.
Exposes triggers, conditions, and actions.

DECISION GUIDELINE: Creating an automation is appropriate when the user wants
event-driven, conditional, or scheduled behavior (e.g. if the user says 'whenever X, do Y',
'when X occurs, do Y', or 'schedule action Z at time T'). For immediate, on-demand
action execution, prefer creating or running scripts instead.

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
You MUST NOT manually include any self-disable or self-delete action (such as calling
`automation.turn_off` or `automation_script_manager.delete_automation` targeting the
automation itself) inside the action list. Doing so will fail validation because the
automation entity does not exist in Home Assistant yet when the tool is called.

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

EXAMPLES OF VALID TRIGGERS:
- State trigger: [{'platform': 'state', 'entity_id': 'binary_sensor.motion', 'to': 'on'}]
- Time trigger: [{'platform': 'time', 'at': '07:30:00'}]
- Numeric state: [{'platform': 'numeric_state', 'entity_id': 'sensor.battery', 'below': 20}]
- Sun event: [{'platform': 'sun', 'event': 'sunset', 'offset': '+00:30:00'}]
- Zone trigger: [{'platform': 'zone', 'entity_id': 'person.john', 'zone': 'zone.home',
  'event': 'enter'}]

EXAMPLES OF VALID CONDITIONS:
- State condition: [{'condition': 'state', 'entity_id': 'sun.sun', 'state': 'below_horizon'}]
- Time condition: [{'condition': 'time', 'after': '22:00:00', 'before': '06:00:00'}]
- Template condition: [{'condition': 'template',
  'value_template': '{{ states("sensor.battery") | int > 50 }}'}]
- And condition: [{'condition': 'and', 'conditions': [{'condition': 'state',
  'entity_id': 'sun.sun', 'state': 'below_horizon'}, {'condition': 'state',
  'entity_id': 'binary_sensor.motion', 'state': 'off'}]}]

EXAMPLES OF VALID ACTIONS:
- Turn on entity: [{'action': 'light.turn_on', 'target': {'entity_id': 'light.living_room'},
  'data': {'brightness_pct': 80}}]
- Turn off entity: [{'action': 'homeassistant.turn_off', 'target': {'entity_id': 'switch.heater'}}]
- Send notification: [{'action': 'notify.send_message', 'target': {'entity_id': 'notify.jeff'},
  'data': {'message': 'Intrusion!', 'title': 'Alert'}}]
- Delay sequence: [{'delay': '00:01:00'}] (delay for 1 minute)
- Conditional Action (If-Then): [{'if': [{'condition': 'state', 'entity_id': 'sun.sun',
  'state': 'below_horizon'}], 'then': [{'action': 'light.turn_on',
  'target': {'entity_id': 'light.hallway'}}]}]"""

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
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
            response.async_set_speech(f"Automation '{result.get('id')}' created successfully.")
        else:
            error_msg = result.get("error") if result else "Unknown error"
            response.async_set_speech(f"Failed to create automation: {error_msg}")
        return response


class DeleteAutomationIntent(intent.IntentHandler):
    """Handle DeleteAutomation intent."""

    intent_type = "DeleteAutomation"
    description = (
        "Delete an automation from Home Assistant. Restricts to specific "
        "tag if configured."
    )

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

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("alias"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Required("sequence"): vol.Any(list, dict),
            vol.Optional("mode"): cv.string,
            vol.Optional("on_completion"): vol.In(["delete_self", "persist"]),
            vol.Optional("validate_only"): cv.boolean,
        }

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
            response.async_set_speech(f"Script '{result.get('id')}' created successfully.")
        else:
            error_msg = result.get("error") if result else "Unknown error"
            response.async_set_speech(f"Failed to create script: {error_msg}")
        return response


class DeleteScriptIntent(intent.IntentHandler):
    """Handle DeleteScript intent."""

    intent_type = "DeleteScript"
    description = "Delete a script from Home Assistant. Restricts to specific tag if configured."

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

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass = intent_obj.hass

        from homeassistant.helpers.service import async_get_all_descriptions
        descriptions = await async_get_all_descriptions(hass)

        lines = []
        for domain, services in sorted(descriptions.items()):
            for service_name, service_info in sorted(services.items()):
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


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register intents with the Home Assistant intent system."""
    intent.async_register(hass, CreateAutomationIntent())
    intent.async_register(hass, DeleteAutomationIntent())
    intent.async_register(hass, CreateScriptIntent())
    intent.async_register(hass, DeleteScriptIntent())
    intent.async_register(hass, GetExposedNotifyEntitiesIntent())
    intent.async_register(hass, EnumerateActionsIntent())
    intent.async_register(hass, GetActionDetailsIntent())
