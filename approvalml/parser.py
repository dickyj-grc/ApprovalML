"""
ApprovalML YAML Parser with comprehensive validation and schema support.
"""

import re
from enum import Enum
from typing import Any, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator


class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    EMAIL = "email"
    CURRENCY = "currency"
    NUMBER = "number"
    DATE = "date"
    DROPDOWN = "dropdown"  # Alias for select - more intuitive naming
    SELECT = "select"
    MULTISELECT = "multiselect"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE_UPLOAD = "file_upload"
    SIGNATURE = "signature"  # Digital signature capture
    RICHTEXT = "richtext"  # WYSIWYG editor with HTML formatting
    HIDDEN = "hidden"  # Hidden field for storing metadata
    LINE_ITEMS = "line_items"
    AUTOCOMPLETE = "autocomplete"  # Search-as-you-type with data source
    AUTONUMBER = "autonumber"  # Auto-incrementing sequential number with optional prefix/padding
    IMAGE = "image"  # Display-only image; value is a URL or resolved from company media asset gallery
    LABEL = "label"  # Display-only static text; always read-only, never renders an input widget
    JSON = "json"  # Stores any JSON value (array, object, primitive); displayed as formatted JSON


class StepType(str, Enum):
    DECISION = "decision"
    PARALLEL_APPROVAL = "parallel_approval"
    CONDITIONAL_SPLIT = "conditional_split"
    AUTOMATIC = "automatic"  # For API/connector calls only
    NOTIFICATION = "notification"  # For sending notifications
    END = "end"


class ParallelStrategy(str, Enum):
    ANY_ONE = "any_one"
    ALL = "all"


class ApprovalType(str, Enum):
    NEEDS_TO_APPROVE = "needs_to_approve"
    NEEDS_TO_SIGN = "needs_to_sign"
    NEEDS_TO_RECOMMEND = "needs_to_recommend"
    NEEDS_TO_ACKNOWLEDGE = "needs_to_acknowledge"
    NEEDS_TO_CALL_ACTION = "needs_to_call_action"
    RECEIVES_A_COPY = "receives_a_copy"


class ResponsiveLayout(BaseModel):
    """Responsive layout breakpoint configuration"""
    tablet: Optional[int] = None  # Max columns on tablet
    mobile: Optional[int] = None  # Max columns on mobile (usually 1)


class FieldLayoutOverride(BaseModel):
    """Per-field layout attributes for layout.defaults and section.fields.

    These are visual/positional attributes — they describe *how* a field is
    rendered in a specific context, not *what* the field is. Keeping them here
    instead of on FormField means the same field can appear differently across
    sections without duplication.

    Priority order (highest wins): section.fields > layout.defaults > field-level attrs (legacy)
    """
    align: Optional[str] = None           # "left" | "center" | "right"
    bottom_border: Optional[bool] = None  # Full-width bottom border under the field entry
    span: Optional[str] = None            # "full" | "half" | "auto" — grid column span hint
    valign: Optional[str] = None          # "top" | "middle" | "bottom"
    label_position: Optional[str] = None  # "above" | "inline" | "hidden"

    @field_validator('align')
    @classmethod
    def validate_align(cls, v):
        if v is not None and v not in ('left', 'center', 'right'):
            raise ValueError("align must be one of: left, center, right")
        return v

    @field_validator('valign')
    @classmethod
    def validate_valign(cls, v):
        if v is not None and v not in ('top', 'middle', 'bottom'):
            raise ValueError("valign must be one of: top, middle, bottom")
        return v

    @field_validator('span')
    @classmethod
    def validate_span(cls, v):
        if v is not None and v not in ('full', 'half', 'auto'):
            raise ValueError("span must be one of: full, half, auto")
        return v

    @field_validator('label_position')
    @classmethod
    def validate_label_position(cls, v):
        if v is not None and v not in ('above', 'inline', 'hidden'):
            raise ValueError("label_position must be one of: above, inline, hidden")
        return v


class FormSection(BaseModel):
    """Layout section for organizing form fields.

    Two layout modes:
    - grid: row-aligned grid — each inner list is a row of field names displayed side-by-side.
            Fields across rows are locked to the same column widths.
    - columns: independent column stacks — each inner list is a vertical stack of field names.
               Columns grow independently; no cross-row alignment. Better for mixed-height fields
               (e.g. a textarea next to a group of short text inputs).
    Exactly one of grid or columns must be specified.
    """
    id: str
    title: str
    description: Optional[str] = None
    initial: bool = False  # Whether this section is shown on initial submission
    grid: Optional[list[list[str]]] = None       # Row-aligned grid layout
    columns: Optional[list[list[str]]] = None    # Independent column-stack layout
    column_widths: Optional[list[str]] = None    # CSS flex widths per column e.g. ["2fr","1fr"] or ["60%","40%"]
                                                 # Length must match columns list; ignored when using grid
    fields: Optional[dict[str, FieldLayoutOverride]] = None  # Per-field layout overrides for this section.
                                                             # Keys are field names; values override layout.defaults
                                                             # for fields rendered inside this section.

    @model_validator(mode='after')
    def validate_layout_mode(self) -> 'FormSection':
        """Exactly one of grid or columns must be present."""
        has_grid = self.grid is not None
        has_columns = self.columns is not None
        if not has_grid and not has_columns:
            raise ValueError(f"Section '{self.id}' must define either 'grid' or 'columns'")
        if has_grid and has_columns:
            raise ValueError(f"Section '{self.id}' cannot define both 'grid' and 'columns' — choose one")
        return self


class FormLayout(BaseModel):
    """Form layout configuration"""
    sections: list[FormSection]
    fields: Optional[dict[str, FieldLayoutOverride]] = None  # Form-scope layout attributes per field, applied across
                                                             # all sections unless overridden by section.fields.
                                                             # Keys are field names.
    responsive: Optional[ResponsiveLayout] = None
    completed_sections: Optional[list[str]] = None  # Section IDs shown (read-only) when workflow has no pending step

    @field_validator('sections')
    @classmethod
    def validate_sections(cls, v):
        """Validate sections have unique IDs"""
        if not v or len(v) == 0:
            raise ValueError("Layout must contain at least one section")
        section_ids = [s.id for s in v]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("Section IDs must be unique")
        return v


class FooterColumns(BaseModel):
    """Responsive column configuration for footer"""
    desktop: int = 3
    tablet: int = 2
    mobile: int = 1

    @field_validator('desktop', 'tablet', 'mobile')
    @classmethod
    def validate_columns(cls, v):
        if v < 1 or v > 12:
            raise ValueError("Column count must be between 1 and 12")
        return v


