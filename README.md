# Automation & Script Manager (Home Assistant Custom Integration)

A custom integration for Home Assistant that allows you to programmatically create, update, and delete automations and scripts. It exposes these actions as standard Home Assistant services (actions) and registers them as native LLM tools for conversational AI agents.

## Features
*   **Programmatic CRUD**: Create, read, update, and delete automations and scripts via action calls without manually editing YAML files.
*   **LLM Tool Integration**: Automatically registers custom intents (`CreateAutomation`, `DeleteAutomation`, `CreateScript`, `DeleteScript`) that expose these actions as tools to LLM integrations (like Assist, Google Generative AI, or OpenAI Conversation).
*   **Self-Destructing Sequences**: Create "run-once" or temporary automations/scripts by specifying `on_completion: delete_self` or `disable_self`.
*   **Safety & Tagging**: Automatically assign a label/tag (e.g., `AI Generated`) to entities created via this manager, and optionally restrict deletions so only tagged entities can be deleted.
*   **Structured Feedback**: Services support optional responses. If the YAML configuration fails validation (using Home Assistant Core's native validation engine), the action returns `{"success": false, "error": "Reason"}` to let humans or LLM agents read and correct the parameters.

---

## Directory Structure
```
custom_components/automation_script_manager/
├── __init__.py          # Core logic, service registration, validation, locks, and file writes
├── const.py             # Domain constant
├── config_flow.py       # Config & Options Flow handler (UI Setup & Settings)
├── services.yaml        # Action metadata, descriptions, and UI selectors
├── intent.py            # Custom intent handlers mapping actions to LLM tools
└── translations/
    └── en.json          # Translation strings for UI configuration fields
```

---

## Installation & Testing

### Testing Locally (Cloned Core)
A developer script is provided to automate testing. It sets up a virtual environment, installs dependencies from the cloned `core/` repository, and starts a test Home Assistant instance:

```bash
./run_test.sh
```

1.  Open your browser and navigate to `http://localhost:8123`.
2.  Complete the onboarding setup.
3.  Go to **Settings -> Devices & Services -> Add Integration** and select **Automation & Script Manager**.

---

## Configuration Options
Click the **Configure** button on the integration card to modify global settings:
1.  **Entity Tag (Label)**: A custom label name (e.g., `AI Generated`) automatically assigned to all created automations and scripts.
2.  **Restrict deletion to tagged entities only**: Protects your system by preventing delete actions from deleting any entity that does not have the specified tag.
3.  **Expose AI LLM Tools**: Enable/disable exposing the creation and deletion actions to voice/LLM assistants.

---

## Actions (Services)

### `automation_script_manager.create_automation`
Creates or updates an automation.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | string (optional) | The unique ID of the automation. |
| `entity_id` | string (optional) | Resolves to the config ID if specified. E.g., `{{ this.entity_id }}`. |
| `config` | dict (optional) | The full automation dictionary configuration. |
| `alias` | string (optional) | Friendly name. |
| `description` | string (optional) | Description. |
| `trigger` | list/dict (optional) | Trigger configuration. |
| `condition` | list/dict (optional) | Condition configuration. |
| `action` | list/dict (optional) | Action configuration. |
| `mode` | string (optional) | Execution mode (`single`, `restart`, `queued`, `parallel`). |
| `on_completion` | string (optional) | Action after run (`delete_self`, `disable_self`, `persist`). Default: `persist`. |

**Example YAML:**
```yaml
action: automation_script_manager.create_automation
data:
  id: run_once_welcome
  alias: Run Once Welcome
  on_completion: delete_self
  trigger:
    - platform: homeassistant
      event: start
  action:
    - action: persistent_notification.create
      data:
        message: "Home Assistant has started! Deleting this automation now."
```

### `automation_script_manager.delete_automation`
Deletes an automation. Either `id` or `entity_id` is required.

```yaml
action: automation_script_manager.delete_automation
data:
  entity_id: automation.run_once_welcome
```

### `automation_script_manager.create_script`
Creates or updates a script.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | string (optional) | The unique slug (lowercase letters, numbers, underscores). |
| `entity_id` | string (optional) | Resolves to the config ID. E.g., `{{ this.entity_id }}`. |
| `config` | dict (optional) | The full script dictionary configuration. |
| `alias` | string (optional) | Friendly name. |
| `description` | string (optional) | Description. |
| `sequence` | list/dict (optional) | The script sequence steps. |
| `mode` | string (optional) | Execution mode. |
| `on_completion` | string (optional) | Action after run (`delete_self`, `persist`). Default: `persist`. |

**Example YAML:**
```yaml
action: automation_script_manager.create_script
data:
  id: self_destructing_script
  alias: Self Destructing Script
  on_completion: delete_self
  sequence:
    - action: light.turn_on
      target:
        entity_id: light.living_room
```

### `automation_script_manager.delete_script`
Deletes a script. Either `id` or `entity_id` is required.

```yaml
action: automation_script_manager.delete_script
data:
  entity_id: script.self_destructing_script
```
