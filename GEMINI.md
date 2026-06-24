# GEMINI.md: Developer & AI Agent Reference

This document serves as a technical design manual and development reference for developers and AI coding agents (such as Gemini) maintaining or extending this custom integration.

---

## Architecture Design

The `automation_script_manager` integration operates directly on Home Assistant's configuration YAML files (`automations.yaml` and `scripts.yaml`). It bypasses the WebSocket API and wraps core configuration-editing logic inside standard asynchronous service calls (actions).

```
                      +-------------------+
                      |   LLM / Assist    |
                      +---------+---------+
                                | (Intents)
                                v
+------------------+  +-------------------+
|  Developer UI    +->|   Service Calls   |
+------------------+  +---------+---------+
                                |
                                v
                      +---------+---------+
                      |   Validation      | (automation/script.config.async_validate_config_item)
                      +---------+---------+
                                |
                                v
                      +---------+---------+
                      |   File Lock       | (asyncio.Lock per YAML file type)
                      +---------+---------+
                                |
                                v
                      +---------+---------+
                      |   Atomic Write    | (write_utf8_file_atomic)
                      +---------+---------+
                                |
                                v
                      +---------+---------+
                      |   Engine Reload   | (automation.reload / script.reload)
                      +-------------------+
```

### 1. File & Concurrency Safety
*   **Locks**: Modifications to the YAML files are serialized using two separate `asyncio.Lock` instances (stored in `hass.data[DOMAIN]["automation_lock"]` and `hass.data[DOMAIN]["script_lock"]`). This prevents race conditions and file corruption when multiple service calls or LLM requests run concurrently.
*   **Atomic Writes**: Writing YAML files uses Home Assistant's internal `write_utf8_file_atomic` utility. This writes to a temporary file first, then swaps it atomically on the filesystem to avoid truncating files if writing fails.

### 2. Validation
Before saving any changes to disk, the integration invokes Home Assistant's native configuration validation routines:
*   **Automations**: `homeassistant.components.automation.config.async_validate_config_item`
*   **Scripts**: `homeassistant.components.script.config.async_validate_config_item`

This checks trigger syntax, action schemas, condition templates, and blueprint inputs. If the validation raises `vol.Invalid` or `HomeAssistantError`, the service call intercepts it and returns structured error feedback.

### 3. Service Call Responses
All services are registered with `supports_response=SupportsResponse.OPTIONAL`. 
*   **Standard Return Type**: `ServiceResponse` (a dictionary).
*   **Payload Format**:
    *   Success: `{"success": True, "id": "<resolved_id>"}`
    *   Failure: `{"success": False, "error": "<detailed_exception_trace>"}`
This structured design prevents hard exceptions from crashing the LLM tool invocation context, enabling conversation agents to inspect the error payload and automatically self-correct parameters (e.g. rewriting invalid trigger YAML).

### 4. Dynamic Tagging & Labels
*   **Labels Registry**: Integrates with `homeassistant.helpers.label_registry` (`lr`).
*   **Flow**: When a configuration tag is set (e.g. `AI Generated`), the integration checks if a matching label exists in Home Assistant. If not, it calls `label_reg.async_create(tag)`.
*   **Entity Registration Delay**: Because Home Assistant reloads the automations/scripts asynchronously after writing the files, the entity might not appear in the `entity_registry` instantly. To solve this, `_async_assign_tag` runs a retry loop (up to 5 attempts, waiting 0.5s between retries) to fetch the entity ID, retrieve the entry, and merge the new label ID into `entry.labels`.

### 5. LLM Intent Mapping
*   **Intents**: Custom intents (`CreateAutomation`, `DeleteAutomation`, `CreateScript`, `DeleteScript`, `GetExposedNotifyEntities`, `EnumerateActions`, `GetActionDetails`) are registered in [intent.py](file:///home/jeff/code/ai-generated-tools/home-assistant-meta/custom_components/automation_script_manager/intent.py).
*   **Tool Discovery**: Home Assistant's Assist API automatically gathers all intent handlers registered in the system (excluding a hardcoded `IGNORE_INTENTS` list) and presents them as OpenAPI tools to conversation agents.
*   **LLM Instructions**: The description property on `CreateAutomationIntent` and `CreateScriptIntent` is heavily populated with YAML examples, guidelines on when to choose automations vs. scripts, and scheduling/cancellation hints. This metadata is parsed by the LLM during function-calling planning. The `GetExposedNotifyEntities` intent allows the LLM to query exposed and available `notify` entities. The `EnumerateActions` intent lists all registered action/service names with their descriptions, and the `GetActionDetails` intent fetches argument/field schemas for any specific action so that the LLM can dynamically build and call actions.

---

## Guidelines for Future Enhancements

*   **Upstream Updates**: When updating this component, ensure that the imports from `homeassistant.components.automation.config` and `homeassistant.components.script.config` match the signatures of the targeted Home Assistant core version.
*   **Voluptuous Schemas**: When modifying service schemas in `__init__.py`, replicate the changes in the `slot_schema` properties inside `intent.py` so the LLM tools remain in sync with the Python services.
*   **Entity Deletion Registry Cleaning**: When deleting an automation or script, always clean up the entity registry via `ent_reg.async_remove(entity_id)` before triggering the reload. Failing to do so can leave orphan entity registry records (often visible as red circles or read-only entities in the HA UI).