class FooterItem(BaseModel):
    """Footer item configuration (message, legend, etc.)"""
    type: str  # "message", "legend", "divider", "image"
    content: Optional[Union[str, dict[str, str]]] = None  # String or key-value pairs for legend
    colspan: int = 1
    align: Optional[str] = None  # "left", "center", "right"
    valign: Optional[str] = None  # "top", "middle", "bottom"
    style: Optional[dict[str, str]] = None  # CSS styles

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        valid_types = ["message", "legend", "divider", "image"]
        if v not in valid_types:
            raise ValueError(f"Footer item type must be one of: {', '.join(valid_types)}")
        return v

    @field_validator('align')
    @classmethod
    def validate_align(cls, v):
        if v and v not in ["left", "center", "right", "justify"]:
            raise ValueError("align must be one of: left, center, right, justify")
        return v

    @field_validator('valign')
    @classmethod
    def validate_valign(cls, v):
        if v and v not in ["top", "middle", "bottom"]:
            raise ValueError("valign must be one of: top, middle, bottom")
        return v

    @field_validator('colspan')
    @classmethod
    def validate_colspan(cls, v):
        if v < 1 or v > 12:
            raise ValueError("colspan must be between 1 and 12")
        return v


class FormFooter(BaseModel):
    """Form footer configuration"""
    columns: Optional[FooterColumns] = None
    padding: Optional[str] = None
    background: Optional[str] = None
    border_top: Optional[str] = None
    items: list[FooterItem] = []

    @field_validator('items')
    @classmethod
    def validate_items(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Footer must contain at least one item")
        return v


class DataSourceParam(BaseModel):
    """Parameter configuration for data source"""
    name: str  # Parameter name
    from_field: str  # Field reference like "field.department" or "variable.user_id"


class DataSourceConfig(BaseModel):
    """Data source configuration for dynamic fields - handles both data fetching and response parsing"""
    source_id: str  # Data source ID (connector_id will be looked up from database)
    params: Optional[list[DataSourceParam]] = None  # Parameters to pass to data source

    # Response parsing configuration (how to interpret the data source response)
    object_path: Optional[str] = None  # JSONPath to data array (e.g., "$.data.items"), defaults to root if omitted
    value_field: Optional[str] = None  # Field name to extract as value; if omitted, stores entire object
    label_field: Optional[str] = None  # Field name to use for label (required for display)
    display: Optional[str] = None  # Optional display template like "{name} - {email}"


class SearchConfig(BaseModel):
    """Search UI behavior configuration for autocomplete fields"""
    min_length: int = 3  # Minimum characters before searching
    debounce_ms: int = 300  # Debounce delay in milliseconds
    max_results: Optional[int] = 50  # Maximum results to show


class OptionsConfig(BaseModel):
    """Options configuration - can be either static list or dynamic data source"""
    data_source: Optional[DataSourceConfig] = None  # Dynamic options from data source

    @model_validator(mode='after')
    def validate_options_config(self):
        """Validate that data_source is provided for dynamic options"""
        if not self.data_source:
            raise ValueError("Options must have data_source configured")
        return self


class FormField(BaseModel):
    """Validation schema for form fields"""
    name: Optional[str] = None  # For array format
    label: Optional[str] = None  # Required for all types except 'label' (validated below)
    type: FieldType
    required: bool = False
    description: Optional[str] = None
    placeholder: Optional[str] = None
    default_value: Optional[Union[str, int, float, bool]] = None

    # Calculated field support
    readonly: Optional[bool] = None
    print_only: Optional[bool] = None   # If True, field is shown in PDF only; hidden in the web form
    calculated: Optional[bool] = None
    formula: Optional[str] = None

    # Currency field support
    currency: Optional[str] = None  # Currency code (e.g., "USD", "IDR", "EUR")

    # Line items specific fields
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    item_fields: Optional[list['FormField']] = None

    # Options configuration - supports both static and dynamic options
    # Static: options: [{"value": "a", "label": "A"}, ...]
    # Dynamic: options: { data_source: { source_id: "...", ... } }
    options: Optional[Union[list[Union[str, dict[str, str]]], OptionsConfig]] = None

    # Search UI behavior (for autocomplete only)
    search: Optional[SearchConfig] = None

    # Radio button display mode
    display_as: Optional[str] = None  # For radio fields: "buttons" or None (default)

    # File upload specific
    accept: Optional[str] = None
    multiple: Optional[bool] = None
    capture: Optional[str] = None  # "environment" or "user" for camera

    # Autonumber field specific
    prefix: Optional[str] = None        # e.g. "EXP-", "PO-", "INV-"
    pad_length: Optional[int] = None    # zero-pad the number to this width (e.g. 5 → "00042")
    start_value: Optional[int] = None   # first number in the sequence (default 1)

    # Display control
    show_label: Optional[bool] = None   # If False, suppress the label caption (useful in header/footer zones)
    display: Optional[str] = None       # "inline" → label: value on one line; default is block (label above value)
    value_align: Optional[str] = None   # For display:"inline" only — aligns the VALUE text ("left"|"right"|"center")
                                        # Label is always left-aligned; value defaults to "right"

    # Column layout (for line_items item_fields and header/footer grid cells)
    align: Optional[str] = None         # "left" | "center" | "right" — aligns cell content in line_items columns
                                        # and block-mode read-only field values
    width: Optional[str] = None         # CSS width e.g. "120px", "15%"
    height: Optional[str] = None        # CSS height e.g. "60px", "20%" — primarily for image fields
    sum: Optional[bool] = None          # If True, show column sum in the footer row (read-only mode)
    text_style: Optional[list[str]] = None  # Text styling applied to the value in read-only display.

    # Image field configuration (type: image)
    source: Optional[str] = None        # Asset name from settings.media.assets — e.g. "company_logo"
                                        # If omitted the field value is used as the image URL directly
    placement: Optional[str] = None     # How the image is placed: "inline" (default) | "background" | "cover"
    object_fit: Optional[str] = None    # CSS object-fit: "cover" | "contain" (default) | "fill" | "scale-down" | "none"
    position: Optional[str] = None      # Horizontal alignment: "left" (default) | "center" | "right"
    bottom_border: Optional[bool] = None # Native full-width bottom underline

    @model_validator(mode='after')
    def validate_label_required(self):
        """label is optional only for type: label — all other types must supply it."""
        if self.type != FieldType.LABEL and not self.label:
            raise ValueError(f"Field '{self.name or '?'}': label is required for type '{self.type.value}'")
        return self

    @field_validator('text_style')
    @classmethod
    def validate_text_style(cls, v):
        if v is None:
            return v
        valid = {"bold", "italic", "underline", "strikethrough"}
        invalid = [s for s in v if s not in valid]
        if invalid:
            raise ValueError(f"Invalid text_style values: {invalid}. Valid: {sorted(valid)}")
        return v

    @field_validator('placement')
    @classmethod
    def validate_placement(cls, v, info):
        if v is None:
            return v
        if info.data.get('type') != FieldType.IMAGE:
            raise ValueError("placement is only valid for image fields")
        valid = {"inline", "background", "cover"}
        if v not in valid:
            raise ValueError(f"placement must be one of: {sorted(valid)}")
        return v

    @field_validator('object_fit')
    @classmethod
    def validate_object_fit(cls, v, info):
        if v is None:
            return v
        if info.data.get('type') != FieldType.IMAGE:
            raise ValueError("object_fit is only valid for image fields")
        valid = {"cover", "contain", "fill", "scale-down", "none"}
        if v not in valid:
            raise ValueError(f"object_fit must be one of: {sorted(valid)}")
        return v

    @field_validator('source')
    @classmethod
    def validate_source(cls, v, info):
        if v is not None and info.data.get('type') != FieldType.IMAGE:
            raise ValueError("source is only valid for image fields")
        return v

    @field_validator('item_fields')
    @classmethod
    def validate_line_items_config(cls, v, info):
        """Validate line_items configuration"""
        # Only validate if this is a line_items field
        if info.data.get('type') == FieldType.LINE_ITEMS:
            if not v:
                raise ValueError("line_items field must have item_fields defined")
            if len(v) == 0:
                raise ValueError("line_items field must have at least one item field")
        return v

    @field_validator('min_items')
    @classmethod
    def validate_min_items(cls, v, info):
        """Validate min_items configuration"""
        if info.data.get('type') == FieldType.LINE_ITEMS and v is not None:
            if v < 0:
                raise ValueError("min_items must be 0 or greater")
        return v

    @field_validator('max_items')
    @classmethod
    def validate_max_items(cls, v, info):
        """Validate max_items configuration"""
        if info.data.get('type') == FieldType.LINE_ITEMS and v is not None:
            min_items = info.data.get('min_items', 0)
            if v < min_items:
                raise ValueError("max_items must be greater than or equal to min_items")
            if v > 100:  # reasonable upper limit
                raise ValueError("max_items should not exceed 100")
        return v

    # Validation rules
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None

    # File upload specific (legacy, kept for compatibility)
    allowed_extensions: Optional[list[str]] = None
    max_file_size: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def handle_validation_object(cls, data: Any) -> Any:
        """Handle validation object in YAML and extract to direct fields"""
        if isinstance(data, dict) and 'validation' in data:
            validation = data.pop('validation')
            if isinstance(validation, dict):
                # Map validation.min/max to min_value/max_value
                if 'min' in validation and 'min_value' not in data:
                    data['min_value'] = validation['min']
                if 'max' in validation and 'max_value' not in data:
                    data['max_value'] = validation['max']
                if 'min_value' in validation and 'min_value' not in data:
                    data['min_value'] = validation['min_value']
                if 'max_value' in validation and 'max_value' not in data:
                    data['max_value'] = validation['max_value']
                # Map other validation properties
                if 'min_length' in validation and 'min_length' not in data:
                    data['min_length'] = validation['min_length']
                if 'max_length' in validation and 'max_length' not in data:
                    data['max_length'] = validation['max_length']
                if 'pattern' in validation and 'pattern' not in data:
                    data['pattern'] = validation['pattern']
        return data

    @field_validator('options')
    @classmethod
    def validate_options(cls, v: Optional[Union[list, OptionsConfig]], info: ValidationInfo) -> Optional[Union[list, OptionsConfig]]:
        """Validate options configuration"""
        field_type = info.data.get('type')

        # Select/multiselect/radio/autocomplete fields need options
        if field_type in [FieldType.SELECT, FieldType.MULTISELECT, FieldType.RADIO, FieldType.AUTOCOMPLETE]:
            if not v:
                raise ValueError(f"{field_type.value} fields must have options configured")

            # If it's a list (static options), validate for select/multiselect/radio only
            if isinstance(v, list) and field_type == FieldType.AUTOCOMPLETE:
                raise ValueError("Autocomplete fields must use dynamic options with data_source, not static options")

        return v

    @field_validator('search')
    @classmethod
    def validate_search(cls, v: Optional[SearchConfig], info: ValidationInfo) -> Optional[SearchConfig]:
        """Validate search configuration"""
        field_type = info.data.get('type')
        options = info.data.get('options')

        # Search only valid for autocomplete fields
        if v:
            if field_type != FieldType.AUTOCOMPLETE:
                raise ValueError("search is only supported for autocomplete fields")
            if v.min_length < 1:
                raise ValueError("search.min_length must be at least 1")
            if v.debounce_ms < 0:
                raise ValueError("search.debounce_ms must be non-negative")

        # Autocomplete fields should have search config
        if field_type == FieldType.AUTOCOMPLETE and not v:
            # Provide default search config
            return SearchConfig()

        return v

    @field_validator('pattern')
    def validate_pattern(cls, v):
        if v:
            try:
                re.compile(v)
            except re.error:
                raise ValueError("Invalid regex pattern")
        return v


class ApproverDetails(BaseModel):
    """Details for external/unregistered approvers"""
    email: str
    name: Optional[str] = None
    position: Optional[str] = None
    employee_type: Optional[str] = "external"  # internal, external, contractor

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        """Validate email format (basic check or template variable)"""
        if not v or not isinstance(v, str):
            raise ValueError("Email is required and must be a string")
        # Allow template variables like ${form.email}
        if v.startswith('${') and v.endswith('}'):
            return v
        # Basic email validation
        if '@' not in v:
            raise ValueError("Invalid email format")
        return v.lower()

    @field_validator('employee_type')
    @classmethod
    def validate_employee_type(cls, v):
        """Validate employee type"""
        if v:
            valid_types = ['internal', 'external', 'contractor']
            if v not in valid_types:
                raise ValueError(f"employee_type must be one of: {', '.join(valid_types)}")
        return v


class ApproverConfig(BaseModel):
    """Configuration for individual approvers"""
    approver: Optional[Union[str, ApproverDetails]] = None  # Email string or approver details object
    dynamic_approver: Optional[str] = None  # Template like ${requestor.supervisor}
    role: Optional[str] = None  # Role-based assignment
    approval_type: ApprovalType = ApprovalType.NEEDS_TO_APPROVE
    sla_hours: Optional[int] = None
    can_edit_fields: Optional[list[str]] = None

    @model_validator(mode='before')
    @classmethod
    def check_approver_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            approver_fields = ['approver', 'dynamic_approver', 'role']
            provided_fields = [field for field in approver_fields if data.get(field) is not None]
            if len(provided_fields) != 1:
                raise ValueError(f"Exactly one of {approver_fields} must be provided. Found: {provided_fields}")
        return data


# Removed Condition class - only string-based conditions are supported


class ActionConfig(BaseModel):
    """Configuration for workflow actions"""
    continue_to: Optional[str] = None
    end_workflow: Optional[bool] = None
    notify_requestor: Optional[str] = None
    email: Optional[bool] = None
    slack: Optional[str] = None
    webhook: Optional[str] = None
    update_budget: Optional[str] = None
    archive_request: Optional[bool] = None
    generate_po_number: Optional[bool] = None
    custom_actions: Optional[dict[str, Any]] = None


class NotificationRecipient(BaseModel):
    """Recipient configuration for notifications"""
    email: Optional[str] = None  # Specific email or variable like ${instance.requester_email}
    role: Optional[str] = None   # Role name like "finance_team"
    user_id: Optional[int] = None  # Specific user ID


class NotificationMessage(BaseModel):
    """Message content for notifications"""
    subject: str  # Subject line / notification title
    body: str     # Message body content


class NotificationConfig(BaseModel):
    """Notification configuration"""
    message: NotificationMessage  # The message to send (channel-agnostic)


class ApiConfig(BaseModel):
    """API configuration for automatic steps"""
    connector: str  # Required: Connector name (e.g., "Claude AI", "ERP System")
    action: str     # Required: Action name within connector
    parameters: Optional[dict[str, Any]] = None  # Parameters for the API call
    timeout: Optional[int] = None  # Timeout in seconds
    save_to: Optional[str] = None  # Variable name to save the response


class DataSourceParameterMapping(BaseModel):
    """Parameter mapping for data source"""
    name: str  # Parameter name
    from_field: Optional[str] = None  # Map from form field (e.g., "field.department")
    value: Optional[Any] = None  # Or provide a static value

    @field_validator('from_field', 'value')
    @classmethod
    def validate_source(cls, v, info: ValidationInfo):
        """Validate that either from_field or value is provided"""
        # Allow both to be None temporarily, will be checked in model_validator
        return v

    @model_validator(mode='after')
    def validate_has_source(self):
        """Ensure either from_field or value is provided"""
        if self.from_field is None and self.value is None:
            raise ValueError(f"Parameter '{self.name}' must have either 'from_field' or 'value'")
        if self.from_field is not None and self.value is not None:
            raise ValueError(f"Parameter '{self.name}' cannot have both 'from_field' and 'value'")
        return self


class DataSourceJoin(BaseModel):
    """Inline batch-lookup join for relational ID fields on fetched rows.

    Resolves integer FK fields (e.g. tax_id: [123, 456]) into human-readable
    names in a single step — no extra steps, no JSONata, no vars wiring needed.

    Single field:
        pick: name
        as: tax_name

    Multiple fields (one API call, multiple output fields):
        pick:
          tax_name: name
          tax_rate: amount
        # `as` not needed when pick is a dict
    """
    field: str                                          # field on each row containing the ID(s)
    source_id: str                                      # connector source to batch-fetch from
    on: str = 'id'                                      # key field in join records (default: "id")
    pick: Union[str, dict[str, str]] = 'name'           # single field name OR {output: source} mapping
    as_field: Optional[str] = Field(default=None, alias='as')  # output field; required when pick is a string
    param: str = 'ids'                                  # parameter name sent to join source (default: "ids")
    separator: str = ', '                               # separator for multi-value joins (default: ", ")
    as_array: bool = False                              # if True, output is a list instead of joined string

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode='after')
    def validate_as_required_for_string_pick(self):
        """as is required when pick is a single field name; not needed when pick is a dict."""
        if isinstance(self.pick, str) and not self.as_field:
            raise ValueError("'as' is required when 'pick' is a single field name")
        return self


