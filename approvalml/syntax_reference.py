"""
ApprovalML YAML Syntax Reference for AI Workflow Generation

This module contains the complete syntax reference for ApprovalML workflows,
designed to be used by AI engines (like Google Gemini) to generate valid
YAML workflow definitions from natural language descriptions.
"""

APPROVALML_SYNTAX_REFERENCE = """
# ApprovalML YAML Syntax Reference for AI Workflow Generation

## Overview
ApprovalML is a YAML-based workflow definition language for business approval processes. It combines form field definitions with dynamic workflow routing logic.

## Core Structure
Every ApprovalML YAML file has this basic structure:

```yaml
name: "Workflow Name"
description: "Brief description of the workflow"
version: "1.0"  # Optional
type: "workflow_type"  # Optional

# Optional submission criteria — controls who can SUBMIT the workflow
submission_criteria:
  company_roles: []  # Array of roles that can submit
  org_hierarchy:
    include_paths: ["1.1.*"]  # Organizational path patterns

# Optional view access — controls who can VIEW ALL submissions in the workflow list
# Users whose company_roles intersect this list get a "My Requests / All Submissions" toggle
# Leave empty (or omit) to use default participant-scoped access (requestor + approvers + managers)
view_all_roles: []  # e.g. ["finance", "admin", "hr"]

# Form definition
form:
  # Optional page-repeating header zone (field names referenced from fields[])
  # Supports grid (rows), columns (column stacks), or both mixed — see full reference below
  header:
    fields: []        # Zone-local field definitions (not rendered in form body)
    grid: []          # e.g. [["company_name", "invoice_no"], ["company_address"]]
    # OR columns mode:
    # columns: []     # e.g. [["company_logo"], ["company_name", "company_address"]]
    # column_widths: []  # e.g. ["auto", "1fr"]

  # Optional layout configuration for sectioned form body
  layout:
    sections: []           # Section structure (references field names)
    completed_sections: [] # Section IDs shown (read-only) when workflow has no pending step
    responsive: {}

  # Optional footer — either field-zone grid or legacy item-based
  footer:
    grid: []  # Field-zone style: [["footer_note", "page_no"]]
    # OR legacy item-based:
    # columns: {}
    # items: []

  # Form fields (defined separately from layout)
  fields: []  # Array of field definitions

# Workflow logic (must be dict/object, NOT list/array)
workflow:
  step_name: {}  # Step names as keys

# Optional settings
settings:
  timeout: {}
  escalation: []
  notifications: {}
  compliance: {}
```

**CRITICAL FORMAT REQUIREMENTS:**
1. ✅ **Workflow Format:** Must be a dictionary with step names as keys: `workflow: { step_name: {...} }`
   - ❌ **DO NOT** use list format: `workflow: [{ name: "step_name", ... }]`

2. ✅ **Form Sections:** Must separate `layout.sections` from `fields`: `form: { layout: {...}, fields: [...] }`
   - ❌ **DO NOT** embed fields inside sections: `form: [{ section: { fields: [...] } }]`

3. ✅ **Step Types:** Use `decision`, `parallel_approval`, `conditional_split`, `automatic`, `notification`, `end`
   - ❌ **DO NOT** use deprecated type: `approval`

4. ✅ **Key Order:** Always output top-level keys in this exact canonical order:
   `name → description → version → type → triggers → submission_criteria → view_all_roles → form → workflow → settings`
   - Any additional top-level keys not in this list should appear after `settings`
   - ❌ **DO NOT** place `form` or `workflow` before `name`/`description`

## Triggers (Optional)

Use `triggers` when the workflow is started automatically — by a schedule or an incoming event — rather than manually by a user.
Omit `triggers` entirely for workflows that users submit through the form UI.

### Trigger Types

#### `cron` — Scheduled execution
Runs the workflow automatically on a schedule. `schedule` is a standard 5-field cron expression.

```yaml
triggers:
  - type: cron
    schedule: "0 * * * *"   # every hour on the hour
```

Common cron expressions:
| Schedule            | Expression        |
|---------------------|-------------------|
| Every hour          | `0 * * * *`       |
| Every 30 minutes    | `*/30 * * * *`    |
| Daily at 9 AM       | `0 9 * * *`       |
| Every Monday 9 AM   | `0 9 * * 1`       |
| First of month      | `0 0 1 * *`       |
| Every 6 hours       | `0 */6 * * *`     |

#### `webhook` — Event-driven execution
Starts the workflow when an external system sends an HTTP request (e.g. an alert, a data push).
No `schedule` field is used.

```yaml
triggers:
  - type: webhook
```

#### Combined — triggered by either
```yaml
triggers:
  - type: cron
    schedule: "0 * * * *"
  - type: webhook
```

### Trigger Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | ✅ Yes | `cron`, `webhook`, or `one_time` |
| `schedule` | For `cron`/`one_time` | Cron expression, e.g. `0 9 * * *` for daily 9 AM |
| `max_runs` | No | Auto-pause after N executions |
| `allow_concurrent` | No | `false` (default) — skip run if a previous instance from this trigger is still in progress. Set `true` to allow overlap. |
| `preset_form_data` | No | Static form values to inject on launch |
| `requestor_email` | No | Email of the employee to treat as submitter |
| `requestor_company_role` | No | **Recommended for scheduled workflows** — the first active employee with this `company_role` becomes the submitter |
| `data_condition` | No | Fetch external data and only launch if changes are detected |

### Best Practice: Use `requestor_company_role` for Ownership

For scheduled workflows, pinning ownership to a single person (`requestor_email`) creates a bottleneck and a single point of failure. If that person leaves, the workflow breaks.

Instead, use `requestor_company_role` to distribute ownership across a functional role:

```yaml
triggers:
  - type: cron
    schedule: "0 9 * * 1"  # Every Monday 9 AM
    requestor_company_role: "finance_manager"
    preset_form_data:
      report_type: "weekly_payroll"
```

**How it works:**
- At each scheduled tick, the system queries active employees for the first person with that company role.
- If that employee leaves, the next tick automatically finds the next active employee with that role.
- The resolved requestor ID is stamped in the instance's metadata for audit purposes.

**Resolution priority:** `requestor_id` → `requestor_email` → `requestor_company_role` → `workflow.created_by`

### Concurrency Control (`allow_concurrent`)

By default, if a previous instance started by this trigger is still `in_progress`, the next scheduled run is **skipped** to prevent double-execution. This is the safe default for workflows that must not overlap (payroll, compliance audits, sequential reporting).

```yaml
triggers:
  - type: cron
    schedule: "0 9 * * 1"   # Every Monday 9 AM
    # allow_concurrent: false  ← this is the default; omitting it is equivalent
```

Set `allow_concurrent: true` when each run is fully independent and overlapping executions are intentional:

```yaml
triggers:
  - type: cron
    schedule: "0 * * * *"   # Every hour
    allow_concurrent: true   # Each hourly snapshot is independent — overlap is fine
```

**Skipped runs do not delay future runs** — the cron schedule advances normally regardless.

**When NOT to set `allow_concurrent: true`:**
- Payroll, billing, or financial workflows (double-run = duplicate charges)
- Sequential review processes where the next run depends on the prior outcome
- Any workflow that modifies shared state or sends external notifications on completion

### When to use triggers

- User says "every hour", "daily", "nightly", "weekly", "every Monday", "on a schedule" → `type: cron`
- User says "when an event occurs", "when data arrives", "via API", "incoming webhook" → `type: webhook`
- User says nothing about scheduling or events (manual form submission) → **omit** triggers entirely

### Cron workflows and form fields

When a workflow is cron-triggered, the form fields receive their values from automatic steps (data source fetches), not from user input. Use `type: textarea` for fields approvers should see, and `type: text` with `hidden: true` for intermediate computed values that only workflow logic reads.

## Form Field Types

### Basic Field Types
- `text` - Single line text input
- `label` - Static text display (no input, for headings or instructions)
- `textarea` - Multi-line text input
- `email` - Email validation with validation
- `number` - Numeric input with validation
- `currency` - Money amount with formatting
- `date` - Date picker
- `dropdown` - Dropdown select (alias for `select` - more intuitive naming)
- `select` - Dropdown with predefined options
- `multiselect` - Multiple selection dropdown
- `checkbox` - Boolean checkbox
- `radio` - Radio button group (supports `display_as: "buttons"` for button-style display)
- `file_upload` - File attachment (supports `capture: "camera"` for mobile camera)
- `signature` - Digital signature capture (drawing or saved signature)
- `richtext` - Rich text editor (WYSIWYG) with HTML and image support
- `hidden` - **Deprecated.** Use `type: text` with `hidden: true` instead (see Field Properties below)
- `line_items` - Dynamic table with repeating rows
- `autocomplete` - Search-as-you-type field with data source integration
- `autonumber` - Auto-incrementing sequential number (e.g. EXP-00042). Read-only; generated at submission. Supports `prefix` and `pad_length`.
- `json` - Structured JSON data field with interactive tree view and syntax highlighting support.

### Additional Field Display Properties
```yaml
- name: "field_name"
  type: "text"
  label: "Display Label"
  show_label: false   # If false, hides the label caption (useful in header/footer zones)
  width: "120px"      # Column width (CSS value: "120px", "15%", "auto") — line_items columns only
```
`width` is for `item_fields` inside `line_items` to set column widths.
`show_label: false` suppresses the label so only the field value appears — common in invoice headers.

**Layout attributes (`align`, `bottom_border`) belong in `layout.defaults` or `section.fields`, not on
the field definition.** Keeping them on the field only makes sense for `item_fields` (table columns)
and header/footer zone fields where the layout layer does not apply.

```yaml
# ✅ Correct — layout attributes in the layout layer
form:
  layout:
    fields:
      amount:
        align: right        # default for this field across all sections
    sections:
      - id: summary
        grid: [["amount"]]
        fields:
          amount:
            bottom_border: true   # only in this section

# ❌ Avoid — layout attributes directly on the field
form:
  fields:
    - name: amount
      type: currency
      label: Amount
      align: right          # don't do this for layout-section fields
      bottom_border: true
```

### Field Properties
```yaml
- name: "field_name"          # Required: unique identifier
  type: "field_type"          # Required: see types above
  label: "Display Label"      # Required: shown to user
  required: true/false        # Required: field validation
  placeholder: "hint text"    # Optional: input placeholder
  accept: ".pdf,.jpg,.png"    # For file_upload: accepted types
  multiple: true/false        # For file_upload/multiselect: allow multiple

  # Visual styling for emphasis (optional)
  style: "warning"            # Options: "warning", "danger", "success", "info"

  # Validation rules
  validation:
    min: 0.01                # Minimum value (number/currency)
    max: 10000              # Maximum value (number/currency)
    min_value: 1            # Alternative syntax
    max_value: 1000

  # Static options (for select/radio/multiselect)
  options:
    - value: "option_key"
      label: "Display Text"

  # OR dynamic options from data source:
  # options:
  #   data_source:
  #     source_name: "My Source"   # Human-readable name (portable; lookup field for the data source name)
  #     value_field: "id"
  #     label_field: "name"
  #     display: "{name} - {code}"  # Optional template

  # Currency fields - optional currency code
  currency: "USD"              # Optional: ISO currency code (USD, EUR, JPY, etc.)

  # Visibility control
  hidden: true      # invisible in the UI; value is still in form data and available to workflow logic
  print_only: true  # shown in PDF only; hidden in the web form
```

**`hidden: true`** — use for fields that automatic steps write into and workflow conditions read, but approvers do not need to see. Must be `type: text` or `type: textarea`.

**`print_only: true`** — use for fields that should appear in the PDF document but not in the form UI.

```yaml
- name: "weather_raw"
  type: text
  label: "Weather Data"
  hidden: true
```

### Field Style Property
Use the `style` property to visually emphasize important fields in the approval UI:

| Style | Background | Use Case |
|-------|------------|----------|
| `warning` | Amber/Yellow | Changes requiring attention, diff results |
| `danger` | Red | Critical items, deletions, errors |
| `success` | Green | Positive outcomes, confirmations |
| `info` | Blue | Informational, read-only context |

Example:
```yaml
- name: "change_summary"
  type: "textarea"
  label: "Change Summary"
  style: "warning"           # Renders with amber background
  required: false
```

### Currency Field Example
```yaml
- name: "total_amount"
  type: "currency"
  label: "Total Amount"
  required: true
  currency: "USD"              # Optional: defaults to company setting
  validation:
    min: 0.01
    max: 50000
```

### Advanced Field Properties

These properties control the presentation and behavior of certain field types.

#### Button-style Choices

For `radio` fields, you can render the options as a button group instead of traditional radio inputs by using the `display_as` property.

```yaml
- name: "equipment_check"
  type: "radio"
  label: "Is all equipment accounted for?"
  required: true
  display_as: "buttons"  # Renders choices as buttons
  options:
    - { value: "yes", label: "Yes" }
    - { value: "no", label: "No" }
    - { value: "na", label: "N/A" }
```

#### Camera-Only File Upload

For `file_upload` fields, you can force the use of the device camera for capturing images directly.

- `capture`: Set to `"environment"` to prefer the rear-facing camera or `"user"` for the front-facing camera.
- `multiple`: Set to `true` to allow multiple captures, or `false` (default) for a single image.

```yaml
- name: "site_photo"
  type: "file_upload"
  label: "Take a photo of the work site"
  required: true
  accept: "image/*"
  multiple: false
  capture: "environment" # Opens the rear camera directly
```

### Richtext Field Example
```yaml
- name: "description"
  type: "richtext"
  label: "Detailed Description"
  required: true
  placeholder: "Enter a detailed description with formatting and images..."
```

**Features:**
- WYSIWYG editor with formatting toolbar (bold, italic, headings, lists, links)
- Image support: paste images or upload from file (automatically converted to base64)
- HTML content saved to storage: `workflows/{workflow_id}/instances/{instance_id}/richtext/{field_name}.html`
- Images are embedded as base64 data URLs within the HTML
- Auto-saves content when editing

**Storage:**
- Content is saved to S3/local storage as a single HTML file
- Path structure: `companies/{company_id}/workflows/{workflow_id}/instances/{instance_id}/richtext/{field_name}.html`
- In test mode, returns synthetic path without actual storage

### Advanced Field Types

#### Line Items (Repeatable Sections)
```yaml
- name: "items_to_purchase"
  type: "line_items"
  label: "Items to Purchase"
  min_items: 1
  max_items: 20

  item_fields:
    - name: "item_description"
      type: "text"
      label: "Description"
      required: true
    - name: "quantity"
      type: "number"
      label: "Qty"
      validation:
        min_value: 1
    - name: "unit_price"
      type: "currency"
      label: "Unit Price"
    - name: "total"
      type: "currency"
      label: "Total"
      readonly: true
      calculated: true
      formula: "quantity * unit_price"
```

#### Calculated Fields with JSONata (Top-Level Form Fields)
Use `calculated: true` with `jsonata` instead of `formula` when you need cross-collection
aggregations or expressions that go beyond simple arithmetic. The JSONata expression receives
the full form data object and is evaluated server-side on every automatic step.

**Common use case — sum a line_items column:**
```yaml
- name: "total_purchase_amount"
  type: "currency"
  label: "Total Purchase Amount"
  readonly: true
  calculated: true
  jsonata: "$sum(items_to_purchase[].total)"
```

**Other examples:**
```yaml
# Count line items
- name: "item_count"
  type: "number"
  label: "Total Items"
  readonly: true
  calculated: true
  jsonata: "$count(items_to_purchase)"

# Conditional label
- name: "urgency_label"
  type: "text"
  label: "Priority"
  readonly: true
  calculated: true
  jsonata: "total_purchase_amount > 10000 ? 'High Value' : 'Standard'"
```

**Rules:**
- `jsonata` and `formula` are mutually exclusive — use one or the other, never both
- Fields with `jsonata` are system-computed: they are skipped in form validation and never required from the user
- The expression receives the full `request_data` object (all form field values)
- Use `$sum(array[].field)` to aggregate line item columns

#### Autocomplete Field (Search with Data Source)
Autocomplete fields provide search-as-you-type functionality with data source integration.

**Structure:**
All data source configuration is nested under `options.data_source`, with UI behavior in `search`:

```yaml
- name: "employee"
  type: "autocomplete"
  label: "Search Employee"
  required: true
  placeholder: "Type at least 3 characters to search..."
  options:
    data_source:
      source_name: "Employee Directory"  # Data source name used for lookup — use when sharing YAMLs across companies
      params:
        - name: q
          from_field: field.employee      # Search query parameter
      # Response parsing configuration
      object_path: "$.data"               # JSONPath to data array in response
      label_field: "Name"                 # Field to display as label
      display: "{full_name} - {dept}"     # Display template
      # value_field: "id"                 # Optional: extract only this field
  search:
    min_length: 3                         # UI: minimum chars before searching
    debounce_ms: 300                      # UI: debounce delay in milliseconds
    max_results: 50                       # UI: maximum results to show
```

**Storage Modes:**

1. **Store Full Object** (for formula access):
```yaml
options:
  data_source:
    source_name: "Employees"      # Data source name used for lookup
    object_path: "$.data"
    label_field: "full_name"
    display: "{full_name} - {current_department}"
    # No value_field = stores entire object
search:
  min_length: 3
  debounce_ms: 300
  max_results: 50
```
This allows formulas to access all fields: `${employee.current_department}`, `${employee.email}`, etc.

2. **Store Specific Value** (ID or other field):
```yaml
options:
  data_source:
    source_name: "Employees"      # Data source name used for lookup
    object_path: "$.data"
    value_field: "id"                     # Extract and store only this field
    label_field: "full_name"
    display: "{full_name} - {email}"
search:
  min_length: 3
  debounce_ms: 300
  max_results: 50
```
This stores only the `id` value from the selected object.

**Key Properties:**
- **Data Source Config** (in `options.data_source`):
  - `source_name`: Data source name used for lookup.
  - `params`: Parameters to pass to data source
  - `object_path`: JSONPath to extract data array (e.g., `$.data`, `$.results.items`)
  - `value_field`: Field to extract and store; if omitted, stores entire object
  - `label_field`: Field name to use for label
  - `display`: Template string for display (e.g., `"{name} - {email}"`)
- **Search UI Config** (in `search`):
  - `min_length`: Minimum characters before search (default: 3)
  - `debounce_ms`: Delay before search executes (default: 300)
  - `max_results`: Maximum results to display (default: 50)

## Form Layout (Optional)

The layout section allows you to organize form fields into sections with grid-based layouts. This is optional - if not specified, all fields are displayed in a simple list.

**IMPORTANT:** Use the separated section format where `layout` and `fields` are siblings under `form`, NOT inline sections with fields inside.

**CORRECT FORMAT (Separated Sections):**
```yaml
form:
  layout:
    sections:
      - id: "section_id"
        title: "Section Title"
        grid:
          - ["field1", "field2"]  # References to field names
  fields:
    - name: "field1"  # Field definitions are separate
      type: "text"
      label: "Field 1"
    - name: "field2"
      type: "text"
      label: "Field 2"
```

**INCORRECT FORMAT (DO NOT USE):**
```yaml
form:
  - section:  # ❌ WRONG: Inline sections with embedded fields
      title: "Section Title"
      fields:
        - name: "field1"
          type: "text"
```

### Layout Structure
```yaml
form:
  layout:
    # ── Form-scope layout attributes ──────────────────────────────────────
    # Per-field layout attrs applied across all sections unless overridden
    # by section.fields. Keys are field names; values are layout attributes.
    fields:
      amount:
        align: right          # numbers right-aligned everywhere by default
      notes:
        label_position: above # label always above for long fields

    sections:
      - id: "section_id"
        title: "Section Title"
        description: "Optional description shown below title"
        initial: true  # If true, this section is shown during initial submission. DEFAULT: add initial: true to EVERY section so the submitter sees the entire form up front. Only omit it from sections that are explicitly meant to be filled by approvers during workflow steps.
        grid:
          - ["field1", "field2"]  # Row with 2 fields side by side
          - ["field3"]  # Row with 1 field (full width)
          - ["field4", "field5", "field6"]  # Row with 3 fields

        # ── Per-field layout overrides for this section ────────────────────
        # Override layout.defaults for specific fields within this section only.
        # Useful when the same field appears in multiple sections with different styling.
        fields:
          field2:
            align: center
            bottom_border: true

    # Optional responsive breakpoints
    responsive:
      tablet: 2  # Maximum columns per row on tablets
      mobile: 1  # Maximum columns per row on mobile (usually 1)

  fields:
    # Field definitions — identity only (type, label, required, options, validation)
    # Do NOT put align or bottom_border here for layout-section fields.
```

### Layout Features

1. **Sections**: Organize fields into logical groups with titles and descriptions
2. **Grid Layout**: Control field positioning using a row-based grid system
3. **Initial Visibility**: By default, mark EVERY section with `initial: true` so the submitter sees the whole form at creation. Only omit `initial: true` (or set `initial: false`) for sections that are explicitly meant to be filled by approvers during later workflow steps.
4. **Responsive**: Automatically adapts to tablet and mobile screens
5. **Layout Defaults**: Set default layout attributes per field across all sections via `layout.defaults`
6. **Section Overrides**: Override layout per field within a specific section via `section.fields`

### Layout Attribute Priority

Layout attributes are resolved in this order (highest priority wins):

```
section.fields[field_name]  →  layout.fields[field_name]  →  field-level (legacy fallback)
```

### Layout Attribute Reference

These attributes belong in `layout.defaults` or `section.fields`, not on `form.fields`:

| Attribute | Values | Description |
|-----------|--------|-------------|
| `align` | `left` | `center` | `right` | Horizontal alignment of the field value in read-only display |
| `bottom_border` | `true` | `false` | Full-width border below the field entry — acts as a visual separator |
| `span` | `full` | `half` | `auto` | Grid column span hint |
| `valign` | `top` | `middle` | `bottom` | Vertical alignment |
| `label_position` | `above` | `inline` | `hidden` | Label placement relative to value |

**Exception:** `align` and `width` on `item_fields` inside `line_items` should stay on the field — they
define table column properties, not section layout.

### Complete Layout Example
```yaml
name: "Employee Onboarding"
description: "Multi-step onboarding process"

form:
  layout:
    sections:
      - id: "personal_info"
        title: "Employee Details"
        description: "To be filled out by the new employee."
        initial: true
        grid:
          - ["full_name", "personal_email"]  # 2 columns
          - ["phone_number"]  # Full width
          - ["start_date", "position"]  # 2 columns

      - id: "it_setup"
        title: "IT Equipment Setup"
        initial: true
        grid:
          - ["laptop_choice"]
          - ["monitor_request", "keyboard_request", "mouse_request"]
          - ["additional_software"]

    responsive:
      tablet: 2
      mobile: 1

  fields:
    - name: "full_name"
      type: "text"
      label: "Full Name"
      required: true
    - name: "personal_email"
      type: "email"
      label: "Personal Email"
      required: true
    # ... more fields ...
```

### Section Visibility in Workflow Steps

When using layouts, workflow steps can control which sections are visible and editable:

```yaml
workflow:
  it_provisioning:
    name: "IT Provisioning"
    type: "decision"
    approver: "it_support"
    view_sections: ["personal_info"]  # Show as read-only
    edit_sections: ["it_setup"]  # Show as editable
    on_complete:
      continue_to: "hr_finalization"

  hr_finalization:
    name: "HR Finalization"
    type: "decision"
    approver: "hr_manager"
    view_sections: ["personal_info", "it_setup"]  # Multiple sections as read-only
    edit_sections: ["hr_verification"]  # This section is editable
    on_approve:
      end_workflow: true
```

**Important Notes:**
- If a step has no `view_sections` and no `edit_sections`, all sections are displayed in view mode by default
- The `initial: true` sections are shown when the requestor creates the workflow
- Sections without `initial: true` are hidden from the submitter and are typically filled in during approval steps
- **Default generation rule:** put `initial: true` on ALL sections unless the user explicitly describes a multi-stage form where specific sections belong to approvers (e.g. "IT manager fills out the equipment section"). In that case only the submitter-facing sections get `initial: true`.

### Completed View (`completed_sections`)

`completed_sections` controls which sections are shown (read-only) once the workflow has no
pending step — i.e. after full approval, rejection, or any terminal state.  It also applies
to the downloaded PDF.

```yaml
form:
  layout:
    completed_sections:
      - invoice_header_info   # shown first
      - line_items_section
      - totals_section
    sections:
      - id: invoice_entry
        initial: true
        grid: [[ invoice_no ]]
      - id: invoice_header_info
        title: Informasi Invoice
        columns:
          - [ customer_name, customer_address ]
          - [ invoice_no, invoice_date, due_date ]
      - id: line_items_section
        title: Daftar Barang
        grid: [[ invoice_lines ]]
      - id: totals_section
        title: Ringkasan Nilai
        columns:
          - [ authorized_signature ]
          - [ jumlah, total_amount, ppn ]
```

- Sections are rendered in the order listed in `completed_sections`, not their definition order
- Without `completed_sections`, all sections are shown in view mode (existing behaviour)
- The `invoice_entry` section above is intentionally omitted — it only needs to exist during initial submission

## Form Footer (Optional)

Form footers display static content like reference legends, form version information, or instructions. Footers are particularly useful for forms that mirror physical documents.

### Footer Structure

```yaml
form:
  footer:
    # Grid configuration
    columns:
      desktop: 3  # Number of columns on desktop (1-12)
      tablet: 2   # Number of columns on tablet
      mobile: 1   # Number of columns on mobile

    # Container styling (optional)
    padding: "16px"
    background: "#f8f9fa"
    border_top: "2px solid #dee2e6"

    # Footer items
    items:
      - type: "message"     # or "legend", "divider", "image"
        content: "text"
        colspan: 1
        align: "left"       # left, center, right, justify
        valign: "top"       # top, middle, bottom
        style: {}           # Optional CSS styles
```

### Footer Item Types

1. **message** - Display static text or key-value pairs (legends)
2. **legend** - Alias for message type with dict content
3. **divider** - Horizontal separator line
4. **image** - Display image/logo

### Footer Examples

#### Example 1: Simple Version Footer

```yaml
footer:
  items:
    - type: message
      content: "Form Version: GBB-FO-001 Ver 1.0/03-06-2024"
      colspan: 1
      align: right
      style:
        font_size: "12px"
        color: "#6c757d"
```

#### Example 2: Legend with Form Version

```yaml
footer:
  columns:
    desktop: 3
    tablet: 2
    mobile: 1
  padding: "16px"
  background: "#f8f9fa"
  border_top: "2px solid #dee2e6"

  items:
    # Left side: Reference legend (takes 2 columns)
    - type: message
      content:
        BB: "Bahan Baku"
        BP: "Bahan Penunjang"
        BS: "Barang Sisa"
        SP: "Spare Part"
        BJ: "Barang Jadi"
        PTS: "Produk Tidak Sesuai"
      colspan: 2
      align: left
      style:
        border_left: "4px solid #0066cc"
        padding_left: "12px"

    # Right side: Form version (takes 1 column)
    - type: message
      content: "GBB-FO-001 Ver 1.0/03-06-2024"
      colspan: 1
      align: right
      valign: bottom
      style:
        font_size: "12px"
        font_family: "monospace"
        color: "#6c757d"
```

#### Example 3: Multi-Section Footer

```yaml
footer:
  columns:
    desktop: 4
  items:
    # Status codes legend
    - type: message
      content:
        P: "Pending"
        A: "Approved"
        R: "Rejected"
        C: "Cancelled"
      colspan: 2
      align: left

    # Separator
    - type: divider
      colspan: 4

    # Company info
    - type: message
      content: "PT. Company Name - Internal Use Only"
      colspan: 3
      align: center

    # Form code
    - type: message
      content: "FORM-001-2024"
      colspan: 1
      align: right
```

### Footer Style Properties

Common CSS properties supported in `style`:
- `font_size`: "12px", "14px", etc.
- `font_family`: "monospace", "sans-serif", etc.
- `font_weight`: "bold", "normal", "600"
- `color`: "#6c757d", "red", "rgb(0,0,0)"
- `background`: "#f0f0f0"
- `border_left`, `border_right`, `border_top`, `border_bottom`: "2px solid blue"
- `padding`, `padding_left`, `padding_right`: "8px", "12px"
- `margin`: "0", "8px 0"

### Use Cases for Footers

1. **Form Versioning**: Display form code and version for audit trails
2. **Reference Legends**: Show code meanings (e.g., department codes, status codes)
3. **Instructions**: Display submission guidelines or notes
4. **Compliance Info**: Show regulatory references or policies
5. **Contact Info**: Display help desk or support information

## Form Header and Field-Zone Footer (Invoice / Document Style)

For document-style forms (invoices, purchase orders, delivery notes) that must match a printed
layout, use `form.header` and `form.footer` zones that reference fields by name.

These zones **repeat on every printed page** (unlike the body layout which appears once).
Place signature fields and totals in the body layout — not in header/footer zones.

---

### Zone-Local Field Definitions

Fields can be defined directly inside a zone's `fields` list.  These fields exist **only in that
zone** — they are not rendered in the form body, and they take precedence over any same-name field
in `form.fields` (Option A lookup order).

Use this for display-only cells that must not appear in the body:

```yaml
form:
  footer:
    fields:
      - name: footer_ref
        type: text
        label: Referensi Pengiriman
        show_label: false
        placeholder: e.g. SO/OUT-FG/03569
        align: right
    grid:
      - [ footer_catatan, footer_ref ]
  # footer_catatan is defined in form.fields (also appears in body sections)
  # footer_ref   is defined only above — never shown in the body
```

Zone-local fields still need to be referenced in the zone's `grid` or `columns` to be rendered.
Input fields work normally (react-hook-form registers them via the zone render).

---

### Zone Layout Modes

A zone (`header` or `footer`) supports two layout modes, which can be **mixed freely** in any order.

#### `grid` — Row-aligned

Each inner list is one table row. Fields in the same list share that row as equal-width cells.
A row with a single field spans the full zone width.

Both `grid` and `columns` are supported with different layouts:

**COLUMNS mode** - Each array is a vertical column:
```yaml
header:
  grid:
    - ["company_name", "invoice_no"]   # Row 1: two equal columns
    - ["company_address"]              # Row 2: full-width (spans all columns)
```

#### `columns` — Column stacks

Each inner list is one vertical column; all columns sit side by side in a single row.
Use this when each column holds multiple stacked fields (e.g. logo left, address block right).
`column_widths` sets per-column CSS widths (`auto` shrinks to content; `1fr` fills remaining space).

```yaml
header:
  columns:
    - ["company_logo"]
    - ["company_name", "company_address", "company_npwp"]
  column_widths: ["auto", "1fr"]
```

#### Mixed `grid` + `columns` in one zone

Both keys may appear in the same zone. They render **in the order they appear in the YAML**,
so placing `grid` before `columns` creates a spanning row above the column block, and vice versa.

```yaml
header:
  grid:
    - ["invoice_title"]          # full-width title row rendered first
  columns:
    - ["company_logo"]
    - ["company_name", "company_address"]
  column_widths: ["auto", "1fr"]
  # grid here would render a row BELOW the columns block
```

---

### Multiple Blocks with Numbered Suffixes

YAML does not allow duplicate keys, so use numeric suffixes to add more than one block of the
same type. **Rendering order follows the YAML key order.**

Supported naming patterns (N = any integer: 1, 2, 10, …):

| Key pattern | Meaning |
|---|---|
| `grid`, `grid1`, `grid2`, … | A grid (row-aligned) block |
| `columns`, `columns1`, `column1`, `column2`, … | A columns (stacked) block |
| `column_widths`, `column_widths1`, `column1_widths`, `column1_width`, … | Widths for the matching columns block (same numeric suffix) |

Width keys are automatically paired with their corresponding columns block by matching suffix:
`column1_widths` → applies to `column1`; `column_widths2` → applies to `columns2`.

```yaml
header:
  grid1:
    - ["doc_type_title"]                       # full-width title
  column1:
    - ["company_logo"]
    - ["company_name", "company_address"]
  column1_widths: ["auto", "1fr"]
  grid2:
    - ["billing_divider"]                      # full-width row between blocks
  column2:
    - ["bill_to_label", "bill_to_value"]
    - ["ship_to_label", "ship_to_value"]
  column2_widths: ["1fr", "1fr"]
```

---

### Zone Field Attributes

Fields referenced in a zone are defined in `form.fields` and support these display attributes:

| Attribute | Values | Effect in zone |
|---|---|---|
| `show_label` | `true` / `false` | When `false`, hides the label caption. If the field also has no value, the label text itself becomes the displayed value (e.g. a static "INVOICE" heading). |
| `display` | `block` (default) / `inline` | `block`: label above, value below. `inline`: label and value on the same line as `Label: value`. Consecutive `inline` fields in a column are grouped into an aligned label–value table. |
| `value_align` | `left` / `center` / `right` | Alignment of the value within its cell. Default `right` for `inline`, unset for `block`. |
| `align` | `left` / `center` / `right` | Alignment of the whole field cell. |
| `text_style` | list: `bold`, `italic`, `underline` | Visual styling applied to the value text. |
| `height` | CSS value e.g. `"60px"` | Maximum height for `image` fields. |

#### `label` field type — static display text

Use `type: label` for headings, notes, or instructions inside form body sections.
It **never renders an input widget** — only shows plain text. `label` is optional;
if omitted, `default_value` becomes the displayed text. `show_label` is always `false`.

```yaml
- name: "billing_heading"
  type: "label"
  default_value: "Billing Information"
  text_style: ["bold"]

- name: "vat_note"
  type: "label"
  default_value: "All amounts are in IDR inclusive of VAT."
  text_style: ["italic"]
  align: "right"
```

#### `image` field type — embedding a logo or asset

Use `type: image` with `source: company_logo` to embed the company logo uploaded in System Settings.
The field never appears as a user-input control; it is display-only.

```yaml
- name: "company_logo"
  type: "image"
  label: ""
  source: "company_logo"   # resolved from company settings — no form data needed
  show_label: false
  height: "60px"
```

#### `display: inline` example — compact address block

```yaml
- name: "company_name"
  type: "text"
  label: "Company"
  show_label: false          # show only the value, no "Company:" prefix
  text_style: ["bold"]

- name: "company_address"
  type: "text"
  label: "Address"
  display: "inline"
  value_align: "left"

- name: "company_npwp"
  type: "text"
  label: "NPWP"
  display: "inline"
  value_align: "left"
```

---

### Complete Invoice Header Example

```yaml
form:
  header:
    columns:
      - ["company_logo"]
      - ["company_name", "company_address", "company_npwp"]
    column_widths: ["auto", "1fr"]

  footer:
    grid:
      - ["footer_note", "page_number"]  # Row: two fields side-by-side
```

### Auto-sizing Columns

For columns that should size based on content (e.g., image columns that shouldn't waste space):

**Option 1: Global autosize**
```yaml
form:
  header:
    columns:
      - ["company_logo"]
      - ["company_name", "company_address"]
    autosize: true  # All columns auto-size based on content
```

**Option 2: Per-column control (most flexible)**
```yaml
form:
  header:
    columns:
      - ["company_logo"]
      - ["company_name", "company_address", "npwp"]
    column_widths: ["auto", "1fr"]  # First column auto-sizes, second takes remaining space
```

**CSS Grid Sizing Keywords:**
- `"auto"` - Size based on content, can grow/shrink naturally
- `"min-content"` - Shrink to minimum size needed for content
- `"max-content"` - Expand to maximum size content wants
- `"fit-content"` - Fit content size with max constraint
- Numeric (e.g., `2`) - Fractional units (2fr = twice the width of 1fr)

**Example: Invoice header with logo and company info**
```yaml
form:
  header:
    columns:
      - ["company_logo"]
      - ["company_name", "company_address", "company_npwp"]
    column_widths: ["auto", "1fr"]  # Logo takes only what it needs, text fills remaining
      - ["footer_catatan", "footer_ref"]

  fields:
    # ── Header: left column ───────────────────────────────────────────────
    - name: "company_logo"
      type: "image"
      source: "company_logo"
      show_label: false
      height: "60px"

    # ── Header: right column (stacked inline fields) ──────────────────────
    - name: "company_name"
      type: "text"
      label: "PT Example Indonesia"
      show_label: false
      text_style: ["bold"]
      readonly: true
      default_value: "PT Example Indonesia"

    - name: "company_address"
      type: "text"
      label: "Address"
      display: "inline"
      value_align: "left"
      show_label: false
      readonly: true

    - name: "company_npwp"
      type: "text"
      label: "NPWP"
      display: "inline"
      value_align: "left"
      readonly: true

    # ── Footer fields ─────────────────────────────────────────────────────
    - name: "footer_catatan"
      type: "text"
      label: "Catatan"
      show_label: false
      default_value: "Dokumen ini dicetak secara otomatis"

    - name: "footer_ref"
      type: "text"
      label: "Ref"
      show_label: false
      align: "right"
      default_value: "Form Ver 1.0"
```

---

### How Dynamic Values Reach the Header/Footer

Fields in the header zone are regular form fields. Their values come from:

1. **`default_value`** on the field definition — for static text like company name or form version.
2. **Automatic step with `field_mapping`** — an early workflow step (type: `automatic`) reads the
   webhook payload and maps values into form fields using JSONPath:
   ```yaml
   fetch_invoice_data:
     type: "automatic"
     field_mapping:
       company_name: "$.company.name"
       company_address: "$.company.address"
       invoice_no: "$.invoice.number"
       invoice_date: "$.invoice.date"
       line_items: "$.invoice.lines"
     on_complete:
       continue_to: "finance_approval"
   ```
3. **Pre-filled form data** from triggers (`preset_form_data`).
4. **User input** on the initial submission form.

## Workflow Step Types

**IMPORTANT:** The workflow must be a dictionary/object where step names are keys, NOT a list/array format.

**CORRECT FORMAT:**
```yaml
workflow:
  step_name:
    name: "step_name"
    type: "decision"
    # ...
```

**INCORRECT FORMAT (DO NOT USE):**
```yaml
workflow:
  - name: "step_name"  # ❌ WRONG: List format not allowed
    type: "decision"
```

**Valid Step Types:** `decision`, `parallel_approval`, `conditional_split`, `automatic`, `notification`, `end`
**Invalid/Deprecated Type:** `approval` (use `decision` instead)

### 1. Decision Steps (`decision`)
Standard approval steps requiring human action. They can have multiple outcomes by defining multiple `on_*` keys.

**Mapping to Form Fields:**
Use `signature_field` to link a decision to a specific field in the form (like a signature). When the user clicks an action button (Approve/Reject), the system will ensure this field is filled.

```yaml
manager_signature_step:
  name: "Manager Review"
  type: "decision"
  approver: "${requestor.manager}"
  signature_field: "manager_signature" # Mapped to form field name
  on_approve:
    continue_to: "NextStep"
```

**NOTE:** Use `type: decision` for single-approver decisions, NOT `type: approval`.

#### Simple Binary Outcome (Approve/Reject)
```yaml
manager_approval:
  name: "Manager Approval"
  type: "decision"
  approver: "${requestor.manager}"
  on_approve:
    continue_to: "FinanceReview"
  on_reject:
    end_workflow: true
```

#### With Notification Shortcut
Use `notify_requestor` to send a quick notification to the workflow requester:
```yaml
supervisor_approval:
  name: "Supervisor Approval"
  type: "decision"
  approver: "${requestor.supervisor}"
  on_approve:
    continue_to: "manager_approval"
  on_reject:
    notify_requestor: "Request denied by supervisor"
    end_workflow: true
```

**Action Config Options:**
- `continue_to: "next_step"` - Route to next workflow step
- `end_workflow: true` - Terminate the workflow
- `notify_requestor: "message"` - Send notification to requester (shortcut)

**Note:** For more complex notifications (multiple recipients, custom formatting), use a dedicated `type: notification` step instead.

#### Email Link Authentication (`require_login`)
By default, approval notification emails contain a **public token link** that lets the approver act (approve/reject) without logging in — useful for external or occasional approvers.

Set `require_login: true` on a decision step to send an authenticated link instead (requires the approver to be logged in):

```yaml
sensitive_approval:
  name: "Sensitive Approval"
  type: "decision"
  approver: "${requestor.manager}"
  require_login: true   # email link → /requests/{id} (login required)
  on_approve:
    continue_to: "next_step"
  on_reject:
    end_workflow: true
```

**When to use `require_login: true`:**
- High-security decisions where you want to enforce authentication
- Steps where MFA or SSO policies should apply before acting
- Internal approvals where all approvers always have accounts

**Default behaviour (omit or `false`):** email contains a `/public-approvals/{token}` link — approver clicks → approves/rejects directly, no login required.

#### Step SLA (`sla`)
Set a time-based SLA target for a step using a human-readable duration string. The engine tracks whether the approver acted within the target and includes this in SLA compliance reports.

```yaml
finance_approval:
  name: "Finance Approval"
  type: "decision"
  approver: "${requestor.manager}"
  sla: "4h"          # Must act within 4 hours
  on_approve:
    continue_to: "done"
  on_reject:
    end_workflow: true
```

**Supported duration units:**

| Unit | Meaning   | Example  |
|------|-----------|----------|
| `ms` | milliseconds | `500ms` |
| `s`  | seconds   | `30s`   |
| `m`  | minutes   | `10m`   |
| `h`  | hours     | `4h`    |
| `d`  | days      | `2d`    |
| `w`  | weeks     | `1w`    |
| `M`  | months (~30d) | `1M` |
| `y`  | years (~365d) | `1y` |

Compound values are supported: `"1h30m"`, `"2d4h"`.

**Backwards compatibility:** `sla_hours: 4` (plain number) is still accepted but deprecated. Use `sla: "4h"` going forward.

#### Multi-Outcome Decision
Use any number of `on_<action>` keys to define custom outcomes.
```yaml
triage_step:
  name: "Triage Support Ticket"
  type: "decision"
  approver: "support_lead"
  on_technical:
    text: "Assign to Technical Team"
    continue_to: "TechnicalReview"
  on_billing:
    text: "Assign to Billing"
    continue_to: "BillingReview"
  on_close:
    text: "Close as Duplicate"
    style: "destructive" # Optional: for UI hints
    notify_requestor: "Ticket closed as duplicate"
    end_workflow: true
```

### 2. Parallel Approval (`parallel_approval`)
Multiple approvers working simultaneously. Three completion strategies are supported.

#### Strategy: `all` — Every approver must sign/approve

Each approver can have its own `signature_field` (or inherit the step-level one):

```yaml
board_sign_off:
  name: "board_sign_off"
  type: "parallel_approval"
  approval_strategy: "all"
  signature_field: "shared_sig"   # Step-level fallback for approvers without their own
  approvers:
    - role: "${requestor.manager}"
      approval_type: needs_to_sign
      signature_field: "manager_sig"   # Per-approver override
    - role: "${requestor.department_head}"
      approval_type: needs_to_sign
      signature_field: "dept_head_sig" # Per-approver override
    - role: "cfo"
      approval_type: needs_to_approve  # No signature required for this approver
  on_approve:
    continue_to: "next_step"
  on_reject:
    end_workflow: true
```

#### Strategy: `any_one` — First approver to act wins

All approvers share one step-level `signature_field` (per-approver override still works):

```yaml
quick_approval:
  name: "quick_approval"
  type: "parallel_approval"
  approval_strategy: "any_one"
  signature_field: "approver_sig"   # Whichever approver acts signs this field
  approvers:
    - role: "${requestor.manager}"
    - role: "${requestor.department_head}"
  on_approve:
    continue_to: "next_step"
  on_reject:
    end_workflow: true
```

#### Strategy: `majority` — More than half (or `required_count`) must approve

Use `required_count` to set an explicit quorum instead of the auto-calculated majority:

```yaml
committee_vote:
  name: "committee_vote"
  type: "parallel_approval"
  approval_strategy: "majority"
  required_count: 3     # Optional: require exactly 3 of 5; omit for auto (floor(n/2)+1)
  signature_field: "committee_sig"  # Step-level shared signature field
  approvers:
    - role: "committee_member_1"
      approval_type: needs_to_sign
    - role: "committee_member_2"
      approval_type: needs_to_sign
    - role: "committee_member_3"
      approval_type: needs_to_sign
    - role: "committee_member_4"
      approval_type: needs_to_sign
    - role: "committee_member_5"
      approval_type: needs_to_sign
  on_approve:
    continue_to: "next_step"
  on_reject:
    end_workflow: true
```

**`signature_field` Resolution Rules:**

| Strategy | Per-approver `signature_field` | Step-level `signature_field` |
|----------|-------------------------------|------------------------------|
| `all` | Used when set on the approver entry | Falls back to step-level for approvers without one |
| `any_one` | Used when set on the approver entry | Falls back to step-level (shared; whichever acts first) |
| `majority` | Used when set on the approver entry | Falls back to step-level for approvers without one |

**Approver entry fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `role` | ✅ | Role name or dynamic reference (`${requestor.manager}`) |
| `approval_type` | ❌ | One of the approval types (default: `needs_to_approve`) |
| `signature_field` | ❌ | Per-approver signature form field name; overrides step-level `signature_field` |

### 3. Conditional Split (`conditional_split`)
Dynamic routing based on form data:

```yaml
routing_step:
  name: "routing_step"
  type: "conditional_split"
  description: "Dynamic Routing"
  choices:
    - conditions: "amount > 10000 and urgency == 'critical'"
      continue_to: "ceo_approval"
    - conditions: "department == 'engineering'"
      continue_to: "tech_approval"
    - conditions: "amount > 5000"
      continue_to: "manager_approval"
  default:
    continue_to: "auto_approve"
```

### 4. Automatic Steps (`automatic`)
**For data fetching and asset updates.** System processing without human interaction.

#### 4a. Data Source Fetch (Read)
Fetch data from a configured data source and optionally compare against a baseline asset:

```yaml
fetch_iam_data:
  type: "automatic"
  name: "Fetch Current IAM Users"
  data_processor:
    source_name: "GCP IAM Data Source" # Data source name used for lookup
    save_to: "iam_users_json"           # Save fetched data to this form field
    compare_to_asset: "gcp-iam-baseline"  # Optional: compare with asset baseline
    save_diff_to: "deepdiff_gcs"        # Optional: save diff result to this field
    ignore_keys: []                     # Optional: keys to ignore in comparison
  on_complete:
    continue_to: "check_changes"
```

**Data Source Properties:**
- `source_id`: Stable unique ID of the data source (preferred — company-scoped, survives renames)
- `source_name`: Human-readable name — portable across companies; fallback when `source_id` is absent
- `save_to`: Variable name to store fetched data. Required unless `field_mapping` is used at step level
- `compare_to_asset`: Asset name to compare fetched data against (uses deepdiff)
- `save_diff_to`: Variable to store the diff result string (`"None"` if no changes, or descriptive summary)
- `ignore_keys`: Top-level keys to exclude from comparison

**Params — source options:**
- `from_field: field.<name>` — reads a value from a workflow form field or variable
- `from_asset: <asset-name>` — reads from an asset's `properties` in the asset register
  - `property: $.last_transaction_id` — JSONPath into `properties` (or plain key name without `$`)
  - Omit `property` to pass the entire `properties` dict
- `value: <literal>` — static value hardcoded in the YAML

```yaml
fetch_new_records:
  type: automatic
  data_processor:
    source_name: "Transactions API"
    save_to: new_transactions
    params:
      - name: since_id
        from_asset: driftwatch-transactions-checkpoint
        property: $.last_transaction_id
      - name: limit
        value: 500
```

**Diff Result Format:**
- If no changes: `"None"` (string, for use in conditional_split)
- If changes detected: Descriptive string with markdown emphasis for highlighting in approval UI:

```
⚠️ **3 change(s) detected**

**➕ ADDITIONS:**
  • Detected addition at **bindings → item #1 → members → item #3**:
    Added: **"user:newuser@example.com"**

**➖ REMOVALS:**
  • Detected removal at **bindings → item #5 → members → item #2**:
    Removed: **"user:olduser@example.com"**

**✏️ MODIFICATIONS:**
  • Detected change at **bindings → item #2 → role**:
    From: "roles/viewer"
    To: **"roles/editor"**
```

**Text Emphasis in Forms:**
- Text/textarea fields support markdown-style `**bold**` markers
- Bold text renders with red color and yellow highlight in the approval UI
- Fields containing emphasized text get an amber background to draw attention
- Use this for important values that approvers need to review carefully

#### 4b. Asset Update / Load (`asset:` / `resource:`)
Six modes are supported, selected by the keys present. The keys `asset:` / `resource:` and `asset_name:` / `resource_name:` are interchangeable. `asset_name` supports `{{field}}` interpolation from `request_data`.

**Mode summary:**

| Keys used | Direction | Scope |
|-----------|-----------|-------|
| `data_to` | asset → variable | Whole `properties` blob |
| `data_from` | variable → asset | Full replace of `properties` |
| `field` + `data_to` | asset → variable | Single field value |
| `field` + `data_from` | variable → asset | Single field patch (other fields untouched) |
| `fields_to` | asset → variables | Multiple specific fields → separate variables |
| `merge_from` | variable dict → asset | Partial merge, other fields preserved |
| `fields_from` | variables → asset | Multiple variables → separate named fields |

---

**Full read** — loads all `properties` into a workflow variable:

```yaml
load_baseline:
  type: "automatic"
  asset:
    asset_name: "gcp-iam-baseline"
    data_to: "iam_users_json"         # asset.properties → request_data.iam_users_json
  on_complete:
    continue_to: "compare_step"
```

**Full write** — replaces all `properties` from a workflow variable (upsert):

```yaml
update_asset:
  type: "automatic"
  asset:
    asset_name: "gcp-iam-baseline"
    data_from: "iam_users_json"       # request_data.iam_users_json → asset.properties
  on_complete:
    continue_to: "approved_end"
```

**Single-field read** — loads one `properties` key into a variable:

```yaml
read_status:
  type: automatic
  asset:
    asset_name: "ccp-{{product_id}}"
    field: current_status             # reads properties.current_status
    data_to: current_status           # optional; defaults to field name if omitted
  on_complete:
    continue_to: route_on_status
```

**Single-field write** — patches one `properties` key, leaves all others intact:

```yaml
update_status:
  type: automatic
  asset:
    asset_name: "ccp-{{product_id}}"
    field: current_status
    data_from: new_status             # request_data.new_status → properties.current_status only
  on_complete:
    continue_to: notify_team
```

**Multi-field read** — loads several `properties` keys into separate variables:

```yaml
load_fields:
  type: automatic
  asset:
    asset_name: "ccp-{{product_id}}"
    fields_to:
      current_status: status_var      # properties.current_status → request_data.status_var
      last_verified_at: verified      # properties.last_verified_at → request_data.verified
  on_complete:
    continue_to: compare_step
```

**Partial merge write** — merges a dict into `properties`, preserving all other keys:

```yaml
partial_update:
  type: automatic
  asset:
    asset_name: "ccp-{{product_id}}"
    merge_from: update_payload        # request_data.update_payload must be a dict
    # e.g. {"current_status": "in_control", "last_verified_at": "2025-06-18"}
    # Keys not present in update_payload are left unchanged in properties.
  on_complete:
    continue_to: notify_team
```

**Multi-field write** — writes several variables into separate named fields, preserving all other keys:

```yaml
save_supplier_data:
  type: automatic
  asset:
    asset_name: "supplier-{{supplier_id}}"
    fields_from:
      status: supplier_status          # request_data.supplier_status → properties.status
      last_audit_date: audit_date      # request_data.audit_date → properties.last_audit_date
      approved_by: current_user_email  # request_data.current_user_email → properties.approved_by
  on_complete:
    continue_to: notify_team
```

**Asset key reference:**
- `asset_name` / `resource_name`: Asset to operate on — **Required**. Supports `{{template}}` interpolation.
- `data_to`: Variable to receive the read value (whole blob, or single field when `field:` is set)
- `data_from`: Variable supplying the write value (whole replace, or single field patch when `field:` is set)
- `field`: Scopes `data_to` / `data_from` to a single `properties` key (patch mode)
- `fields_to`: Dict of `{field_name: variable_name}` — reads multiple individual fields at once
- `merge_from`: Variable supplying a partial dict — shallow-merged into `properties` (other keys untouched)
- `fields_from`: Dict of `{field_name: variable_name}` — writes each variable into the named field; other keys are preserved

**Test Mode Behavior:**
- `asset` write (`data_from` / `merge_from` / `fields_from` / `field`+`data_from`): Writes to user-scoped sandbox copy; production asset is not modified
- `asset` read (`data_to` / `fields_to` / `field`+`data_to`): Reads the user-scoped test copy if available, otherwise falls back to the production copy

#### 4c. Asset File Update (`asset_file:`)

Upload a file from a `file_upload` form field into a named asset in the registry. The asset stores the current file reference in its `properties`; S3 bucket versioning automatically retains previous versions. Use this after an approval step to persist a document (policy, certificate, evidence) against a named asset.

```yaml
save_policy:
  type: automatic
  name: "Save SOC2 Policy to Registry"
  asset_file:
    asset_name: "vaap-soc2-{{product_id}}"   # resolved from request_data; each product has its own version history
    field_name: policy_document               # which file field in the asset schema to update
    file_from: policy_upload                  # file_upload form field containing the uploaded file
    schema: "SOC2 Policy"                     # optional: assign schema when auto-creating the asset
  on_complete:
    continue_to: notify_team
```

**Properties:**
- `asset_name`: Asset registry name. Supports `{{template}}` interpolation from `request_data`. Each unique resolved name has its own independent S3 version history — uploading for `ccp-prod123` never affects `ccp-prod456`.
- `field_name`: The file field key within the asset's `properties` (and its schema, if one is attached).
- `file_from`: Name of the `file_upload` field in the workflow form. The engine reads the file bytes from the instance attachment path and re-uploads them to the stable asset path.
- `schema`: (Optional) Asset schema name to assign to the asset on first creation. Ignored if the asset already exists.

**How versioning works:**
The asset stores a JSON reference to the current file in `properties[field_name]`:
```json
{
  "s3_key": "companies/1/assets/files/vaap-soc2-prod123/policy_document",
  "original_name": "soc2-policy-2025.pdf",
  "content_type": "application/pdf",
  "size": 12345,
  "s3_version_id": "abc123xyz",
  "uploaded_at": "2025-06-18T07:30:00Z",
  "uploaded_by": "alice@example.com"
}
```
Previous versions are preserved in S3 and listed in the asset's chronology with `previous_s3_version_id` for recovery.

**Download via API:**
- `GET /assets/{uuid}/fields/{field_name}/download` — current version
- `GET /assets/{uuid}/fields/{field_name}/download?version_id={v}` — specific S3 version
- `GET /assets/{uuid}/fields/{field_name}/versions` — full version history

Access is gated by the asset's `view_roles` on every request.

#### 4d. Field Mapping (Extract and Transform Data)
Map and transform values from webhook payloads or API responses into form fields using JSONPath extraction and JSONata transformations.

**Three Types of Field Mapping:**

**1. Simple JSONPath Extraction**
Extract values directly from JSON using JSONPath:
```yaml
field_mapping:
  customer_name: "$.customer.name"
  invoice_number: "$.invoice.number"
  total_amount: "$.invoice.total"
```

**2. Nested Array Mapping (Line Items)**
Map JSON arrays to line_items fields:
```yaml
field_mapping:
  invoice_lines:
    source: "$.invoice.invoice_line_ids"
    item_fields:
      product_name: "display_name"
      quantity: "quantity"
      price: "price_unit"
```

**3. JSONata Transformation**
Transform data using JSONata expressions (string operations, regex, math, conditionals):

**With source (extract first, then transform):**
```yaml
field_mapping:
  # Remove product ID prefix: "[434322544] Plastic Cup" → "Plastic Cup"
  product_name:
    source: "$.product.name"
    jsonata: "$replace(value, /\\[\\d+\\]\\s*/, '')"

  # Format phone: "5551234567" → "(555) 123-4567"
  phone_formatted:
    source: "$.customer.phone"
    jsonata: "$replace(value, /(\\d{3})(\\d{3})(\\d{4})/, '($1) $2-$3')"

  # Extract first 3 chars, uppercase: "john smith" → "JOH"
  customer_code:
    source: "$.customer.name"
    jsonata: "$uppercase($substring(value, 0, 3))"
```

**Without source (use entire payload):**
```yaml
field_mapping:
  # Concatenate multiple fields
  full_address:
    jsonata: "street & ', ' & city & ' ' & postal_code"

  # Combine first and last name
  full_name:
    jsonata: "firstName & ' ' & lastName"

  # Calculate discount percentage
  discount_pct:
    jsonata: "$round((regular_price - sale_price) / regular_price * 100) & '%'"
```

**JSONata Common Patterns:**
```yaml
# String operations
jsonata: "$uppercase(value)"                          # Uppercase
jsonata: "$lowercase(value)"                          # Lowercase
jsonata: "$trim(value)"                               # Trim whitespace
jsonata: "$substring(value, 0, 10)"                   # First 10 chars
jsonata: "$substringAfter(value, '@')"                # Extract domain from email

# Regex operations
jsonata: "$replace(value, /\\[\\d+\\]\\s*/, '')"     # Remove ID prefix
jsonata: "$replace(value, /[^0-9]/, '')"              # Extract numbers only
jsonata: "$replace(value, /<[^>]*>/, '')"             # Remove HTML tags

# Concatenation
jsonata: "firstName & ' ' & lastName"                 # Join with space
jsonata: "street & ', ' & city & ' ' & zip"           # Multi-field concat

# Conditional logic
jsonata: "qty > 100 ? 'In Stock' : 'Low Stock'"       # Ternary operator
jsonata: "value ? value : 'N/A'"                      # Null check

# Math operations
jsonata: "$round((original - sale) / original * 100)" # Calculate percentage
```

**4. `vars` — Cross-step Reference in JSONata**

All JSONata expressions (top-level and inside `item_fields`) have access to a special `vars` key
that points to the full `request_data` of the current workflow instance — i.e. every value saved
by every previous step. Use `vars` to reference data fetched in an earlier step when the current
step's own payload does not contain it.

```yaml
# vars.some_step_save_key  →  the full API response saved by that step
# vars.some_step_save_key.data  →  the `data` array inside that response

# Look up a tax name from a lookup table saved in a previous step:
tax:
  source: "tax_id[0]"      # value = raw integer ID (e.g. 123) from current item
  jsonata: |
    vars.tax_lookup.data[id = $number(value)].name

# Join all tax names for a multi-tax line:
all_taxes:
  source: "tax_id"          # value = array [123, 456]
  jsonata: |
    $join($map(value, function($id) {
      vars.tax_lookup.data[id = $number($id)].name
    }), ", ")
```

This enables the **three-pass pattern** for ERP / relational line-item lookups (see example below).

**Inline Join — Resolving Relational ID Fields (Single Step)**

ERP systems like Odoo store relational fields as integer IDs or arrays (e.g. `tax_id: [123, 456]`).
The `join` key on `data_processor` resolves these automatically in a single step — the engine
batch-fetches the related records, builds an in-memory lookup, and writes the resolved name
directly onto each row before `field_mapping` runs. No extra steps, no JSONata, no `vars`.

**Single-field pick** — extract one field from the join record, write to one output field:

```yaml
fetch_invoice_lines:
  type: automatic
  data_processor:
    source_name: src_invoice_lines
    save_to: invoice_lines
    join:
      - field: tax_ids         # field on each row (scalar int or array of ints)
        source_name: src_tax_api # connector source to batch-fetch related records from
        on: id                 # key field in join records to match against (default: "id")
        pick: name             # value field to extract from each matched record (default: "name")
        as: tax_name           # output field written onto each enriched row
        # param: ids           # optional — param name sent to join source (default: "ids")
        # separator: ", "      # optional — separator when field is an array (default: ", ")
        # as_array: false      # optional — true outputs a list instead of joined string
  field_mapping:
    invoice_lines:
      source: "$.invoice_lines.data"
      item_fields:
        qty: quantity
        unit_price: price_unit
        tax: tax_name          # already resolved — no JSONata or vars needed
  on_complete:
    continue_to: manager_approval
```

**Multi-field pick** — extract several fields from the same join record in one API call:

```yaml
fetch_invoice_lines:
  type: automatic
  data_processor:
    source_name: src_invoice_lines
    save_to: invoice_lines
    join:
      - field: tax_ids
        source_name: src_tax_api
        on: id
        pick:                  # dict: output_field_name: source_field_name
          tax_name: name       # row.tax_name ← matched_record.name
          tax_rate: amount     # row.tax_rate ← matched_record.amount
          tax_account: code    # row.tax_account ← matched_record.code
        # `as` is not used when pick is a dict
  field_mapping:
    invoice_lines:
      source: "$.invoice_lines.data"
      item_fields:
        qty: quantity
        unit_price: price_unit
        tax: tax_name          # e.g. "Included PPN"
        rate: tax_rate         # e.g. "11%"
        account: tax_account   # e.g. "4310"
  on_complete:
    continue_to: manager_approval
```

**`join` field reference:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `field` | ✅ Yes | — | Field on each fetched row that holds the FK ID(s) |
| `source_id` | ✅ One of | — | Stable unique ID of the connector source for batch-fetch (e.g. `src_xxx`, company-scoped) |
| `source_name` | ✅ One of | — | Human-readable connector source name — portable across companies; fallback when `source_id` is absent |
| `as` | ✅ when `pick` is a string | — | Output field written onto each enriched row |
| `on` | ❌ No | `"id"` | Key field in the join source records to match against |
| `pick` | ❌ No | `"name"` | String (single field) or dict `{output: source}` (multiple fields) |
| `param` | ❌ No | `"ids"` | Parameter name sent to the join source for the batch IDs |
| `separator` | ❌ No | `", "` | Separator when `field` is an array and output is a string |
| `as_array` | ❌ No | `false` | `true` → output is a list of strings instead of a joined string |

**Key behaviours:**
- Multiple join entries can be listed under `join:` to resolve several FK fields in one step.
  Each entry makes one batch API call to its `source_name`.
- `pick` as a dict extracts multiple fields from the **same** API call — no extra network requests.
- All joins run before `field_mapping`, so resolved names are available immediately.
- Array FKs (`tax_ids: [49, 50]`) produce `"Included PPN, GST 10%"` (string) or
  `["Included PPN", "GST 10%"]` (with `as_array: true`).

---

**Three-Pass Pattern (ERP Relational Field Lookup)**

The three-pass pattern is the older approach for the same problem. Prefer the single-step
`join` key above. The three-pass pattern remains documented for reference and backward compatibility.

ERP systems like Odoo store relational fields as raw integer ID arrays (e.g. `tax_id: [123, 456]`).
Making one API call per row causes N+1 problems. The three-pass pattern solves this with only
existing YAML keys:

- **Pass 1** — fetch line items; use `field_mapping` JSONata to collect all unique IDs into a flat list
- **Pass 2** — batch-fetch display names for those IDs using `data_processor` with `from_field` params
- **Pass 3** — standalone `field_mapping` (no `data_processor`) reads saved data + resolves IDs via `vars`

```yaml
# Pass 1: fetch line items, extract unique tax IDs into a flat list
fetch_lines:
  type: automatic
  data_processor:
    source_name: src_invoice_lines
    save_to: lines_raw
  field_mapping:
    tax_ids:
      jsonata: "$distinct(data.tax_id)"   # data = API response; JSONata flattens nested arrays
  on_complete:
    continue_to: fetch_tax_names

# Pass 2: batch-fetch tax descriptions using the collected IDs
fetch_tax_names:
  type: automatic
  data_processor:
    source_name: src_tax_api
    params:
      - name: ids
        from_field: field.tax_ids
    save_to: tax_lookup
  on_complete:
    continue_to: map_lines

# Pass 3: standalone field_mapping (no data_processor) — reads from request_data via vars
map_lines:
  type: automatic
  field_mapping:
    invoice_lines:
      source: "$.lines_raw.data"          # JSONPath on instance.request_data
      item_fields:
        qty: quantity
        unit_price: price_unit
        tax:
          source: "tax_id[0]"             # value = first tax ID integer, e.g. 123
          jsonata: |
            vars.tax_lookup.data[id = $number(value)].name
        all_taxes:
          source: "tax_id"                # value = full array [123, 456]
          jsonata: |
            $join($map(value, function($id) {
              vars.tax_lookup.data[id = $number($id)].name
            }), ", ")
  on_complete:
    continue_to: manager_approval
```

After Pass 1: `request_data["lines_raw"]` = full API response; `request_data["tax_ids"]` = `[123, 456]`
After Pass 2: `request_data["tax_lookup"]["data"]` = array of tax records with `id` and `name`
After Pass 3: `invoice_lines[i].tax` = `"VAT 10%"` (resolved from integer `123`)

**Complete Example:**
```yaml
fetch_invoice_data:
  name: "Populate and Transform Invoice Fields"
  type: "automatic"
  field_mapping:
    # Simple extraction
    invoice_no: "$.invoice.name"
    invoice_date: "$.invoice.invoice_date"

    # JSONata transformations
    product_name:
      source: "$.product.name"
      jsonata: "$replace(value, /\\[\\d+\\]\\s*/, '')"

    customer_code:
      source: "$.customer.name"
      jsonata: "$uppercase($substring(value, 0, 3))"

    full_address:
      jsonata: "street & ', ' & city & ' ' & postal_code"

    # Array mapping
    invoice_lines:
      source: "$.invoice.invoice_line_ids"
      item_fields:
        product: "display_name"
        quantity: "quantity"
        price: "price_unit"
  on_complete:
    continue_to: "finance_approval"
```

**`field_mapping` Properties:**
- Keys are form field names (must exist in `form.fields`)
- Values can be:
  - String: JSONPath expression (e.g., `"$.customer.name"`)
  - Dict with `source` + `jsonata`: Extract then transform
  - Dict with `jsonata` only: Transform using entire payload
  - Dict with `source` + `item_fields`: Map array to line_items
- All JSONata expressions receive a `vars` key pointing to the full `request_data` (all data saved by prior steps); use `vars.save_key.field` to reference earlier fetch results
- A step with only `field_mapping` (no `data_processor`) is valid and reads from `request_data` directly — used as Pass 3 in the three-pass lookup pattern
- Missing paths are skipped with warnings logged
- Errors don't block workflow execution (fault-tolerant)
- Can be combined with `data_processor` or `resource` on the same step

**JSONPath root when `data_processor` and `field_mapping` are on the same step:**
When a step has both `data_processor` (with `save_to`) and `field_mapping`, the JSONPath expressions are evaluated against the raw API response object — **not** against `request_data`.
- For a single-object API response (e.g. WeatherAPI returns `{"location":…, "current":…}`), write paths starting from that object: `$.location.name`, `$.current.temp_c`
- For a multi-record API response, the source is the array: write `$[0].field` or use JSONata
- A standalone `field_mapping` step (no `data_processor`) still reads from `request_data` as before

**Error Handling:**
- JSONPath not found: Field skipped, warning logged
- JSONata expression fails: Error logged, field skipped
- Empty arrays: Field set to `[]`
- Workflow continues regardless of mapping errors

**Important:** `type: automatic` should ONLY be used for data operations. For sending notifications, use `type: notification` instead.

### 5. Notification Steps (`notification`)
**For sending notifications to users.** Supports intelligent routing based on user preferences:

```yaml
notify_completion:
  name: "Notify Completion"
  type: "notification"
  recipients:
    - email: "${instance.requester_email}"  # Variable reference
    - role: "finance_team"                   # Role-based
    - user_id: 123                           # Specific user ID
  notification:
    message:
      subject: "✅ Request Approved - ${form.request_title}"
      body: |
        Your request has been successfully approved.

        **Details:**
        - Request: ${form.request_title}
        - Amount: ${form.amount}
        - Approved by: ${approver.name}

        The request is now being processed.
  on_complete:
    continue_to: "complete"
```

**Notification Routing Logic:**
1. System looks up recipients by email/role/user_id
2. For each recipient, checks if they're a logged-in user
3. If user has configured notification preferences (Slack, Teams, etc.), sends via that channel
4. Otherwise, defaults to email
5. Supports multi-channel delivery (email + Slack, etc.)

**Recipient Types:**
- `email: "user@example.com"` or `email: "${instance.requester_email}"` - Direct email
- `role: "finance_team"` - All users with this role
- `user_id: 123` - Specific user by ID

### 6. Spawn Step (`spawn`)
**For fan-out sub-workflow execution.** Creates one child workflow instance per row in a `line_items` field, then fans back in when the required number of children complete.

```yaml
process_vendor_invoices:
  type: "spawn"
  name: "Process Each Vendor Invoice"
  workflow: "vendor-invoice-approval"  # Child workflow name to spawn
  items: "line_items"                  # Form field containing the array of rows
  wait_for: "all"                      # Fan-in strategy: "all" | "any" | "none"
  pass:                                # Fields from parent to copy into child request_data
    - "department"
    - "requested_by"
  map:                                 # Per-row field mappings (row fields → child field names)
    vendor_name: "vendor"
    invoice_amount: "amount"
    invoice_date: "date"
  on_complete:
    continue_to: "final_review"
  on_failure:
    continue_to: "escalation"
```

**Fan-in Strategies (`wait_for`):**
- `all` *(default)* — parent advances only when **every** child instance has completed
- `any` — parent advances as soon as **at least one** child completes
- `none` — fire-and-forget; parent advances immediately after spawning all children

**Field Mapping (`pass` and `map`):**
- `pass`: List of top-level field names to copy verbatim from the parent into each child's `request_data`
- `map`: Dict of `row_field: child_field` — values come from each individual line item row

**Test Mode Behavior:**
In test mode (instance metadata `is_test_mode: true`), the spawn step logs what it *would* spawn without creating real child instances. The coordinator step is immediately approved and `on_complete` routing is followed.

**Key Properties:**
- `workflow`: Name of the child workflow to spawn — **Required**
- `items`: Name of the form field (array of objects) to iterate — **Required**
- `wait_for`: Fan-in strategy (`all` | `any` | `none`) — default `all`
- `pass`: List of parent field names to copy into each child
- `map`: Dict mapping row fields to child request_data field names
- `on_complete`: Routing when fan-in threshold is met
- `on_failure`: Routing when any child is rejected/failed (for `all` strategy)

### 7. End Step (`end`)
Explicit workflow termination nodes. **RECOMMENDED** for complex workflows with multiple outcomes:

```yaml
complete:
  name: "Successfully Completed"
  type: "end"
  # Optional: Add metadata for outcome tracking
  metadata:
    outcome: "approved"
```

**With Final Notification:**
End nodes can optionally send a notification to the requester before terminating:

```yaml
approved_complete:
  name: "Approved - Process Complete"
  type: "end"
  notify_requestor: "Your request has been fully approved and processed"
  metadata:
    outcome: "approved"
```

**Benefits of Explicit End Nodes:**
- Clear workflow termination points for visualization
- Better auditability and analytics
- Can represent different outcomes (success, rejection, cancellation)
- Enables final actions before termination (like notifications)

**Multiple End Nodes Example:**
```yaml
workflow:
  final_approval:
    type: "decision"
    on_approve:
      continue_to: "approved_complete"  # Route to success end
    on_reject:
      continue_to: "rejected_complete"  # Route to rejection end

  approved_complete:
    name: "Approved - Process Complete"
    type: "end"
    notify_requestor: "Your request has been approved!"
    metadata:
      outcome: "approved"

  rejected_complete:
    name: "Rejected"
    type: "end"
    notify_requestor: "Your request has been rejected. Please contact support for details."
    metadata:
      outcome: "rejected"
```

**End Node Properties:**
- `name` - Display name for the end state
- `type: "end"` - Required
- `notify_requestor` - Optional: Send final notification to requester
- `metadata` - Optional: Track outcome, reason, etc. for analytics

**Note:** You can still use `end_workflow: true` for simple workflows, but explicit `type: end` nodes are preferred for better workflow structure and analytics.

## Approval Types

1. **`needs_to_approve`** (default) - Can approve, reject, or request more info
2. **`needs_to_sign`** - Requires digital signature
3. **`needs_to_recommend`** - Advisory role, cannot block workflow
4. **`needs_to_acknowledge`** - Simple acknowledgment required
5. **`needs_to_call_action`** - Executes system action or manual task
6. **`receives_a_copy`** - Notification only, no action required

## Approver Configuration

### Simple String Format
Use an email address or role name for registered employees:
```yaml
manager_approval:
  type: "decision"
  approver: "manager@company.com"  # Email of registered employee
  approval_type: "needs_to_approve"

finance_review:
  type: "decision"
  approver: "finance_manager"  # Role name
  approval_type: "needs_to_approve"
```

### External/Unregistered Approvers
For external users (vendors, clients, contractors) who don't have accounts, use the object format:
```yaml
vendor_signature:
  type: "decision"
  approver:
    email: "vendor@external.com"
    name: "Jane Smith"
    position: "Vendor Representative"
    employee_type: "external"  # Optional: internal, external, contractor
  approval_type: "needs_to_sign"
```

**Features:**
- Automatically creates employee record if email doesn't exist
- No pre-registration required
- Supports internal, external, and contractor types
- Signature stored against employee record

### Dynamic Approvers from Form Fields
Use template variables to pull approver details from form data:
```yaml
client_acknowledgement:
  type: "decision"
  approver:
    email: "${form.client_email}"
    name: "${form.client_name}"
    position: "${form.client_company}"
    employee_type: "external"
  approval_type: "needs_to_acknowledge"
```

**Use Cases:**
- Client sign-offs on contracts
- Vendor approvals on purchase orders
- Contractor certifications
- Partner acknowledgements
- Third-party validations

### Signature Display Format
When using `approval_type: "needs_to_sign"`, signatures are displayed as:

**Before signing:**
```
Signed by ________________

Jane Smith
Vendor Representative • External
```

**After signing:**
```
Signed by [Signature Image/Text]

Jane Smith
Vendor Representative • External
Signed on: March 8, 2026, 10:30 AM
```

## Conditional Expression Syntax

### Operators
- Comparison: `>`, `<`, `>=`, `<=`, `==`, `!=`
- Logical: `and`, `or`, `not`
- Membership: `in`, `not in`
- String operations: String equality and membership

### Examples
```yaml
# Numeric comparisons
conditions: "amount > 1000"
conditions: "total_amount <= 500"

# String equality
conditions: "department == 'engineering'"
conditions: "urgency != 'low'"

# List membership
conditions: "category in ['equipment', 'software']"
conditions: "'urgent' in tags"

# Complex expressions
conditions: "amount > 100000 and urgency == 'critical'"
conditions: "department == 'legal' and amount > 25000"
conditions: "(urgency == 'high' or priority >= 4) and amount > 10000"
```

## Dynamic Role References

Use `${requestor.property}` to reference user hierarchy:

- `${requestor.manager}` - Direct manager
- `${requestor.supervisor}` - Supervisor
- `${requestor.department_head}` - Department head
- `${requestor.head_of_department}` - Alternative syntax

## Settings Configuration

```yaml
settings:
  # Timeouts for each step
  timeout:
    manager_approval: "72_hours"
    finance_approval: "48_hours"
    ceo_approval: "5_business_days"

  # Escalation rules
  escalation:
    - after_timeout: "notify_next_level"
    - final_escalation: "ceo"

  # Notification preferences
  notifications:
    send_reminders: true
    reminder_intervals: ["24_hours", "2_hours"]

  # Compliance settings
  compliance:
    receipt_required: true
    policy_check: true
```

## Submission Criteria and View Access

### `submission_criteria` — Who Can Submit

Controls which employees can see and submit this workflow. Uses `company_roles` and optional org path filters.

```yaml
submission_criteria:
  company_roles: ["employee", "manager"]   # From the company's role list
  departments: ["Finance", "Accounting"]   # Optional department filter
  org_hierarchy:
    include_paths: ["1.1.*"]               # Include path and all descendants
    exclude_paths: ["1.1.3.*"]             # Exclude specific sub-path
```

### `view_all_roles` — Who Can View All Submissions

Controls which roles can see **every** submission for this workflow in the list view (not just their own). By default, users only see submissions where they are the requestor, an approver, or a manager in the org hierarchy.

When a user's `company_roles` intersect this list, they get a **"My Requests / All Submissions"** toggle in the workflow list view. This is the correct way to give finance, HR, or audit teams reporting visibility without granting global admin access.

```yaml
view_all_roles: ["finance", "hr", "admin"]
```

**When to include `view_all_roles`:**
- The user mentions finance/accounting needing to see all expense submissions
- The user mentions HR needing to view all leave requests or performance reviews
- The user mentions a manager/auditor role needing to export or report on submissions
- The workflow is an expense, purchase order, leave, or any report-style process

**When to omit `view_all_roles`:**
- All participants only need to see their own submissions
- The workflow is highly sensitive (e.g., salary adjustment) and no role should have bulk visibility

**Example — Expense Workflow:**
```yaml
name: "Travel Expense Request"
type: "expense"
submission_criteria:
  company_roles: ["employee"]
view_all_roles: ["finance", "admin"]   # Finance team can export all approved expenses
```

**Example — Leave Request (no bulk access needed):**
```yaml
name: "Leave Request"
type: "leave"
submission_criteria:
  company_roles: ["employee"]
# view_all_roles omitted — managers see subordinates via org hierarchy naturally
```

## Validation Rules for AI Generation

When generating ApprovalML YAML, ensure:

1. **Workflow Format**: Workflow MUST be a dictionary/object with step names as keys, NOT a list/array
   - ✅ Correct: `workflow: { manager_approval: {...}, finance_review: {...} }`
   - ❌ Wrong: `workflow: [{ name: "manager_approval", ... }]`

2. **Form Structure**: Form sections and fields MUST be separated
   - ✅ Correct: `form: { layout: { sections: [...] }, fields: [...] }`
   - ❌ Wrong: `form: [{ section: { fields: [...] } }]`

3. **Step Types**: Use ONLY valid step types: `decision`, `parallel_approval`, `conditional_split`, `automatic`, `notification`, `end`
   - ❌ NEVER use: `approval` (this is deprecated)

4. **Required Fields**: All steps must have `name`, `type`, and appropriate routing

5. **Unique Names**: Step names must be unique within the workflow

6. **Valid Routing**: All `continue_to` references must point to existing steps

7. **Role Validation**: All approver roles should exist in the employee table

8. **Expression Syntax**: Conditional expressions must use proper operators

9. **Termination**: Workflows must have proper end conditions (`end_workflow: true` OR explicit `type: end` nodes)

10. **End Node Best Practice**: For complex workflows with multiple outcomes, use explicit `type: end` nodes instead of `end_workflow: true`

11. **Reserved Keyword**: The step name `initial` is reserved by the system for revision routing. Do NOT create a step named "initial".

12. **view_all_roles**: When generating workflows for expense, purchase, leave, or reporting use cases, consider including `view_all_roles` at the top level to grant the appropriate finance/HR/audit roles bulk visibility over all submissions. Values must be strings matching `company_roles` in the company. Example: `view_all_roles: ["finance", "admin"]`.

## Workflow Revision Pattern

### Automatic "initial" Step

Every workflow automatically creates an `initial` step when submitted. This step:
- Represents the initial submission by the requestor
- Is assigned to the requestor (approver_id = requestor_id)
- Is auto-approved on creation (step_sequence = 0)
- Can be referenced as a routing target for revisions

### Sending Back for Revision

Any workflow step can route back to `initial` to request revisions from the requestor:

```yaml
manager_approval:
  type: "decision"
  approver: "${requestor.manager}"
  on_approve:
    continue_to: "finance_review"
  on_reject:
    continue_to: "initial"  # ✨ Send back for revision
  on_request_changes:
    text: "Request Changes"
    continue_to: "initial"  # ✨ Custom action for revisions
```

### What Happens When Routing to "initial"

1. **System reopens the initial step** - Status changes from APPROVED → PENDING
2. **Instance status updates** - Workflow status becomes PENDING
3. **Requestor is notified** - "Your submission requires revision"
4. **Requestor can edit** - Form is editable with all original data
5. **Requestor resubmits** - Workflow starts again from the first step
6. **Audit trail preserved** - All revision history is tracked

### Best Practices for Revisions

1. **Use descriptive action names:**
   ```yaml
   on_request_changes:
     text: "Request Changes"
     continue_to: "initial"
   ```

2. **Add a revision notes field:**
   ```yaml
   - name: "revision_notes"
     type: "textarea"
     label: "Revision Notes"
     placeholder: "Explain what changed since last submission..."
   ```

3. **Notify requestor with context:**
   ```yaml
   on_reject:
     notify_requestor: "Please revise the budget justification and resubmit"
     continue_to: "initial"
   ```

4. **Multiple approval levels can send back:**
   ```yaml
   workflow:
     manager_approval:
       on_reject:
         continue_to: "initial"

     finance_approval:
       on_reject:
         continue_to: "initial"

     executive_approval:
       on_send_back:
         continue_to: "initial"
   ```

### Complete Revision Example

```yaml
workflow:
  manager_review:
    type: "decision"
    approver: "${requestor.manager}"
    on_approve:
      continue_to: "finance_review"
    on_reject:
      continue_to: "rejected_end"
    on_request_changes:
      text: "Request Changes"
      style: "warning"
      continue_to: "initial"  # Send back for revision

  finance_review:
    type: "decision"
    approver: "finance_manager"
    on_approve:
      continue_to: "approved_end"
    on_send_back:
      text: "Send Back"
      continue_to: "initial"  # Finance can also send back

  approved_end:
    type: "end"
    notify_requestor: "Request approved!"

  rejected_end:
    type: "end"
    notify_requestor: "Request rejected"
```

## Common Patterns

### Amount-Based Routing with Explicit End Nodes
```yaml
amount_check:
  type: "conditional_split"
  choices:
    - conditions: "amount > 10000"
      continue_to: "executive_approval"
    - conditions: "amount > 1000"
      continue_to: "manager_approval"
  default:
    continue_to: "complete"  # Auto-approve for small amounts

executive_approval:
  type: "decision"
  approver: "ceo"
  on_approve:
    continue_to: "complete"
  on_reject:
    continue_to: "rejected"

manager_approval:
  type: "decision"
  approver: "${requestor.manager}"
  on_approve:
    continue_to: "complete"
  on_reject:
    continue_to: "rejected"

complete:
  name: "Successfully Completed"
  type: "end"

rejected:
  name: "Rejected"
  type: "end"
```

### Department-Specific Routing
```yaml
department_routing:
  type: "conditional_split"
  choices:
    - conditions: "department == 'engineering'"
      continue_to: "cto_approval"
    - conditions: "department in ['finance', 'accounting']"
      continue_to: "cfo_approval"
  default:
    continue_to: "department_head_approval"
```

### Multi-Condition Logic
```yaml
complex_routing:
  type: "conditional_split"
  choices:
    - conditions: "amount > 50000 and ('budget' in tags or category == 'consulting')"
      continue_to: "cfo_approval"
    - conditions: "urgency == 'critical' or (urgency == 'high' and priority >= 3)"
      continue_to: "expedited_approval"
```

## Test Data (Optional)

The `test_data` section pre-fills the submission form when a workflow is run in **test mode** inside
the Workflow Designer. It is ignored completely in production.

```yaml
test_data:
  invoice_no: "SL/INV/2026/0425"
  invoice_date: "2026-03-09"
  customer_name: "PT. UNGGUL PLASTIK"
  total_amount: 27940000
  invoice_lines:
    - item_name: "Widget A"
      qty: 100
      unit_price: 50000
      amount: 5000000
```

**Rules:**
- Keys must match field names defined in `form.fields`
- Values can be any YAML scalar (string, number, boolean) or a list of dicts for `line_items` fields
- The section is silently ignored when submitting real workflow requests

## Parameter Mapping (Optional)

`param_mapping` is a simple key-rename map for URL and API auto-submit. When the system that
triggers the workflow uses different parameter names than the form field names, this translates
them transparently — no JSONPath needed.

```yaml
param_mapping:
  emp_id: employee_id        # URL ?emp_id=123  →  form field employee_id
  cost: amount               # URL ?cost=500    →  form field amount
  dept: department_code      # URL ?dept=FIN    →  form field department_code
```

**Rules:**
- Keys are the *incoming* parameter names (from URL query string or flat API payload)
- Values are the target form field names (must exist in `form.fields`)
- Entirely optional — omit it when parameter names already match field names
- Only applies to flat key-value params; for nested JSON payloads use `triggers[].field_mapping`

## Print Settings (Optional)

The `print` section controls how the workflow document is rendered as a PDF.

```yaml
print:
  orientation: portrait         # portrait (default) | landscape
  page_size: A4                 # A4 (default) | A3 | A5 | Letter | Legal | Tabloid
  margin: "8mm"                 # CSS margin for all sides (default: "8mm"). Accepts "10mm", "10mm 6mm", etc.
  suppress_auto_header: true    # true (default) — if form.header exists, skip the auto company+title block
  suppress_section_header: false # false (default) — when true, hides all section title bars in the PDF
  show_history: true            # true (default) — render the Approval History table at the end
```

**Field Descriptions:**

| Field | Default | Description |
|---|---|---|
| `orientation` | `portrait` | Page orientation for PDF output |
| `page_size` | `A4` | Paper size — A4, A3, A5, Letter, Legal, or Tabloid |
| `margin` | `"8mm"` | CSS page margin applied to all four sides. Accepts any CSS length: `"8mm"`, `"10mm"`, `"10mm 6mm"` (vertical horizontal) |
| `suppress_auto_header` | `true` | When `true` and the workflow has a `form.header`, the system title block (company name + workflow title) is omitted to avoid duplication with the custom header |
| `suppress_section_header` | `false` | When `true`, all section title bars (dark heading rows) are hidden in the PDF — useful for clean invoice layouts |
| `show_history` | `true` | When `false`, the Approval History / chronology table is not included in the PDF |

**Print-only fields:**

Individual fields can be marked `print_only: true` to make them appear in the PDF but not in the web form. This is useful for centered document titles or print-specific annotations:

```yaml
fields:
  - name: doc_title
    type: text
    default_value: "PURCHASE ORDER"
    text_style: [bold]
    value_align: center
    print_only: true       # visible in PDF only — hidden in the submission/approval form
```

This syntax reference should enable AI engines to generate valid ApprovalML workflows from natural language descriptions while ensuring proper validation against available employee roles.
"""

