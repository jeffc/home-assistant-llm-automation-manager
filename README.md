# Automation & Script Manager (Home Assistant Custom Integration)

A custom integration for Home Assistant that allows you to programmatically create, update, and delete automations and scripts. It exposes these actions as standard Home Assistant services (actions) and registers them as native LLM tools for conversational AI agents.

## Features
*   **Programmatic CRUD**: Create, read, update, and delete automations and scripts via action calls without manually editing YAML files.
*   **LLM Tool Integration**: Automatically registers custom intents (`CreateAutomation`, `DeleteAutomation`, `CreateScript`, `DeleteScript`, `GetExposedNotifyEntities`, `EnumerateActions`, `GetActionDetails`) that expose these actions as tools to LLM integrations (like Assist, Google Generative AI, or OpenAI Conversation).
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
1.  **Entity Tag (Label)**: A custom label name (e.g., `AI Generated`) automatically assigned to
    all created automations and scripts.
2.  **One-Shot Entity Tag (Label)**: A second label name (defaulting to `one-shot`) automatically
    assigned to all created temporary/one-shot entities in addition to the global tag.
3.  **Restrict deletion to tagged entities only**: Protects your system by preventing delete actions
    from deleting any entity that does not have the specified tag.
4.  **Disable instead of delete**: If enabled, self-destruct/deletion requests will disable
    automations and modify scripts to prevent execution instead of deleting their files.
5.  **Disable Override Tag (Label)**: A label name (defaulting to `would-be-deleted`) assigned
    to entities when they would have been deleted but are instead disabled.
6.  **Expose AI LLM Tools**: Enable/disable exposing the creation and deletion actions to voice/LLM
    assistants.
7.  **Use regular expression rules**: Enable specifying custom regular expression lists to restrict
    allowed actions on a separate configuration page.

### Regular Expression Action Filtering
If **Use regular expression rules** is enabled on the main options page, the flow advances to a subpage with two multiline text fields:
*   **Allowed Action Regexes**: Regular expressions (one per line) specifying allowed actions.
*   **Denied Action Regexes**: Regular expressions (one per line) specifying blocked actions.

**Resolution Logic:**
1.  **Only Allowed specified**: Only actions matching one or more allowed regexes are permitted.
2.  **Only Denied specified**: All actions are permitted except those matching one or more denied regexes.
3.  **Both specified**: Denied list is checked first (matching blocks the action). If not denied, it must match one or more allowed regexes to be permitted; otherwise, it is blocked.
4.  **Wildcard matching**: Adding a wildcard (`.*`) to the end of the allowlist will allow any action except those explicitly matched on the denylist.

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
| `validate_only` | boolean (optional) | Perform a dry-run validation check without saving. |

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
| `validate_only` | boolean (optional) | Perform a dry-run validation check without saving. |

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

### `automation_script_manager.get_allowed_actions`
Retrieves a list of all registered Home Assistant actions (services) and whether they are allowed or blocked by the configured security policies (including mode, domains, action overrides, and regex rules).

This service returns a response and can be executed from the **Developer Tools -> Actions (Services)** tab.

**Parameters:**
- `verbose` (Optional): A boolean that, when set to `true`, returns detailed information about why each action is allowed or blocked (which policy or matching regex/list was used). Defaults to `false`.

**Example Response (Default, Non-Verbose):**
```yaml
allowed:
  light:
    - turn_on
    - turn_off
  switch:
    - turn_on
blocked:
  lock:
    - unlock
  climate:
    - set_temperature
```

**Example Response (Verbose):**
```yaml
allowed:
  light:
    turn_on: "Allowed by default (global mode: allow_all)"
    turn_off: "Allowed by default (global mode: allow_all)"
  switch:
    turn_on: "Allowed by default (global mode: allow_all)"
blocked:
  lock:
    unlock: "Blocked by default fallback (global mode: expose_only_these)"
  climate:
    set_temperature: "Blocked by default fallback (global mode: expose_only_these)"
```