class DataSourceConfig(BaseModel):
    """Data source configuration for fetching external data in workflows"""
    # New preferred method: use source_id (unique identifier)
    source_id: Optional[str] = None  # Data source unique ID (e.g., "src_abc123")

    # Legacy method: use connector + source names
    connector: Optional[str] = None  # Connector name (e.g., "my_database", "airtable_connector")
    source: Optional[str] = None     # Data source name within connector

    params: Optional[list[DataSourceParameterMapping]] = None  # Parameter mappings
    save_to: str    # Required: Variable name to save the fetched data (e.g., "employees_json")
    timeout: Optional[int] = None  # Timeout in seconds
    join: Optional[list[DataSourceJoin]] = None  # Inline batch-lookup joins for relational ID fields

    @model_validator(mode='after')
    def validate_source_specification(self):
        """Validate that either source_id OR (connector + source) is provided"""
        if not self.source_id and not (self.connector and self.source):
            raise ValueError(
                "Data source must specify either 'source_id' OR both 'connector' and 'source'"
            )
        return self


class WorkflowStep(BaseModel):
    """Validation schema for workflow steps"""
    name: str
    type: StepType
    description: Optional[str] = None

    # Step-specific configurations
    approvers: Optional[list[ApproverConfig]] = None
    approver: Optional[Union[str, dict]] = None  # Single approver shorthand - email string or details object
    approval_type: Optional[ApprovalType] = None

    # Parallel approval specific
    strategy: Optional[ParallelStrategy] = ParallelStrategy.ALL

    # For conditional_split: list of condition choices
    choices: Optional[list[dict]] = None
    # Default action for conditional_split
    default: Optional[dict] = None

    # Section visibility controls (for layout sections)
    view_sections: Optional[list[str]] = None  # Sections shown as readonly
    edit_sections: Optional[list[str]] = None  # Sections shown as fully editable
    # mixed_sections: sections shown with only specific fields editable; everything else readonly.
    # Keys are section IDs; values have an "editable" list of field names.
    # Example:  mixed_sections: { totals_section: { editable: [disc_total, u_muka] } }
    mixed_sections: Optional[dict[str, dict]] = None

    # Notification-specific fields (for type: notification)
    recipients: Optional[list[NotificationRecipient]] = None
    notification: Optional[NotificationConfig] = None

    # API configuration (for type: automatic)
    api: Optional[ApiConfig] = None

    # Data source configuration (for fetching external data)
    data_source: Optional[DataSourceConfig] = None

    # Actions
    on_approve: Optional[ActionConfig] = None
    on_reject: Optional[ActionConfig] = None
    on_complete: Optional[ActionConfig] = None
    on_timeout: Optional[ActionConfig] = None
    on_failure: Optional[ActionConfig] = None  # For automatic steps

    # Timing
    timeout: Optional[str] = None  # e.g., "48_hours", "5_business_days"
    sla_hours: Optional[int] = None

    # Integration
    webhook_url: Optional[str] = None
    api_endpoint: Optional[str] = None

    # Metadata (especially useful for end nodes to track outcome)
    metadata: Optional[dict[str, Any]] = None

    # Final notification before ending (for type: end nodes)
    notify_requestor: Optional[str] = None

    # Digital signature requirement (for type: decision steps)
    # Value is the name of a form field with type: signature that must be filled
    # before the approver's action is accepted.
    signature_field: Optional[str] = None

    # Field mapping for automatic steps that receive a webhook payload.
    # Keys are form field names; values are either:
    # - Simple string: JSONPath expression for scalar fields
    # - Dict with 'source' and 'item_fields': For mapping arrays to line_items
    # Examples:
    #   Simple: field_mapping: { invoice_no: "$.invoice.number" }
    #   Array:  field_mapping: { invoice_lines: { source: "$.data", item_fields: {...} } }
    field_mapping: Optional[dict[str, Union[str, dict]]] = None

    @field_validator('choices')
    @classmethod
    def validate_choices(cls, v):
        """Validate choices for conditional_split"""
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("Choices must be a list")
            for choice in v:
                if not isinstance(choice, dict):
                    raise ValueError("Each choice must be a dictionary")
                if 'conditions' not in choice:
                    raise ValueError("Each choice must have 'conditions'")
                if 'continue_to' not in choice:
                    raise ValueError("Each choice must have 'continue_to'")
                if not isinstance(choice['conditions'], str) or not choice['conditions'].strip():
                    raise ValueError("Choice conditions must be a non-empty string")
        return v

    @field_validator('timeout')
    def validate_timeout(cls, v):
        if v:
            # Parse timeout formats like "48_hours", "5_business_days"
            pattern = r'^\d+_(hours|business_days|days|minutes)$'
            if not re.match(pattern, v):
                raise ValueError("Invalid timeout format. Use format like '48_hours' or '5_business_days'")
        return v

    @field_validator('field_mapping')
    @classmethod
    def validate_field_mapping_jsonpath(cls, v):
        """Validate JSONPath expressions and nested structures in field_mapping."""
        if v:
            for field_name, mapping in v.items():
                if isinstance(mapping, str):
                    # Simple scalar mapping - validate JSONPath
                    if not mapping.startswith('$.'):
                        raise ValueError(
                            f"JSONPath expression for '{field_name}' must start with '$.' (got: {mapping})"
                        )
                elif isinstance(mapping, dict):
                    # Check if it's a JSONata transformation
                    if 'jsonata' in mapping:
                        # JSONata transformation: { source: "$.path", jsonata: "expression" }
                        if 'source' in mapping:
                            if not isinstance(mapping['source'], str):
                                raise ValueError(f"'source' in field_mapping for '{field_name}' must be a string")
                            if not mapping['source'].startswith('$.'):
                                raise ValueError(f"'source' JSONPath for '{field_name}' must start with '$.' (got: {mapping['source']})")
                        if not isinstance(mapping['jsonata'], str):
                            raise ValueError(f"'jsonata' in field_mapping for '{field_name}' must be a string")

                    # Check if it's a nested array mapping for line_items
                    elif 'item_fields' in mapping:
                        # Nested array mapping: { source: "$.array", item_fields: {...} }
                        if 'source' not in mapping:
                            raise ValueError(
                                f"Nested field_mapping for '{field_name}' must have 'source' (JSONPath to array)"
                            )
                        if not isinstance(mapping['source'], str):
                            raise ValueError(
                                f"'source' in field_mapping for '{field_name}' must be a string"
                            )
                        if not mapping['source'].startswith('$.'):
                            raise ValueError(
                                f"'source' JSONPath for '{field_name}' must start with '$.' (got: {mapping['source']})"
                            )
                        if not isinstance(mapping['item_fields'], dict):
                            raise ValueError(
                                f"'item_fields' in field_mapping for '{field_name}' must be a dict"
                            )

                    else:
                        raise ValueError(
                            f"Dict field_mapping for '{field_name}' must have either 'jsonata' (transformation) or 'item_fields' (array mapping)"
                        )
                else:
                    raise ValueError(
                        f"field_mapping value for '{field_name}' must be string (JSONPath) or dict with 'jsonata' or 'item_fields'"
                    )
        return v

    @model_validator(mode='after')
    def validate_step_type_requirements(self):
        """Validate that required fields are present based on step type"""
        # Automatic steps must have api, data_source, or asset configuration
        if self.type == StepType.AUTOMATIC:
            if not self.api and not self.data_source and not self.field_mapping:
                raise ValueError(
                    "Automatic steps must have either 'api' configuration (connector + action), "
                    "'data_source' (external data fetch), or 'field_mapping' (payload mapping)"
                )
            if self.api and (not self.api.connector or not self.api.action):
                raise ValueError("Automatic steps must specify both 'connector' and 'action' in api config")

            # field_mapping with data_source is valid
            # field_mapping alone is valid (for webhook payload mapping)

        # Notification steps must have recipients and notification
        if self.type == StepType.NOTIFICATION:
            if not self.recipients:
                raise ValueError("Notification steps must have 'recipients'")
            if not self.notification:
                raise ValueError("Notification steps must have 'notification' with message")

        return self


