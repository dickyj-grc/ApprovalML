"""
Regression tests for WorkflowSafeLoader / safe_load_workflow_yaml.

PyYAML's default SafeLoader implements YAML 1.1, whose bool resolver also
matches yes/no/on/off/y/n (case-insensitive). An unquoted form field like
`label: yes` was silently parsed as Python bool True instead of the string
"yes", which later crashed the workflow view endpoint when that value was
fed into a Pydantic model expecting a string. safe_load_workflow_yaml
narrows the bool resolver to YAML 1.2 semantics (true/false only) to match
what Workflow Studio's own YAML parser (js-yaml v4, YAML 1.2 core schema)
already does, so backend and frontend agree on what a workflow YAML file means.

Run with: pytest tests/test_yaml_boolean_labels.py -v
"""

from approvalml import safe_load_workflow_yaml

# @lat: [[workflow-form#Form Field Types#YAML boolean-keyword labels]]
def test_ambiguous_bool_keywords_stay_strings():
    doc = """
form:
  fields:
    - name: f_yes
      type: text
      label: yes
    - name: f_no
      type: text
      label: no
    - name: f_on
      type: text
      label: on
    - name: f_off
      type: text
      label: off
"""
    data = safe_load_workflow_yaml(doc)
    labels = {f['name']: f['label'] for f in data['form']['fields']}
    assert labels == {'f_yes': 'yes', 'f_no': 'no', 'f_on': 'on', 'f_off': 'off'}
    assert all(isinstance(v, str) for v in labels.values())


# @lat: [[workflow-form#Form Field Types#YAML boolean-keyword labels]]
def test_true_false_keywords_still_parse_as_bool():
    doc = """
form:
  fields:
    - name: agree
      type: checkbox
      label: Active
      required: true
      default_value: false
"""
    data = safe_load_workflow_yaml(doc)
    field = data['form']['fields'][0]
    assert field['required'] is True
    assert field['default_value'] is False
    assert isinstance(field['required'], bool)
    assert isinstance(field['default_value'], bool)


# @lat: [[workflow-form#Form Field Types#YAML boolean-keyword labels]]
def test_quoted_bool_keyword_was_already_safe_and_remains_so():
    doc = """
form:
  fields:
    - name: f_quoted
      type: text
      label: "yes"
"""
    data = safe_load_workflow_yaml(doc)
    assert data['form']['fields'][0]['label'] == 'yes'
