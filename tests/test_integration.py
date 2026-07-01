"""Unit tests for Automation & Script Manager custom integration."""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest
import voluptuous as vol

from homeassistant.helpers import config_validation as cv
from custom_components.automation_script_manager import (
    _extract_actions,
    _extract_entity_ids,
    is_action_allowed_by_regex,
    async_get_common_icons,
)
from custom_components.automation_script_manager.intent import (
    CreateAutomationIntent,
    CreateScriptIntent,
)


def test_extraction_logic():
    """Test action and entity extraction from config dictionary structures."""
    config = {
        "alias": "Test Automation",
        "trigger": [{"platform": "state", "entity_id": "input_boolean.test"}],
        "action": [
            {"action": "notify.pixel_10", "data": {"message": "Hello"}},
            {
                "if": [{"condition": "state", "entity_id": "binary_sensor.motion", "state": "on"}],
                "then": [{"action": "light.turn_on", "target": {"entity_id": "light.living_room"}}],
            },
        ],
    }

    actions = _extract_actions(config)
    assert "notify.pixel_10" in actions
    assert "light.turn_on" in actions
    assert len(actions) == 2

    entity_ids = _extract_entity_ids(config)
    assert "input_boolean.test" in entity_ids
    assert "binary_sensor.motion" in entity_ids
    assert "light.living_room" in entity_ids
    assert len(entity_ids) == 3


def test_permission_regexes():
    """Test security policy regex checks for allowed/denied action lists."""
    # Scenario A: Permissive mode with system safety (default)
    allow_regex = ".*"
    disallow_regex = "homeassistant\\..*\nupdate\\..*\nhassio\\..*"

    assert not is_action_allowed_by_regex("homeassistant.restart", allow_regex, disallow_regex)
    assert not is_action_allowed_by_regex("update.install", allow_regex, disallow_regex)
    assert is_action_allowed_by_regex("light.turn_on", allow_regex, disallow_regex)

    # Scenario B: Minimalist strict allowlist
    allow_strict = "light\\..*\nmedia_player\\..*\nclimate\\..*"
    disallow_strict = ""

    assert is_action_allowed_by_regex("light.turn_on", allow_strict, disallow_strict)
    assert is_action_allowed_by_regex("media_player.media_play", allow_strict, disallow_strict)
    assert not is_action_allowed_by_regex("switch.turn_on", allow_strict, disallow_strict)

    # Scenario C: Lock & security protection
    allow_c = ".*"
    disallow_c = "lock\\.unlock\ncover\\.open\nalarm_control_panel\\.alarm_disarm"

    assert not is_action_allowed_by_regex("lock.unlock", allow_c, disallow_c)
    assert not is_action_allowed_by_regex("cover.open", allow_c, disallow_c)
    assert is_action_allowed_by_regex("lock.lock", allow_c, disallow_c)


def test_tag_schema_validation():
    """Test tag inputs in config flow reject invalid characters but accept valid ones."""
    schema = vol.Schema(vol.All(cv.string, vol.Match(r"^[a-zA-Z0-9_\-\s]*$")))

    # Valid tags
    schema("CREATED_WITH_AUTOMATION")
    schema("one-shot")
    schema("would-be-deleted")
    schema("tag 123")
    schema("")

    # Invalid tags (should raise vol.Invalid)
    with pytest.raises(vol.Invalid):
        schema("tag,with,comma")
    with pytest.raises(vol.Invalid):
        schema("tag/with/slash")
    with pytest.raises(vol.Invalid):
        schema("tag;with;semicolon")