# Field type definitions for validation
FIELD_TYPES = {
    "text": {"validation": ["min_length", "max_length", "pattern"]},
    "textarea": {"validation": ["min_length", "max_length", "rows"]},
    "email": {"validation": ["required", "pattern"]},
    "number": {"validation": ["min_value", "max_value", "step"]},
    "currency": {"validation": ["min", "max", "min_value", "max_value"], "optional_props": ["currency"]},
    "date": {"validation": ["min_date", "max_date"]},
    "datetime": {"validation": ["min_date", "max_date"]},
    "dropdown": {
        "validation": ["required"],
        "optional_props": ["options", "data_source", "lookup"],
        "requires_one_of": ["options", "data_source"],
        "description": "Dropdown select field (alias for 'select' - more intuitive naming)"
    },
    "select": {
        "validation": ["required"],
        "optional_props": ["options", "data_source", "lookup"],
        "requires_one_of": ["options", "data_source"]  # Must have either static options or data_source
    },
    "multiselect": {"required_props": ["options"], "validation": ["min_selections", "max_selections"]},
    "checkbox": {"validation": ["required"]},
    "radio": {"required_props": ["options"], "validation": ["required"], "optional_props": ["display_as"]},
    "file_upload": {"validation": ["accept", "multiple", "max_size", "max_files"], "optional_props": ["capture"]},
    "signature": {"validation": ["required"], "optional_props": ["initial", "label"]},
    "json": {
        "validation": ["required"],
        "optional_props": ["display_as", "default_value"],
        "description": "Structured JSON data field. Supports interactive tree view and syntax highlighting.",
        "yaml_example": (
            "- name: payload\n"
            "  type: json\n"
            "  label: API Payload\n"
            "  display_as: tree\n"
            "  default_value: '{\"status\": \"active\"}'"
        )
    },
    "richtext": {
        "validation": ["required"],
        "description": "Rich text editor (WYSIWYG) that supports HTML formatting and embedded images. Images are automatically converted to base64 and embedded in the HTML content. Content is saved to S3/local storage at companies/{company_id}/workflows/{workflow_id}/instances/{instance_id}/richtext/{field_name}.html"
    },
    "line_items": {"required_props": ["item_fields"], "validation": ["min_items", "max_items"]},
    "autocomplete": {
        "required_props": ["options"],  # Changed: now requires options instead of data_source
        "validation": ["required"],
        "optional_props": ["search", "placeholder"],
        "search_props": ["min_length", "debounce_ms", "max_results"],
        "data_source_props": ["source_id", "source_name", "params", "object_path", "value_field", "label_field", "display"],
        "value_type": "dynamic",  # Can be string (ID) or object depending on configuration
        "value_type_rules": {
            # If value_field is NOT set in options.data_source, stores entire object
            # If value_field is set, stores only that field value
            "object": ["no_value_field"],
            "primitive": ["value_field"]
        }
    },
    "autonumber": {
        "validation": [],
        "optional_props": ["prefix", "pad_length", "start_value"],
        "description": (
            "Auto-incrementing sequential number field. The value is generated server-side at submission "
            "time and is read-only for users. Sequence is scoped per workflow + field name. "
            "Use 'prefix' for a text prefix (e.g. 'EXP-'), 'pad_length' for zero-padding (e.g. 5 → '00042'), "
            "and 'start_value' to set the first number in the sequence (defaults to 1)."
        ),
        "yaml_example": (
            "- name: form_no\n"
            "  type: autonumber\n"
            "  label: Form No.\n"
            "  prefix: \"EXP-\"\n"
            "  pad_length: 5\n"
            "  start_value: 1\n"
            "  # Generates: EXP-00001, EXP-00002, ..."
        )
    },
    "label": {
        "validation": [],
        "optional_props": ["default_value", "text_style", "align", "value_align", "print_only"],
        "description": (
            "Display-only static text field. Never renders an input widget — always shows as plain text. "
            "label is optional; if omitted, default_value is used as the display text. "
            "show_label is always false for this type. "
            "Useful for sub-headings, instructions, or notes inside form sections."
        ),
        "yaml_example": (
            "- name: section_note\n"
            "  type: label\n"
            "  default_value: \"All amounts are in IDR inclusive of VAT.\"\n"
            "  text_style: [italic]\n\n"
            "- name: billing_heading\n"
            "  type: label\n"
            "  default_value: \"Billing Information\"\n"
            "  text_style: [bold]"
        )
    },
    "image": {
        "validation": [],
        "optional_props": ["source", "placement", "object_fit", "position", "height", "width", "show_label"],
        "description": (
            "Display-only image field. Resolves from the company Media Gallery by asset name "
            "(source: <name>) or uses the field value as a direct URL. "
            "placement: inline (default) | background | cover. "
            "object_fit: contain (default) | cover | fill | scale-down | none."
        ),
        "yaml_example": (
            "- name: company_logo\n"
            "  type: image\n"
            "  label: \"\"\n"
            "  source: company_logo   # resolved from Media Gallery by name\n"
            "  placement: inline\n"
            "  position: left\n"
            "  height: \"64px\"\n"
            "  show_label: false"
        )
    }
}

