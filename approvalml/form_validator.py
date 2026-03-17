"""
Form Data Validation Utilities

This module provides utilities for validating form data against workflow field definitions,
with special handling for dynamic field types like autocomplete.
"""

from typing import Any, Dict, List, Optional, Tuple


def is_autocomplete_object_field(field_def: Dict[str, Any]) -> bool:
    """
    Determine if an autocomplete field is configured to store objects.

    An autocomplete field stores objects when value_field is NOT specified
    in the data_source configuration. When value_field is omitted, the entire
    object is stored instead of just extracting a single field value.

    Args:
        field_def: Field definition from workflow YAML

    Returns:
        True if field should store objects, False if it stores primitives (IDs)
    """
    if field_def.get("type") != "autocomplete":
        return False

    # New structure: options.data_source.value_field
    options = field_def.get("options", {})
    if isinstance(options, dict):
        data_source = options.get("data_source", {})
        value_field = data_source.get("value_field")

        # If value_field is not set, stores entire object
        return value_field is None

    # Legacy structure: search.value_field (for backward compatibility)
    search_config = field_def.get("search", {})
    value_field = search_config.get("value_field")

    # Check for object_path (indicates nested object structure)
    if "object_path" in search_config:
        return value_field is None

    # Default to object storage if value_field not specified
    return value_field is None


def get_expected_value_type(field_def: Dict[str, Any]) -> str:
    """
    Get the expected value type for a field.

    Args:
        field_def: Field definition from workflow YAML

    Returns:
        One of: "string", "number", "boolean", "object", "array", "any", "flexible"
    """
    field_type = field_def.get("type")

    # Special handling for autocomplete with data_source
    # These fields can store either primitives (string/number) or objects depending on configuration
    # Return "flexible" to accept both types
    if field_type == "autocomplete":
        # Check if it has data_source configuration
        options = field_def.get("options", {})
        if isinstance(options, dict) and "data_source" in options:
            return "flexible"  # Accept both primitives and objects
        # Legacy check
        if "data_source" in field_def:
            return "flexible"
        # Fallback to string for non-data-source autocomplete
        return "string"

    # Standard field type mappings
    type_mapping = {
        "text": "string",
        "textarea": "string",
        "email": "string",
        "number": "number",
        "currency": "number",
        "date": "string",
        "select": "string",
        "multiselect": "array",
        "checkbox": "boolean",
        "radio": "string",
        "file_upload": "string",  # Usually stores file path or ID
        "line_items": "array",
    }

    return type_mapping.get(field_type, "any")