def test_common_icons_mining():
    """Test mining, frequency counting, sorting, and capping of active server icons."""
    hass = MagicMock()

    # Create mock states with duplicate icons to test frequency counting
    state1 = MagicMock()
    state1.attributes = {"icon": "mdi:couch"}
    state2 = MagicMock()
    state2.attributes = {"icon": "mdi:couch"}
    state3 = MagicMock()
    state3.attributes = {"icon": "mdi:lightbulb"}
    state4 = MagicMock()
    state4.attributes = {"icon": "invalid_icon_no_prefix"}

    hass.states.async_all.return_value = [state1, state2, state3, state4]

    # Mock entity registry
    ent_reg = MagicMock()
    entry1 = MagicMock()
    entry1.icon = "mdi:couch"
    entry1.original_icon = None
    entry2 = MagicMock()
    entry2.icon = None
    entry2.original_icon = "mdi:fan"
    ent_reg.entities = {"e1": entry1, "e2": entry2}

    # Patch er.async_get
    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=ent_reg),
        patch("custom_components.automation_script_manager.COMMON_ICONS", []),
    ):
        result = async_get_common_icons(hass)
        icons_list = result.get("icons", [])

        # mdi:couch (count 3), mdi:fan (count 1), mdi:lightbulb (count 1)
        icons_only = [item["icon"] for item in icons_list]
        assert "mdi:couch" in icons_only
        assert "mdi:fan" in icons_only
        assert "mdi:lightbulb" in icons_only
        assert len(icons_only) == 3

        # couch should be first since it has highest frequency
        assert icons_only[0] == "mdi:couch"


def test_intent_dynamic_slots_and_guidelines():
    """Test that slot schemas remain robust and guidelines are conditional."""
    hass = MagicMock()

    # Mock config entry and options
    entry = MagicMock()
    entry.options = {
        "let_llm_assign_icon": False,
        "debug_mode": False,
        "categorize_mode": "leave_uncategorized",
    }
    hass.config_entries.async_entries.return_value = [entry]

    # Create intents
    auto_intent = CreateAutomationIntent(hass)
    script_intent = CreateScriptIntent(hass)

    # Slots should be permissive (always optional) to prevent InvalidSlotInfo errors
    assert "icon" in auto_intent.slot_schema
    assert "reasoning" in auto_intent.slot_schema
    assert "category_id" in auto_intent.slot_schema

    assert "icon" in script_intent.slot_schema
    assert "reasoning" in script_intent.slot_schema
    assert "category_id" in script_intent.slot_schema

    # Guidelines should omit icon assignment info if disabled
    assert "ICON ASSIGNMENT GUIDELINE" not in auto_intent.description
    assert "ICON ASSIGNMENT GUIDELINE" not in script_intent.description

    # Enable icon assignment
    entry.options["let_llm_assign_icon"] = True

    # Guidelines should now include icon assignment instructions
    assert "ICON ASSIGNMENT GUIDELINE" in auto_intent.description
    assert "ICON ASSIGNMENT GUIDELINE" in script_intent.description


@pytest.mark.asyncio
async def test_options_flow_manual_tag_validation():
    """Test tag validation in OptionsFlowHandler."""
    from custom_components.automation_script_manager.config_flow import OptionsFlowHandler

    mock_entry = MagicMock()
    mock_entry.options = {
        "tag": "initial-tag",
        "one_shot_tag": "initial-one-shot",
        "would_be_deleted_tag": "initial-would-be-deleted",
    }

    with patch.object(
        OptionsFlowHandler, "config_entry", new_callable=PropertyMock
    ) as mock_config_entry:
        mock_config_entry.return_value = mock_entry
        handler = OptionsFlowHandler()
        handler.hass = MagicMock()

        # Mock category registry to return no categories
        with patch("homeassistant.helpers.category_registry.async_get") as mock_cat_get:
            mock_cat_reg = MagicMock()
            mock_cat_reg.async_list_categories.return_value = []
            mock_cat_get.return_value = mock_cat_reg

            # Test valid input (passes validation, returns next step or transitions)
            valid_input = {
                "tag": "my_valid_tag 123",
                "one_shot_tag": "valid-one",
                "would_be_deleted_tag": "valid-would-be-deleted",
            }
            with patch.object(handler, "async_step_security") as mock_step_sec:
                await handler.async_step_init(valid_input)
                mock_step_sec.assert_called_once()

            # Test invalid input (fails validation, shows form with errors)
            invalid_input = {
                "tag": "invalid,tag",
                "one_shot_tag": "invalid;tag",
                "would_be_deleted_tag": "invalid/tag",
            }
            res = await handler.async_step_init(invalid_input)
            assert res["errors"] == {
                "tag": "invalid_tag_format",
                "one_shot_tag": "invalid_tag_format",
                "would_be_deleted_tag": "invalid_tag_format",
            }