class PageOrientation(str, Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class PrintConfig(BaseModel):
    """PDF/print settings for this workflow document."""
    orientation: PageOrientation = PageOrientation.PORTRAIT
    page_size: str = "A4"                  # A4 | Letter | Legal
    suppress_auto_header: bool = True      # If True and form.header exists, skip the auto company+title block
    suppress_section_header: bool = False  # If True, hide all section title bars in the PDF
    show_history: bool = True              # Whether to render the Approval History table in the PDF

    @field_validator('page_size')
    @classmethod
    def validate_page_size(cls, v):
        allowed = {'A4', 'Letter', 'Legal'}
        if v not in allowed:
            raise ValueError(f"page_size must be one of: {sorted(allowed)}")
        return v


class Settings(BaseModel):
    """Global workflow settings"""
    timeout: Optional[dict[str, str]] = None
    escalation: Optional[list[dict[str, str]]] = None
    audit: Optional[dict[str, bool]] = None
    notifications: Optional[dict[str, Any]] = None
    sla_defaults: Optional[dict[str, int]] = None


class Integrations(BaseModel):
    """External system integrations"""
    webhooks: Optional[dict[str, str]] = None
    email_templates: Optional[dict[str, str]] = None
    slack_channels: Optional[dict[str, str]] = None
    api_endpoints: Optional[dict[str, str]] = None


class FieldZone(BaseModel):
    """A page-repeating print zone (header or footer) defined via a field grid or columns.

    Fields listed in the grid/columns are resolved by name.  Resolution order (Option A):
    1. ``zone.fields[]`` — inline field definitions local to this zone
    2. ``form.fields[]`` — the global form field list

    Zone-local fields (defined in ``zone.fields``) are NOT rendered in the form body;
    they only appear inside this zone.  Use them for display-only cells like company
    logos, invoice titles, or delivery reference boxes that must not clutter the body.

    Two layout modes:
    - grid: Each inner list is a ROW, elements placed horizontally
      Example: [["company_name", "invoice_no"], ["address"]] creates 2 rows
    - columns: Each inner list is a COLUMN, elements stacked vertically
      Example: [["logo"], ["company_name", "address", "npwp"]] creates 2 columns

    Auto-sizing:
    - autosize: true - All columns use CSS Grid 'auto' (size based on content)
    - column_widths: ["auto", "1fr", 2] - Mix auto, fr units, and numeric values
    """
    fields: Optional[list['FormField']] = None  # Zone-local field definitions (not rendered in form body)
    grid: Optional[list[list[str]]] = None  # Row-based layout
    columns: Optional[list[list[str]]] = None  # Column-based layout
    column_widths: Optional[list[Union[int, str]]] = None  # Numeric (fr) or string ("auto", "min-content", etc.)
    autosize: Optional[bool] = None  # If true, all columns use 'auto' sizing
    title: Optional[str] = None  # Optional zone title (not rendered in PDF, used for tooling)

    @model_validator(mode='after')
    def validate_has_grid_or_columns(self):
        """Ensure at least one of grid or columns is provided"""
        if not self.grid and not self.columns:
            raise ValueError("FieldZone must have either 'grid' or 'columns' defined")

        # Use whichever is provided (columns takes precedence)
        rows = self.columns if self.columns is not None else self.grid

        # Validate the rows
        if not rows:
            raise ValueError("FieldZone grid/columns must contain at least one row")
        for row in rows:
            if not isinstance(row, list):
                raise ValueError("Each grid/columns row must be a list of field names")

        # Validate column_widths if provided
        if self.column_widths:
            for width in self.column_widths:
                if isinstance(width, str):
                    # Allow CSS Grid sizing keywords
                    if width not in ['auto', 'min-content', 'max-content', 'fit-content']:
                        raise ValueError(
                            f"Invalid column width '{width}'. "
                            f"String values must be 'auto', 'min-content', 'max-content', or 'fit-content'. "
                            f"Use numeric values for fractional units (e.g., 1, 2, 3)."
                        )

        return self


# ==========================================
# TRIGGER CONFIGURATION (Scheduled Workflows)
# ==========================================

class TriggerType(str, Enum):
    """Types of workflow triggers"""
    CRON = "cron"
    WEBHOOK = "webhook"
    ONE_TIME = "one_time"


class DataConditionConfig(BaseModel):
    """Configuration for data-driven trigger conditions.

    Fetches data from a data source and optionally compares it against
    a saved asset baseline using deepdiff.
    """
    data_source_connector: Optional[str] = None              # Connector name (optional, resolved from source)
    data_source_name: str                                   # Data source name (e.g., "GCP IAM Users")
    compare_to_asset: Optional[str] = None                  # Asset name for deepdiff comparison
    params: Optional[list[dict[str, Any]]] = None           # Data source parameters
    ignore_keys: Optional[list[str]] = None                 # Keys to ignore in deepdiff comparison


class TriggerConfig(BaseModel):
    """Individual trigger configuration within a workflow YAML.

    Supports three trigger types:
    - cron: Recurring schedule (requires 'schedule' field with cron expression)
    - webhook: External HTTP POST trigger (webhook token auto-generated)
    - one_time: Single execution at a scheduled time
    """
    type: TriggerType
    schedule: Optional[str] = None                          # Cron expression (required for cron type)
    max_runs: Optional[int] = None                          # Maximum number of executions (null = unlimited)
    data_condition: Optional[DataConditionConfig] = None    # Optional data-driven condition
    preset_form_data: Optional[dict[str, Any]] = None       # Auto-fill form fields by name match
    requestor_email: Optional[str] = None                   # Employee email to act as requestor

    # Field mapping for webhook/URL triggers
    # Maps incoming payload/query params to form fields using JSONPath expressions
    # Supports both simple scalar mapping and nested array mapping for line_items
    # e.g. field_mapping: { customer_name: "$.customer.name", invoice_lines: { source: "$.data", item_fields: {...} } }
    field_mapping: Optional[dict[str, Union[str, dict]]] = None

    @field_validator('field_mapping')
    @classmethod
    def validate_field_mapping_jsonpath(cls, v):
        """Validate JSONPath expressions and nested structures."""
        if v:
            for field_name, mapping in v.items():
                if isinstance(mapping, str):
                    # Simple scalar mapping - validate JSONPath
                    if not mapping.startswith('$.'):
                        raise ValueError(
                            f"JSONPath expression for '{field_name}' must start with '$.' (got: {mapping})"
                        )
                elif isinstance(mapping, dict):
                    # Check if it's a JSONata transformation
                    if 'jsonata' in mapping:
                        # JSONata transformation: { source: "$.path", jsonata: "expression" }
                        if 'source' in mapping:
                            if not isinstance(mapping['source'], str):
                                raise ValueError(f"'source' in field_mapping for '{field_name}' must be a string")
                            if not mapping['source'].startswith('$.'):
                                raise ValueError(f"'source' JSONPath for '{field_name}' must start with '$.' (got: {mapping['source']})")
                        if not isinstance(mapping['jsonata'], str):
                            raise ValueError(f"'jsonata' in field_mapping for '{field_name}' must be a string")

                    # Check if it's a nested array mapping for line_items
                    elif 'item_fields' in mapping:
                        # Nested array mapping: { source: "$.array", item_fields: {...} }
                        if 'source' not in mapping:
                            raise ValueError(
                                f"Nested field_mapping for '{field_name}' must have 'source' (JSONPath to array)"
                            )
                        if not isinstance(mapping['source'], str):
                            raise ValueError(
                                f"'source' in field_mapping for '{field_name}' must be a string"
                            )
                        if not mapping['source'].startswith('$.'):
                            raise ValueError(
                                f"'source' JSONPath for '{field_name}' must start with '$.' (got: {mapping['source']})"
                            )
                        if not isinstance(mapping['item_fields'], dict):
                            raise ValueError(
                                f"'item_fields' in field_mapping for '{field_name}' must be a dict"
                            )

                    else:
                        raise ValueError(
                            f"Dict field_mapping for '{field_name}' must have either 'jsonata' (transformation) or 'item_fields' (array mapping)"
                        )
                else:
                    raise ValueError(
                        f"field_mapping value for '{field_name}' must be string (JSONPath) or dict with 'jsonata' or 'item_fields'"
                    )
        return v

    @model_validator(mode='after')
    def validate_trigger_type_requirements(self):
        """Validate that required fields are present based on trigger type."""
        if self.type == TriggerType.CRON and not self.schedule:
            raise ValueError("Cron triggers must have a 'schedule' field with a valid cron expression")
        if self.type == TriggerType.WEBHOOK and self.schedule:
            raise ValueError("Webhook triggers should not have a 'schedule' field")
        if self.type == TriggerType.ONE_TIME and not self.schedule:
            raise ValueError("One-time triggers must have a 'schedule' field with a datetime or cron expression")
        if self.max_runs is not None and self.max_runs < 1:
            raise ValueError("max_runs must be at least 1")
        return self


class ApprovalProcess(BaseModel):
    """Main ApprovalML workflow schema"""
    name: str
    description: Optional[str] = None
    version: str = "1.0"

    # Form definition - normalized to dict[str, FormField] after validation
    form: dict[str, FormField]

    # Form layout configuration (optional)
    form_layout: Optional[FormLayout] = None

    # Form header zone (page-repeating, field-grid based)
    form_header: Optional[FieldZone] = None

    # Form footer configuration (optional)
    # Accepts either the legacy item-based FormFooter or the new FieldZone grid model.
    form_footer: Optional[Union[FormFooter, FieldZone]] = None

    # Workflow steps
    workflow: dict[str, WorkflowStep]

    # Optional configurations
    settings: Optional[Settings] = None
    print: Optional[PrintConfig] = None    # PDF/print layout settings
    integrations: Optional[Integrations] = None

    # Scheduled workflow triggers (cron, webhook, one_time)
    triggers: Optional[list[TriggerConfig]] = None

    # Test data: pre-filled field values used by the designer's test mode.
    # These are NOT used in production; they only pre-populate the test submission form
    # so testers don't have to fill in every field manually.
    test_data: Optional[dict[str, Any]] = None

    # Optional simple key-rename map for URL/API auto-submit.
    # When the calling system uses different parameter names than the form field names,
    # this renames incoming keys before they are matched to form fields.
    # e.g. param_mapping: { emp_id: employee_id, cost: amount }
    # Works for query-string params and flat API payloads (no JSONPath needed).
    param_mapping: Optional[dict[str, str]] = None

    # Optional list of company_roles that can view ALL submissions for this workflow.
    # Users whose company_roles intersect this list get a "My Requests / All Submissions"
    # toggle in the workflow list view — bypassing the default participant-scoped filter.
    # e.g. view_all_roles: ["finance", "admin", "hr"]
    # Leave empty or omit to use default access (requestor + approvers + org managers only).
    view_all_roles: Optional[list[str]] = None

    @model_validator(mode='before')
    @classmethod
    def normalize_form_format(cls, data):
        """Convert new format with 'fields' array, layout, and footer to normalized format"""
        if isinstance(data, dict) and 'form' in data:
            form_data = data['form']
            if isinstance(form_data, dict):
                # Extract layout if present
                if 'layout' in form_data:
                    data['form_layout'] = form_data['layout']

                # Extract header if present (new FieldZone-based header)
                if 'header' in form_data:
                    data['form_header'] = form_data['header']

                # Extract footer if present
                if 'footer' in form_data:
                    data['form_footer'] = form_data['footer']

                # Handle 'fields' array format
                if 'fields' in form_data:
                    # New format: { "fields": [ { "name": "field1", ... }, ... ] }
                    fields_array = form_data['fields']
                    if isinstance(fields_array, list):
                        normalized_form = {}
                        for field in fields_array:
                            if isinstance(field, dict) and 'name' in field:
                                field_name = field['name']
                                field_copy = field.copy()
                                del field_copy['name']  # Remove name from field definition
                                normalized_form[field_name] = field_copy
                        data['form'] = normalized_form
        return data

    @field_validator('workflow')
    def validate_workflow_references(cls, v):
        """Validate that workflow step references are valid"""
        step_ids = set(v.keys())

        for step_id, step in v.items():
            # Check continue_to references in actions
            for action_field in ['on_approve', 'on_reject', 'on_complete', 'on_timeout']:
                action = getattr(step, action_field, None)
                if action and action.continue_to:
                    if action.continue_to not in step_ids:
                        raise ValueError(f"Step '{step_id}' references unknown step '{action.continue_to}'")

            # Check continue_to references in choices
            if step.choices:
                for choice in step.choices:
                    if 'continue_to' in choice and choice['continue_to'] not in step_ids:
                        raise ValueError(f"Step '{step_id}' choice references unknown step '{choice['continue_to']}'")

            # Check continue_to references in default
            if step.default and 'continue_to' in step.default:
                default_target = step.default['continue_to']
                if default_target not in step_ids:
                    raise ValueError(f"Step '{step_id}' default references unknown step '{default_target}'")

        return v

    @model_validator(mode='after')
    def validate_section_references(self):
        """Validate that workflow step section references exist in layout"""
        if self.form_layout and self.workflow:
            section_ids = {section.id for section in self.form_layout.sections}

            for step_id, step in self.workflow.items():
                # Validate view_sections
                if step.view_sections:
                    for section_id in step.view_sections:
                        if section_id not in section_ids:
                            raise ValueError(
                                f"Step '{step_id}' references unknown section '{section_id}' in view_sections. "
                                f"Available sections: {', '.join(sorted(section_ids))}"
                            )

                # Validate edit_sections
                if step.edit_sections:
                    for section_id in step.edit_sections:
                        if section_id not in section_ids:
                            raise ValueError(
                                f"Step '{step_id}' references unknown section '{section_id}' in edit_sections. "
                                f"Available sections: {', '.join(sorted(section_ids))}"
                            )

                # Validate mixed_sections
                if step.mixed_sections:
                    for section_id in step.mixed_sections:
                        if section_id not in section_ids:
                            raise ValueError(
                                f"Step '{step_id}' references unknown section '{section_id}' in mixed_sections. "
                                f"Available sections: {', '.join(sorted(section_ids))}"
                            )

            # Validate completed_sections on the layout itself
            if self.form_layout.completed_sections:
                for section_id in self.form_layout.completed_sections:
                    if section_id not in section_ids:
                        raise ValueError(
                            f"form.layout.completed_sections references unknown section '{section_id}'. "
                            f"Available sections: {', '.join(sorted(section_ids))}"
                        )

        return self

    @model_validator(mode='after')
    def validate_layout_field_references(self):
        """Validate that layout sections reference existing form fields"""
        if self.form_layout:
            form_field_names = set(self.form.keys())

            for section in self.form_layout.sections:
                # Flatten grid to get all field references
                referenced_fields = set()
                for row in section.grid:
                    referenced_fields.update(row)

                # Check if all referenced fields exist
                for field_name in referenced_fields:
                    if field_name not in form_field_names:
                        raise ValueError(
                            f"Section '{section.id}' references unknown field '{field_name}'. "
                            f"Available fields: {', '.join(sorted(form_field_names))}"
                        )

        return self


class ApprovalMLParser:
    """Main parser class for ApprovalML YAML files"""

    def __init__(self):
        self.parsed_workflow: Optional[ApprovalProcess] = None
        self.validation_errors: list[str] = []

    def parse_yaml(self, yaml_content: str) -> Optional[ApprovalProcess]:
        """Parse YAML content and validate against schema"""
        try:
            # Parse YAML
            data = yaml.safe_load(yaml_content)

            if not isinstance(data, dict):
                raise ValueError("YAML must contain a dictionary at root level")

            # Support both direct format and nested approval_process format
            if 'approval_process' in data:
                # Nested format with approval_process section
                process_data = data['approval_process']
            else:
                # Direct format - YAML root is the process data
                process_data = data

            # Validate and parse using Pydantic
            self.parsed_workflow = ApprovalProcess(**process_data)
            self.validation_errors = []

            return self.parsed_workflow

        except yaml.YAMLError as e:
            self.validation_errors = [f"YAML parsing error: {str(e)}"]
            return None
        except ValidationError as e:
            self.validation_errors = [f"Validation error: {str(e)}"]
            return None
        except Exception as e:
            self.validation_errors = [f"Unexpected error: {str(e)}"]
            return None

    def parse_file(self, file_path: str) -> Optional[ApprovalProcess]:
        """Parse ApprovalML file from disk"""
        try:
            with open(file_path, encoding='utf-8') as file:
                yaml_content = file.read()
            return self.parse_yaml(yaml_content)
        except FileNotFoundError:
            self.validation_errors = [f"File not found: {file_path}"]
            return None
        except OSError as e:
            self.validation_errors = [f"Error reading file: {str(e)}"]
            return None

    def validate_workflow_semantics(self) -> list[str]:
        """Additional semantic validation beyond schema validation"""
        if not self.parsed_workflow:
            return ["No parsed workflow to validate"]

        errors = []

        # Check for unreachable steps
        workflow = self.parsed_workflow.workflow

        # Find entry points (steps with no incoming references)
        referenced_steps = set()
        for step in workflow.values():
            for action_field in ['on_approve', 'on_reject', 'on_complete', 'on_timeout']:
                action = getattr(step, action_field, None)
                if action and action.continue_to:
                    referenced_steps.add(action.continue_to)

        entry_points = set(workflow.keys()) - referenced_steps
        if not entry_points:
            errors.append("No entry point found in workflow (all steps are referenced)")

        # Check for cycles (basic detection)
        # This is a simplified cycle detection - could be enhanced

        # Validate form field references in choices format
        form_fields = set(self.parsed_workflow.form.keys())
        for step_id, step in workflow.items():
            if step.choices:
                import re
                field_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b'
                for choice in step.choices:
                    if 'conditions' in choice:
                        potential_fields = re.findall(field_pattern, choice['conditions'])
                        for field in potential_fields:
                            # Skip common operators and keywords
                            keywords = ['and', 'or', 'not', 'in', 'true', 'false', 'True', 'False']
                            if field not in keywords and field not in form_fields:
                                # This is a warning rather than an error since string conditions are more flexible
                                pass  # Could add warnings here if needed

        return errors


    def extract_variables(self) -> list[str]:
        """Extract all template variables used in the workflow"""
        if not self.parsed_workflow:
            return []

        variables = set()
        variable_pattern = r'\$\{([^}]+)\}'

        # Convert workflow to string and extract variables
        workflow_str = str(self.parsed_workflow.model_dump())
        matches = re.findall(variable_pattern, workflow_str)
        variables.update(matches)

        return list(variables)

    def get_validation_summary(self) -> dict[str, Any]:
        """Get comprehensive validation summary"""
        semantic_errors = self.validate_workflow_semantics() if self.parsed_workflow else []

        return {
            "is_valid": len(self.validation_errors) == 0 and len(semantic_errors) == 0,
            "schema_errors": self.validation_errors,
            "semantic_errors": semantic_errors,
            "workflow_name": self.parsed_workflow.name if self.parsed_workflow else None,
            "step_count": len(self.parsed_workflow.workflow) if self.parsed_workflow else 0,
            "form_field_count": len(self.parsed_workflow.form) if self.parsed_workflow else 0,
            "template_variables": self.extract_variables(),
        }


def parse_approvalml(yaml_content: str) -> tuple[Optional[ApprovalProcess], dict[str, Any]]:
    """Convenience function to parse ApprovalML and return validation summary"""
    parser = ApprovalMLParser()
    workflow = parser.parse_yaml(yaml_content)
    validation_summary = parser.get_validation_summary()

    return workflow, validation_summary


def parse_approvalml_file(file_path: str) -> tuple[Optional[ApprovalProcess], dict[str, Any]]:
    """Convenience function to parse ApprovalML file and return validation summary"""
    parser = ApprovalMLParser()
    workflow = parser.parse_file(file_path)
    validation_summary = parser.get_validation_summary()

    return workflow, validation_summary
