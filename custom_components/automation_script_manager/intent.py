"""Intent handlers for the Automation & Script Manager."""

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, config_validation as cv

from .const import DOMAIN

class CreateAutomationIntent(intent.IntentHandler):
    """Handle CreateAutomation intent."""

    intent_type = "CreateAutomation"
    description = (
        "Create or update an automation in Home Assistant. Exposes triggers, conditions, and actions. "
        "DECISION GUIDELINE: Creating an automation is appropriate when the user wants event-driven, "
        "conditional, or scheduled behavior (e.g. if the user says 'whenever X, do Y', 'when X occurs, do Y', "
        "or 'schedule action Z at time T'). For immediate, on-demand action execution, prefer creating or "
        "running scripts instead.\n"
        "SELF-DESTRUCTING / SCHEDULED ACTIONS HINT: You can create a 'self-destructing' automation by "
        "setting 'on_completion' to 'delete_self' or 'disable_self'. This is highly useful for performing "
        "a delayed action in the future (e.g. triggering at a specific time or after a delay) or when a "
        "condition is met (e.g. when a sensor reaches a value). Because it is saved as a standard automation entity, "
        "the scheduled action can later be cancelled by you or the user by disabling or deleting that "
        "automation before it triggers.\n"
        "IMPORTANT: Triggers, conditions, and actions must be valid Home Assistant structures. "
        "EXAMPLES OF VALID TRIGGERS:\n"
        "- State trigger: [{'platform': 'state', 'entity_id': 'binary_sensor.motion', 'to': 'on'}]\n"
        "- Time trigger: [{'platform': 'time', 'at': '07:30:00'}]\n"
        "- Numeric state: [{'platform': 'numeric_state', 'entity_id': 'sensor.battery', 'below': 20}]\n"
        "- Sun event: [{'platform': 'sun', 'event': 'sunset', 'offset': '+00:30:00'}]\n"
        "- Zone trigger: [{'platform': 'zone', 'entity_id': 'person.john', 'zone': 'zone.home', 'event': 'enter'}]\n"
        "EXAMPLES OF VALID CONDITIONS:\n"
        "- State condition: [{'condition': 'state', 'entity_id': 'sun.sun', 'state': 'below_horizon'}]\n"
        "- Time condition: [{'condition': 'time', 'after': '22:00:00', 'before': '06:00:00'}]\n"
        "- Template condition: [{'condition': 'template', 'value_template': '{{ states(\"sensor.battery\") | int > 50 }}'}]\n"
        "- And condition: [{'condition': 'and', 'conditions': [{'condition': 'state', 'entity_id': 'sun.sun', 'state': 'below_horizon'}, {'condition': 'state', 'entity_id': 'binary_sensor.motion', 'state': 'off'}]}]\n"
        "EXAMPLES OF VALID ACTIONS:\n"
        "- Turn on entity: [{'action': 'light.turn_on', 'target': {'entity_id': 'light.living_room'}, 'data': {'brightness_pct': 80}}]\n"
        "- Turn off entity: [{'action': 'homeassistant.turn_off', 'target': {'entity_id': 'switch.heater'}}]\n"
        "- Call notification: [{'action': 'persistent_notification.create', 'data': {'title': 'Alert', 'message': 'Intrusion!'}}]\n"
        "- Delay sequence: [{'delay': '00:01:00'}] (delay for 1 minute)\n"
        "- Conditional Action (If-Then): [{'if': [{'condition': 'state', 'entity_id': 'sun.sun', 'state': 'below_horizon'}], 'then': [{'action': 'light.turn_on', 'target': {'entity_id': 'light.hallway'}}]}]\n"
    )

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("alias"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Optional("trigger"): vol.Any(list, dict),
            vol.Optional("condition"): vol.Any(list, dict),
            vol.Optional("action"): vol.Any(list, dict),
            vol.Optional("mode"): cv.string,
            vol.Optional("on_completion"): vol.In(["delete_self", "disable_self", "persist"]),
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
        ):
            if key in slots:
                service_data[key] = slots[key]["value"]

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
    description = "Delete an automation from Home Assistant. Restricts to specific tag if configured."

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
    description = (
        "Create or update a script in Home Assistant. Scripts define a sequence of actions. "
        "IMPORTANT: The sequence must be a valid Home Assistant sequence structure. "
        "EXAMPLES OF VALID ACTIONS IN SEQUENCE:\n"
        "- Call service: [{'action': 'light.turn_on', 'target': {'entity_id': 'light.living_room'}, 'data': {'brightness_pct': 50}}]\n"
        "- Media Player: [{'action': 'media_player.volume_set', 'target': {'entity_id': 'media_player.lounge'}, 'data': {'volume_level': 0.5}}]\n"
        "- Run script: [{'action': 'script.flash_light'}]\n"
        "- Delay: [{'delay': '00:00:05'}] (delay for 5 seconds)\n"
        "- Conditional sequence (If-Then): [{'if': [{'condition': 'state', 'entity_id': 'sun.sun', 'state': 'below_horizon'}], 'then': [{'action': 'light.turn_on', 'target': {'entity_id': 'light.hallway'}}]}]\n"
        "- Choose logic: [{'choose': [{'conditions': [{'condition': 'state', 'entity_id': 'binary_sensor.motion', 'state': 'on'}], 'sequence': [{'action': 'light.turn_on', 'target': {'entity_id': 'light.living_room'}}]}]}]\n"
    )

    @property
    def slot_schema(self) -> dict | None:
        """Return slot schema."""
        return {
            vol.Optional("id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("alias"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Optional("sequence"): vol.Any(list, dict),
            vol.Optional("mode"): cv.string,
            vol.Optional("on_completion"): vol.In(["delete_self", "persist"]),
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
        ):
            if key in slots:
                service_data[key] = slots[key]["value"]

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


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register intents with the Home Assistant intent system."""
    intent.async_register(hass, CreateAutomationIntent())
    intent.async_register(hass, DeleteAutomationIntent())
    intent.async_register(hass, CreateScriptIntent())
    intent.async_register(hass, DeleteScriptIntent())
