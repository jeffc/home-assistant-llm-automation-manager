# Automation & Script Manager (Home Assistant Custom Integration)

A custom integration for Home Assistant that allows you to programmatically create, update, and delete automations and scripts. It exposes these actions as standard Home Assistant services (actions) and registers them as native LLM tools for conversational AI agents.

## Features
*   **Programmatic CRUD**: Create, read, update, and delete automations and scripts via action calls without manually editing YAML files.
*   **LLM Tool Integration**: Automatically registers custom intents (`CreateAutomation`, `DeleteAutomation`, `CreateScript`, `DeleteScript`, `GetExposedNotifyEntities`, `EnumerateActions`, `GetActionDetails`) that expose these actions as tools to LLM integrations (like Assist, Google Generative AI, or OpenAI Conversation).
*   **Self-Destructing Sequences**: Create "run-once" or temporary automations/scripts by
    specifying `on_completion: delete_self` or `disable_self`. Self-deletion/disabling calls
    are executed asynchronously in a detached background task to prevent self-cancellation
    when the entity turns off or reloads.
*   **Safety & Tagging**: Automatically assign a label/tag (e.g., `AI Generated`) to entities created via this manager, and optionally restrict deletions so only tagged entities can be deleted.
*   **Structured Feedback**: Services support optional responses. If the YAML configuration fails validation (using Home Assistant Core's native validation engine), the action returns `{"success": false, "error": "Reason"}` to let humans or LLM agents read and correct the parameters.

> [!WARNING]
> **Important File Writing & Reload Behavior**
> 
> This integration directly modifies `automations.yaml` and `scripts.yaml` and triggers an engine reload (`automation.reload` or `script.reload`) to apply the changes immediately.
> 
> If you have unapplied manual changes in these files, triggering any service call through this integration will reload the entire configuration from disk, causing those manual changes to become active unexpectedly. Make sure to commit or apply manual modifications before using this integration.

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
1.  **Entity Tag (Label)**: A custom label name automatically assigned to all created
    automations and scripts. Defaults to `CREATED_WITH_AUTOMATION`.
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
7.  **Let LLM assign icons**: If enabled, the AI assistant will be allowed to choose custom icons for
    created/updated entities and will be equipped with the `GetCommonIcons` search tool.
8.  **Prompt LLM to be explicit about one-time vs recurring**: If enabled, the LLM will be explicitly
    instructed in the tool description to state in its response whether the generated automation is
    one-time or recurring. (Note that the guidance to ask the user if it is not clear remains active
    regardless of this setting).
9.  **Categorize Mode**: Specifies how to categorize generated scripts and automations:
    - `Leave uncategorized`: Does not assign any category.
    - `Put in specified category`: Automatically assigns a preselected category for all automations and scripts.
    - `Auto-categorize`: Instructs the LLM to inspect existing categories, choose the most relevant one, and assign it to the entity.
10. **Specified Automation Category**: The category to assign to generated automations (used when "Put in specified category" is selected).
11. **Specified Script Category**: The category to assign to generated scripts (used when "Put in specified category" is selected).
12. **Always assign a category**: When using `Auto-categorize`, if this is enabled, the LLM must choose a category even if there isn't a strong match. If disabled, it can leave the entity uncategorized.
13. **Allowed Action Regexes**: Regular expressions (one per line) specifying allowed actions.
    Leave empty to default to allowing all actions.
14. **Denied Action Regexes**: Regular expressions (one per line) specifying blocked actions.
    Checked before the allowlist.
15. **LLM Generation Debug Mode**: Enable debug mode to allow LLM intent handlers to accept an
    optional reasoning parameter, log it to `home-assistant.log`, include it in the description of
    the generated entity, and return it. Note that the "reasoning" slot (along with all other tool
    call outputs) can also be found in the standard Home Assistant "debug conversation" view.

*Note: The generation date and time (timestamp) is always automatically appended to the description of any created automation or script.*

### Regular Expression Action Filtering
Action permissions are controlled using two multiline text fields on the configuration page:
*   **Denied Action Regexes**: Regular expressions matching blocked actions.
    Defaults to `homeassistant\..*`.
*   **Allowed Action Regexes**: Regular expressions matching allowed actions.
    Defaults to `.*` (allow all).

Lines starting with `#` are treated as comments and ignored.

**Resolution Logic:**
1.  **Neither specified (empty)**: All actions are permitted.
2.  **Only Allowed specified**: Only actions matching one or more allowed regexes are permitted.
3.  **Only Denied specified**: All actions are permitted except those matching one or more denied regexes.
4.  **Both specified**: Denied list is checked first (matching blocks the action). If not denied,
    it must match one or more allowed regexes to be permitted; otherwise, it is blocked.
5.  **Wildcard matching**: Adding a wildcard (`.*`) to the end of the allowlist
    will allow any action except those explicitly matched on the denylist.

#### Examples of Regex Policies

##### Scenario A: Permissive Mode with System Safety (Default)
Allows all actions except sensitive system-level commands.
*   **Denied Action Regexes:**
    ```text
    # Block internal Home Assistant controls, updates, and integrations setup
    homeassistant\..*
    update\..*
    hassio\..*
    ```
*   **Allowed Action Regexes:**
    ```text
    # Allow all other domains and actions
    .*
    ```

##### Scenario B: Minimalist Strict Allowlist
AI can only control lights, media players, and climate settings.
*   **Denied Action Regexes:**
    *(Empty)*
*   **Allowed Action Regexes:**
    ```text
    # Explicitly permit only these safe domains
    light\..*
    media_player\..*
    climate\..*
    ```

##### Scenario C: Lock & Security Protection (Block Specific Services)
Allows broad control but prevents the LLM from unlocking doors or opening garage doors.
*   **Denied Action Regexes:**
    ```text
    # Block physical entry/security actions
    lock\.unlock
    cover\.open
    alarm_control_panel\.alarm_disarm
    ```
*   **Allowed Action Regexes:**
    ```text
    # Allow everything except the blocked security actions
    .*
    ```

##### Scenario D: Combined Strict Policy
Allow only home entertainment controls, but prevent turning off any security cameras or sirens.
*   **Denied Action Regexes:**
    ```text
    # Prevent disabling safety alerts
    siren\.turn_off
    camera\.turn_off
    ```
*   **Allowed Action Regexes:**
    ```text
    # Allow media players, lights, and switches
    media_player\..*
    light\..*
    switch\..*
    ```

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
Retrieves a list of all registered Home Assistant actions (services) and whether they are allowed or blocked by the configured security policies (regular expression rules).

This service returns a response and can be executed from the **Developer Tools -> Actions (Services)** tab.

**Parameters:**
- `verbose` (Optional): A boolean that, when set to `true`, returns detailed information about why each action is allowed or blocked (which pattern or matching regex list was used). Defaults to `false`.

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
    turn_on: "Allowed by regex allowlist (matched 'light\\..*')"
    turn_off: "Allowed by regex allowlist (matched 'light\\..*')"
  switch:
    turn_on: "Allowed by regex allowlist (matched 'switch\\..*')"
blocked:
  lock:
    unlock: "Blocked by regex denylist (matched 'lock\\..*')"
  climate:
    set_temperature: "Blocked because it did not match any pattern in the regex allowlist"
```

### `automation_script_manager.get_entity_traces`
Retrieves recent execution runs and detailed step traces for a specific automation or script entity. Unlike the LLM intent, this user-callable action has no exposure restrictions and can query traces for any automation or script.

**Parameters:**
- `entity_id` (Required): The entity ID of the automation or script (e.g. `automation.my_automation` or `script.my_script`).
- `run_id` (Optional): The optional execution Run ID. If omitted, defaults to the most recent run.

### `automation_script_manager.get_template_helper_docs`
Retrieves documentation, python signatures, and descriptions for available Jinja2 template functions, filters, and tests.

**Parameters:**
- `search_term` (Optional): A search term to filter helper names and descriptions.
- `only_custom` (Optional): A boolean that, when set to `true`, only returns Home Assistant specific custom template helpers (hides standard Jinja2 defaults). Defaults to `true`.

### `automation_script_manager.render_template`
Evaluates (renders) a Jinja2 template with optional variables and returns the result.

**Parameters:**
- `template` (Required): The Jinja2 template string to render.
- `variables` (Optional): A dictionary of variables to pass into the template context.

### `automation_script_manager.get_common_icons`
Search common icons, active server icons, or validate any Material Design Icon (MDI) used in Home Assistant.

**Parameters:**
- `search_term` (Optional): A search term to filter icon name, category, or description within the common/active icons list.
- `icon_to_validate` (Optional): A specific icon name (e.g. `mdi:lightbulb`) to check if it exists in Home Assistant's full MDI database.

---

## Conversation AI Intents (LLM Tools)
The integration automatically registers custom intents that are exposed as tools to conversation agents:
- **`GetEntityTraces`**: Allows the LLM to get execution traces and recent run details for a specific automation or script entity.
  *   **Restriction**: To preserve user privacy and security, this intent enforces that the target entity **must be exposed** to the conversation assistant (i.e. `async_should_expose(hass, "conversation", entity_id)` must be true). If the entity is not exposed, the tool call returns an error.
- **`GetTemplateHelperDocs`**: Allows the LLM to search or inspect the available Jinja2 template helper functions, filters, and tests registered in Home Assistant to aid in template generation.
- **`RenderTemplate`**: Allows the LLM to evaluate (render) any Jinja2 template with optional variables. This can be used to test template expressions or render dynamic output for the user.
- **`GetCommonIcons`**: Allows the LLM to search common and active server MDI icons, or validate that a specific icon exists in the full MDI database.
