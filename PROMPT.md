# ApprovalML — AI Prompt Guide

Use this file as a system prompt or knowledge base when generating ApprovalML workflows with any AI assistant (ChatGPT, Claude, Gemini, etc.).

## How to use this file

### ChatGPT / Claude / Gemini (paste method)
1. Copy the entire contents of this file
2. Paste it at the start of your conversation as context
3. Then describe the workflow you want in plain English

**Example prompt after pasting:**
> "Create a travel expense approval workflow for amounts over $500 that requires manager approval, then finance approval. Include fields for destination, travel dates, estimated cost, and purpose."

### ChatGPT Custom GPT
1. Go to ChatGPT → Explore GPTs → Create
2. In the **Instructions** field, paste the system prompt section below
3. Upload this file as a **Knowledge** file
4. Name it something like "ApprovalML Workflow Builder"

### Gemini Gem
1. Go to Gemini → Gems → New Gem
2. Paste the system prompt section in the **Instructions** field
3. Upload this file as context

### Claude Project
1. Create a new Project in Claude.ai
2. Add this file to the **Project Knowledge**
3. The syntax is always available in every conversation in that project

---

## System Prompt (use this in Custom GPT / Gem instructions)

```
You are an ApprovalML workflow expert. You help users create valid YAML workflow
files for the ApprovalML approval workflow system.

When a user describes a workflow:
1. Generate a complete, valid ApprovalML YAML file
2. Include all required form fields based on the use case
3. Use appropriate step types: decision, parallel_approval, conditional_split, notification, end
4. Add realistic conditional routing where appropriate
5. Always validate your output against the syntax rules in your knowledge base

Critical rules:
- workflow: must be a dict with step names as keys, NEVER a list
- Use type: decision, NOT type: approval (deprecated)
- notification steps use notification.message.subject and notification.message.body
- Every workflow must end with a step of type: end
- Dynamic approvers: use ${requestor.manager}, ${requestor.supervisor}, ${requestor.head_of_department}
- Conditions in conditional_split use plain expressions like: amount > 1000, leave_type == 'unpaid'

Always output the complete YAML file, not just a partial snippet.
```

---

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

# Optional submission criteria
submission_criteria:
  company_roles: []  # Array of roles that can submit
  org_hierarchy:
    include_paths: ["1.1.*"]  # Organizational path patterns

# Form definition
form:
  # Optional layout configuration for sectioned forms
  layout:
    sections: []  # Section structure (references field names)
    responsive: {}

  # Optional footer configuration for reference data and metadata
  footer:
    columns: {}
    items: []

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

## Form Field Types

### Basic Field Types
- `text` - Single line text input
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
- `hidden` - Hidden field for storing metadata or computed values
- `line_items` - Dynamic table with repeating rows
- `autocomplete` - Search-as-you-type field with data source integration
- `autonumber` - Auto-incrementing sequential number (e.g. EXP-00042). Read-only; generated at submission. Supports `prefix` and `pad_length`.

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
  #     source_id: "src_xxx"
  #     value_field: "id"
  #     label_field: "name"
  #     display: "{name} - {code}"  # Optional template

  # Currency fields - optional currency code
  currency: "USD"              # Optional: ISO currency code (USD, EUR, JPY, etc.)
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
      source_id: "src_84d12515751c4985"  # Data source unique ID
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
    source_id: "src_employees"
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
    source_id: "src_employees"
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
  - `source_id`: Data source unique ID (required)
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
    sections:
      - id: "section_id"
        title: "Section Title"
        description: "Optional description shown below title"
        initial: true  # If true, this section is shown during initial submission
        grid:
          - ["field1", "field2"]  # Row with 2 fields side by side
          - ["field3"]  # Row with 1 field (full width)
          - ["field4", "field5", "field6"]  # Row with 3 fields

    # Optional responsive breakpoints
    responsive:
      tablet: 2  # Maximum columns per row on tablets
      mobile: 1  # Maximum columns per row on mobile (usually 1)

  fields:
    # Field definitions...
```

### Layout Features

1. **Sections**: Organize fields into logical groups with titles and descriptions
2. **Grid Layout**: Control field positioning using a row-based grid system
3. **Initial Section**: Mark one section with `initial: true` to show it on workflow creation
4. **Responsive**: Automatically adapts to tablet and mobile screens

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
- The `initial: true` section is shown when the requestor creates the workflow
- Sections not marked as `initial` are typically filled in during approval steps

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
Multiple approvers working simultaneously:

```yaml
parallel_step:
  name: "parallel_step"
  type: "parallel_approval"
  description: "Multiple Approvers"
  approvers:
    - role: "purchasing_officer_1"
    - role: "purchasing_officer_2"
    - role: "purchasing_officer_3"
  approval_strategy: "any_one" | "all" | "majority"
  on_approve:
    continue_to: "NextStepName"
  on_reject:
    end_workflow: true
```

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
**For data fetching and resource updates.** System processing without human interaction.

#### 4a. Data Source Fetch (Read)
Fetch data from a configured data source and optionally compare against a baseline resource:

```yaml
fetch_iam_data:
  type: "automatic"
  name: "Fetch Current IAM Users"
  data_source:
    source_id: "src_cff5797288f440d7"  # Data source unique ID (connector is implicit)
    save_to: "iam_users_json"           # Save fetched data to this form field
    compare_to_resource: "gcp-iam-baseline"  # Optional: compare with resource baseline
    save_diff_to: "deepdiff_gcs"        # Optional: save diff result to this field
    ignore_keys: []                     # Optional: keys to ignore in comparison
  on_complete:
    continue_to: "check_changes"
```

**Data Source Properties:**
- `source_id`: Unique ID of the data source (e.g., `src_xxx`) - **Required** (connector is resolved automatically)
- `save_to`: Form field name to store fetched data - **Required**
- `compare_to_resource`: Resource name to compare fetched data against (uses deepdiff)
- `save_diff_to`: Form field to store the diff result string (`"None"` if no changes, or descriptive summary)
- `ignore_keys`: List of top-level keys to exclude from comparison

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

#### 4b. Resource Update (Write)
Update a resource with data from a form field:

```yaml
update_resource:
  type: "automatic"
  name: "Update IAM Baseline Resource"
  resource:
    data_from: "iam_users_json"      # Get data from this form field
    resource_name: "gcp-iam-baseline" # Update this resource
  on_complete:
    continue_to: "approved_end"
```

**Resource Properties:**
- `data_from`: Form field containing the data to save - **Required**
- `resource_name`: Name of the resource to update - **Required**

**Test Mode Behavior:**
- `data_source` (read): Executes normally - data is fetched and compared
- `resource` (write): Logs the action in history but does NOT modify the resource

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

### 6. End Step (`end`)
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

This syntax reference should enable AI engines to generate valid ApprovalML workflows from natural language descriptions while ensuring proper validation against available employee roles.