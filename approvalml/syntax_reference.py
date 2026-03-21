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

# Optional submission criteria
submission_criteria:
  company_roles: []  # Array of roles that can submit
  org_hierarchy:
    include_paths: ["1.1.*"]  # Organizational path patterns

# Form definition
form:
  # Optional page-repeating header zone (field names referenced from fields[])
  # Supports grid (rows), columns (column stacks), or both mixed — see full reference below
  header:
    grid: []          # e.g. [["company_name", "invoice_no"], ["company_address"]]
    # OR columns mode:
    # columns: []     # e.g. [["company_logo"], ["company_name", "company_address"]]
    # column_widths: []  # e.g. ["auto", "1fr"]

  # Optional layout configuration for sectioned form body
  layout:
    sections: []  # Section structure (references field names)
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

### Additional Field Display Properties
```yaml
- name: "field_name"
  type: "text"
  label: "Display Label"
  show_label: false   # If false, hides the label caption (useful in header/footer zones)
  align: "right"      # Column text alignment: "left" | "center" | "right"
  width: "120px"      # Column width (CSS value: "120px", "15%", "auto")
```
`align` and `width` are most useful on `item_fields` inside `line_items` to control column layout.
`show_label: false` suppresses the label so only the field value appears — common in invoice headers.

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

## Form Header and Field-Zone Footer (Invoice / Document Style)

For document-style forms (invoices, purchase orders, delivery notes) that must match a printed
layout, use `form.header` and `form.footer` zones that reference fields by name.

These zones **repeat on every printed page** (unlike the body layout which appears once).
Place signature fields and totals in the body layout — not in header/footer zones.

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

#### 4c. Field Mapping (Populate Form Fields from Webhook Payload)
Map values from a webhook payload (e.g., from Odoo or an ERP system) directly into form fields
using JSONPath expressions. This is typically the first step after a webhook trigger.

```yaml
fetch_invoice_data:
  name: "Populate Invoice Fields"
  type: "automatic"
  field_mapping:
    company_name: "$.company.name"
    company_address: "$.company.street"
    invoice_no: "$.invoice.name"
    invoice_date: "$.invoice.invoice_date"
    due_date: "$.invoice.invoice_date_due"
    customer_name: "$.invoice.partner_id.name"
    subtotal: "$.invoice.amount_untaxed"
    tax_amount: "$.invoice.amount_tax"
    total_amount: "$.invoice.amount_total"
  on_complete:
    continue_to: "finance_approval"
```

**`field_mapping` Properties:**
- Keys are form field names (must exist in `form.fields`)
- Values are JSONPath expressions evaluated against the incoming `request_data` / webhook payload
- Missing paths silently leave the target field unchanged
- Can be combined with `data_source` or `resource` on the same step

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

11. **Reserved Keyword**: The step name `initial` is reserved by the system for revision routing. Do NOT create a step named "initial".

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

## Print Settings (Optional)

The `print` section controls how the workflow document is rendered as a PDF.

```yaml
print:
  orientation: portrait         # portrait (default) | landscape
  page_size: A4                 # A4 (default) | Letter | Legal
  suppress_auto_header: true    # true (default) — if form.header exists, skip the auto company+title block
  suppress_section_header: false # false (default) — when true, hides all section title bars in the PDF
  show_history: true            # true (default) — render the Approval History table at the end
```

**Field Descriptions:**

| Field | Default | Description |
|---|---|---|
| `orientation` | `portrait` | Page orientation for PDF output |
| `page_size` | `A4` | Paper size — A4, Letter, or Legal |
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
        "data_source_props": ["source_id", "params", "object_path", "value_field", "label_field", "display"],
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
        "optional_props": ["approval_type", "signature_field", "on_approve", "on_reject", "timeout", "view_sections", "edit_sections"]
    },
    "parallel_approval": {
        "required_props": ["approvers", "approval_strategy"],
        "optional_props": ["signature_field", "on_approve", "on_reject", "timeout", "view_sections", "edit_sections"]
    },
    "conditional_split": {
        "required_props": ["choices"],
        "optional_props": ["default", "view_sections", "edit_sections"]
    },
    "automatic": {
        "required_props": ["on_complete"],
        "optional_props": ["api", "data_source", "resource", "field_mapping", "on_failure"],
        "requires_one_of": ["api", "data_source", "resource", "field_mapping"],
        "field_mapping_description": (
            "Maps values from the incoming webhook payload or instance request_data to form fields. "
            "Keys are form field names; values are JSONPath expressions evaluated against the payload. "
            "e.g. { invoice_no: '$.invoice.number', total: '$.invoice.total_amount' }"
        ),
        "data_source_props": {
            "required": ["source_id", "save_to"],
            "optional": ["compare_to_resource", "save_diff_to", "ignore_keys"]
        },
        "resource_props": {
            "required": ["data_from", "resource_name"]
        }
    },
    "notification": {
        "required_props": ["recipients", "notification", "on_complete"],
        "optional_props": []
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