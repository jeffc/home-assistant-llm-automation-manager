# Todo List

- [x] **Configurability & Hard Enforcement of Allowed Actions**
  - Add an options flow setting `expose_actions_mode` ("expose_all_except" or "expose_only_these").
  - Add a multi-select option `exposed_actions_list` in the options flow using a `SelectSelector` populated with:
    - Domains (prefixed with `domain:`, e.g., `domain:light`)
    - Individual actions (prefixed with `action:`, e.g., `action:light.turn_on`)
  - Update `EnumerateActions` intent handler to filter actions based on these choices.
  - Update the validation engine to reject creating or updating automations/scripts that reference any action not allowed under these rules.


- [ ] **LLM Generation Debug Mode**
  - Add a boolean setting `debug_mode` to the options flow.
  - When enabled, add an optional `reasoning` slot to the `CreateAutomation` and `CreateScript` intents.
  - The intent handler should log this reasoning in `home-assistant.log` and return it somehow to the user.

- [x] **Force Self-Disable for One-Shots / Override Deletes**
  - Add a configuration toggle to the options flow to force self-disable instead of self-delete.
  - When enabled:
    - **Automations**:
      - Calling `delete_automation` does not delete the YAML entry; it disables
        (turns off) the automation and logs the override. Possibly also adds a
        "would be deleted" tag
    - **Scripts**:
      - Completion action is rewritten to call a script disable routine instead of `delete_script` and adds a tag
      - Calling `delete_script` (or completion deactivation) does not remove the YAML entry; it modifies the script to:
        1. Prepend a persistent notification warning that the disabled script was called.
        2. Prepend a `stop` action to halt any further execution.
        3. Log the override.

- [x] **Auto-Tagging for One-Shot Scripts**
  - Add a second tag configuration option `one_shot_tag` (default: `one-shot`) to the options flow.
  - When a temporary/one-shot entity (having `delete_self` or `disable_self` completion actions) is created, automatically assign **both** the general tag and this new `one_shot_tag`.

- [x] **Robust Automation/Script Action & Trigger Validation**
  - Added checks to prevent creating/updating automations/scripts without actions or triggers. This prevents LLMs from creating empty entities that only self-destruct/disable.

- [x] **One-Shot Conditional Block Prompting ("do X when Y if Z")**
  - Update the description of `CreateAutomationIntent` in `intent.py` to instruct the LLM:
    - When creating a temporary/one-shot automation with a condition (e.g., "do X when Y if Z"), it should place the condition inside a conditional action block (`if`-`then` inside the action list) instead of using a top-level `condition`.
    - This ensures the automation triggers and always executes the self-destruct/disable completion action regardless of whether the condition is true or false.

- [ ] **Managed Entity Diagnostics (`GetManagedEntityErrors`)**
  - Implement an intent handler to retrieve recent runtime errors or execution traces for entities created by this integration.
  - Track created entities using an independent local JSON datastore/log (e.g., via Home Assistant's `Store` class in `.storage/`) rather than relying purely on tags, which the user might not have configured.
  - Explore setting metadata on entities (e.g., prefixing unique IDs in YAML with `asm_` or using entity registry options) to identify integration-created entities.
  - Helps LLM agents diagnose post-creation runtime failures.