# Step type definitions
STEP_TYPES = {
    "decision": {
        "required_props": ["approver"],
        "optional_props": ["approval_type", "signature_field", "require_login", "on_approve", "on_reject", "timeout", "sla", "sla_hours", "view_sections", "edit_sections"]
    },
    "parallel_approval": {
        "required_props": ["approvers", "approval_strategy"],
        "optional_props": ["signature_field", "required_count", "on_approve", "on_reject", "timeout", "sla", "sla_hours", "view_sections", "edit_sections"]
    },
    "conditional_split": {
        "required_props": ["choices"],
        "optional_props": ["default", "view_sections", "edit_sections"]
    },
    "automatic": {
        "required_props": ["on_complete"],
        "optional_props": ["api", "data_processor", "asset", "field_mapping", "on_failure"],
        "requires_one_of": ["api", "data_processor", "asset", "field_mapping"],
        "field_mapping_description": (
            "Extracts and transforms values from webhook payloads or API responses into form fields. "
            "Supports three types: (1) Simple JSONPath extraction: { field: '$.path' }, "
            "(2) JSONata transformation: { field: { source: '$.path', jsonata: '$uppercase(value)' } }, "
            "(3) Array mapping: { field: { source: '$.array', item_fields: {...} } }. "
            "JSONata enables string operations, regex, math, and conditionals. "
            "e.g. { product_name: { source: '$.product.name', jsonata: '$replace(value, /\\\\[\\\\d+\\\\]\\\\s*/, \"\")' } }"
        ),
        "data_processor_props": {
            "required": ["source_name", "save_to"],
            "optional": ["compare_to_asset", "save_diff_to", "ignore_keys", "field_mapping", "output_schema"]
        },
        "asset_props": {
            "required": ["asset_name"],
            "one_of": [["data_from"], ["data_to"], ["merge_from"], ["fields_to"], ["fields_from"]],
            "optional": ["field"]
        }
    },
    "notification": {
        "required_props": ["recipients", "notification", "on_complete"],
        "optional_props": []
    },
    "spawn": {
        "required_props": ["workflow", "items"],
        "optional_props": ["wait_for", "pass", "map", "on_complete", "on_failure"],
        "description": (
            "Fan-out step that creates one child workflow instance per row in a line_items field. "
            "The parent workflow waits for child instances to complete based on 'wait_for' strategy: "
            "'all' (default) — wait for every child; 'any' — advance on first approved child; "
            "'none' — fire-and-forget, parent advances immediately. "
            "Field wiring priority: explicit 'map' > named 'pass' list > auto-match by field name."
        )
    },
    "wait_webhook": {
        "required_props": ["source", "on_complete"],
        "optional_props": ["match", "field_mapping", "timeout", "on_failure"],
        "description": (
            "Pauses workflow execution until an external service POSTs to "
            "/api/v1/triggers/webhook/source/{source_token}. "
            "The source token is generated once per company in System Settings → Integrations. "
            "`source` must match the registered source name (e.g. 'odoo', 'stripe'). "
            "`match` is load-bearing when multiple instances may be waiting — it filters the payload "
            "against instance.request_data using a single field equality check. "
            "`field_mapping` copies JSONPath values from the incoming payload into form fields. "
            "`timeout.sla` sets the SLA duration; `timeout.on_timeout.continue_to` routes the step "
            "when the SLA expires instead of escalating to a manager."
        )
    },
    "end": {
        "required_props": [],
        "optional_props": ["metadata", "notify_requestor"]
    }
}