def validate_field_value(
    field_name: str,
    field_def: Dict[str, Any],
    value: Any,
    strict: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Validate a form field value against its field definition.

    Args:
        field_name: Name of the field
        field_def: Field definition from workflow YAML
        value: The submitted value to validate
        strict: If True, enforce strict type checking. If False, allow reasonable coercion.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Skip validation for None/empty values if field is not required
    if value is None or value == "":
        # Signatures are handled by special UI flow, never block here
        if field_def.get("type") == "signature" or "signature" in field_name.lower():
            return True, None
            
        if field_def.get("required", False):
            return False, f"Field '{field_name}' is required"
        return True, None

    expected_type = get_expected_value_type(field_def)
    actual_type = type(value).__name__

    # Type validation
    if expected_type == "string":
        if not isinstance(value, str):
            if strict:
                return False, f"Field '{field_name}' expected string, received {actual_type}"
            # Allow number to string coercion
            if isinstance(value, (int, float)):
                return True, None
            return False, f"Field '{field_name}' expected string, received {actual_type}"

    elif expected_type == "number":
        if not isinstance(value, (int, float)):
            if strict:
                return False, f"Field '{field_name}' expected number, received {actual_type}"
            # Allow string to number coercion if it's a valid number
            if isinstance(value, str) and value.replace('.', '', 1).replace('-', '', 1).isdigit():
                return True, None
            return False, f"Field '{field_name}' expected number, received {actual_type}"

    elif expected_type == "boolean":
        if not isinstance(value, bool):
            if strict:
                return False, f"Field '{field_name}' expected boolean, received {actual_type}"
            # Allow string/number to boolean coercion
            if value in [0, 1, "true", "false", "True", "False", "0", "1"]:
                return True, None
            return False, f"Field '{field_name}' expected boolean, received {actual_type}"

    elif expected_type == "object":
        if not isinstance(value, dict):
            return False, f"Field '{field_name}' expected object, received {actual_type}"

    elif expected_type == "array":
        if not isinstance(value, list):
            return False, f"Field '{field_name}' expected array, received {actual_type}"

    elif expected_type == "flexible":
        # Flexible type accepts both primitives (string, number) and objects
        # This is used for autocomplete fields with data_source
        # - If value_field is specified: stores primitive (string/number) → ${var}
        # - If value_field is omitted: stores object (dict) → ${var.key1.key2}
        if not isinstance(value, (str, int, float, dict)):
            return False, f"Field '{field_name}' expected string, number, or object, received {actual_type}"

    # If expected type is "any", accept anything

    return True, None


def validate_form_data(
    form_fields: List[Dict[str, Any]],
    form_data: Dict[str, Any],
    strict: bool = False
) -> Tuple[bool, List[str]]:
    """
    Validate submitted form data against workflow field definitions.

    Args:
        form_fields: List of field definitions from workflow YAML
        form_data: Submitted form data (field name -> value mapping)
        strict: If True, enforce strict type checking

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    # Create a map of field names to field definitions
    field_map = {field["name"]: field for field in form_fields if "name" in field}

    # Validate each submitted field
    for field_name, value in form_data.items():
        # Skip internal/system fields
        if field_name.startswith("_"):
            continue

        # Check if field is defined in workflow
        if field_name not in field_map:
            errors.append(f"Unknown field: '{field_name}'")
            continue

        field_def = field_map[field_name]
        is_valid, error_msg = validate_field_value(field_name, field_def, value, strict)

        if not is_valid and error_msg:
            errors.append(error_msg)

    # Check for required fields that are missing
    for field_name, field_def in field_map.items():
        # Skip signature fields - handled by special UI flow
        if field_def.get("type") == "signature" or "signature" in field_name.lower():
            continue
            
        if field_def.get("required", False) and field_name not in form_data:
            errors.append(f"Required field missing: '{field_name}'")

    return len(errors) == 0, errors


def get_autocomplete_example(store_mode: str = "object") -> str:
    """
    Get an example YAML snippet for autocomplete configuration.

    Args:
        store_mode: Either "object" or "id"

    Returns:
        YAML string with example configuration
    """
    if store_mode == "object":
        return """
# Autocomplete that stores full object
- name: employee
  type: autocomplete
  label: "Select Employee"
  options:
    data_source:
      source_id: "src_employees"
      object_path: "$.data.items"
      label_field: "name"
      display: "{name} ({email})"
      # No value_field = stores entire object
  search:
    min_length: 3
    debounce_ms: 300

# Submitted value will be an object:
# {
#   "id": 123,
#   "name": "John Doe",
#   "email": "john@example.com",
#   "department": "Engineering"
# }

# Reference in formulas:
# ${employee.name}
# ${employee.department}
# ${employee.email}
"""
    else:
        return """
# Autocomplete that stores only ID
- name: employee_id
  type: autocomplete
  label: "Select Employee"
  options:
    data_source:
      source_id: "src_employees"
      object_path: "$.data.items"
      value_field: "id"  # Extract and store only the ID
      label_field: "name"
      display: "{name} ({email})"
  search:
    min_length: 3
    debounce_ms: 300

# Submitted value will be a string/number:
# "123"

# Reference in formulas:
# ${employee_id}  → "123"
"""