# Approval types
APPROVAL_TYPES = [
    "needs_to_approve",
    "needs_to_sign",
    "needs_to_recommend",
    "needs_to_acknowledge",
    "needs_to_call_action",
    "receives_a_copy"
]

# Dynamic role references
DYNAMIC_ROLES = [
    "${requestor.manager}",
    "${requestor.supervisor}",
    "${requestor.department_head}",
    "${requestor.head_of_department}"
]

def get_syntax_reference() -> str:
    """
    Get the complete ApprovalML syntax reference for AI generation.

    Returns:
        str: The complete syntax reference text
    """
    return APPROVALML_SYNTAX_REFERENCE

def get_field_types() -> dict:
    """
    Get the supported field types and their properties.

    Returns:
        dict: Field type definitions
    """
    return FIELD_TYPES

def get_step_types() -> dict:
    """
    Get the supported step types and their properties.

    Returns:
        dict: Step type definitions
    """
    return STEP_TYPES

def get_approval_types() -> list:
    """
    Get the supported approval types.

    Returns:
        list: List of approval type strings
    """
    return APPROVAL_TYPES

def get_dynamic_roles() -> list:
    """
    Get the supported dynamic role references.

    Returns:
        list: List of dynamic role reference strings
    """
    return DYNAMIC_ROLES