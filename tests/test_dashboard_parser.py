"""
Dashboard YAML parser regression tests.

Tests cover: the full worked example from lat.md/dashboards.md parsing end to end,
the kind: dashboard discriminator, exactly-one-of data_processor/source on tiles,
the columns-mode layout tile-id reference check (grid-mode is already covered by the
existing ApprovalProcess field-reference tests), the native asset join's source_id/
source_name exclusion, and line_chart's series requirement.

Run with: pytest tests/test_dashboard_parser.py -v
"""

import pytest
from approvalml.parser import Dashboard, DataSourceParameterMapping, parse_dashboard_yaml

# @lat: [[dashboards#YAML schema and parser#Full example parses]]
VALID_DASHBOARD = """
kind: dashboard
name: "Vendor Spend Overview"
description: "Quarterly vendor spend by region"

controls:
  - name: date_from
    type: date
  - name: timeframe
    type: date_range_preset
    options:
      - { label: "Last 30 Days", value: "last_30_days" }

tiles:
  - id: top_vendors
    type: table
    label: "Top Vendors"
    data_processor:
      source_name: "Vendor Spend SQL"
      params:
        - name: date_from
          from_control: date_from
      join:
        - field: vendor_id
          source_name: "Vendor Master"
          on: id
          pick: { vendor_name: name }
    row_path: "data"
    filter: "$not(vendor_tier='excluded')"
    columns:
      - { label: "Vendor", path: "vendor_name" }

  - id: server_baselines
    type: table
    source:
      type: asset
      category: server
    columns:
      - { label: "Name", path: "name" }

  - id: billing_with_tier
    type: table
    data_processor:
      source_name: "Billing Export SQL"
      join:
        - field: server_name
          source_type: asset
          category: server
          on: name
          pick: { tier: properties.tier }
    row_path: "data"
    columns:
      - { label: "X", path: "x" }

  - id: spend_by_region
    type: bar_chart
    data_processor:
      source_name: "Vendor Spend SQL"
    row_path: "data"
    x: "vendor.region.code"
    y: "totals.amount"
    agg: sum

  - id: total_spend
    type: stat
    template: kpi_badge
    data_processor:
      source_name: "Vendor Spend SQL"
    row_path: "data"
    settings:
      metric: "totals.amount"
      agg: sum

  - id: error_vs_delay
    type: scatter
    data_processor:
      source_name: "Audit Findings SQL"
    row_path: "data"
    x: "error_rate"
    y: "sla_delay_hours"
    size: "dollar_risk"
    point_label: "vendor_name"
    quadrants:
      x_threshold: 5.0
      y_threshold: 24
      labels:
        high_high: "Critical Process Failure"

  - id: approved_vs_rejected_trend
    type: line_chart
    data_processor:
      source_name: "Aptiwise Internal DB"
    row_path: "data"
    x: "day"
    series:
      - { label: "Approved", path: "approved" }
      - { label: "Rejected", path: "rejected" }

layout:
  sections:
    - id: overview
      title: "Overview"
      columns:
        - [ total_spend ]
        - [ top_vendors, spend_by_region ]
    - id: assets
      title: "Assets"
      columns:
        - [ server_baselines, billing_with_tier ]
    - id: other
      title: "Other"
      columns:
        - [ error_vs_delay, approved_vs_rejected_trend ]

subscriptions:
  - name: "Monday Morning Digest"
    schedule: "0 8 * * 1"
    recipients:
      - role: "finance_manager"
"""


# @lat: [[dashboards#YAML schema and parser#Full example parses]]
def test_full_example_parses():
    dashboard, summary = parse_dashboard_yaml(VALID_DASHBOARD)
    assert dashboard is not None, summary["errors"]
    assert summary["is_valid"] is True
    assert dashboard.kind == "dashboard"
    assert len(dashboard.tiles) == 7


# @lat: [[dashboards#YAML schema and parser#kind discriminator required]]
def test_missing_kind_is_rejected():
    bad = VALID_DASHBOARD.replace("kind: dashboard\n", "")
    dashboard, summary = parse_dashboard_yaml(bad)
    assert dashboard is None
    assert not summary["is_valid"]


# @lat: [[dashboards#YAML schema and parser#Columns-mode layout tile references are checked]]
def test_unknown_tile_id_in_columns_layout_is_rejected():
    bad = VALID_DASHBOARD.replace("- [ total_spend ]", "- [ nonexistent_tile ]")
    dashboard, summary = parse_dashboard_yaml(bad)
    assert dashboard is None
    assert "unknown tile" in summary["errors"][0]


# @lat: [[dashboards#YAML schema and parser#Tile requires exactly one of data_processor or source]]
def test_tile_with_both_data_processor_and_source_is_rejected():
    bad = VALID_DASHBOARD.replace(
        "    source:\n      type: asset\n      category: server\n",
        '    source:\n      type: asset\n      category: server\n'
        '    data_processor:\n      source_name: "X"\n',
    )
    dashboard, summary = parse_dashboard_yaml(bad)
    assert dashboard is None
    assert "exactly one of" in summary["errors"][0]


# @lat: [[dashboards#YAML schema and parser#line_chart requires at least one series]]
def test_line_chart_without_series_is_rejected():
    bad = VALID_DASHBOARD.replace(
        '    series:\n      - { label: "Approved", path: "approved" }\n'
        '      - { label: "Rejected", path: "rejected" }\n',
        "",
    )
    dashboard, summary = parse_dashboard_yaml(bad)
    assert dashboard is None
    assert "series" in summary["errors"][0]


# @lat: [[dashboards#Native asset source#Asset join rejects source_id and source_name]]
def test_asset_join_with_source_name_is_rejected():
    bad = VALID_DASHBOARD.replace(
        "          source_type: asset\n          category: server\n          on: name\n",
        "          source_type: asset\n          source_name: bad\n"
        "          category: server\n          on: name\n",
    )
    dashboard, summary = parse_dashboard_yaml(bad)
    assert dashboard is None
    assert "must not specify" in summary["errors"][0]


# @lat: [[dashboards#Row filtering#Native asset source has no row_path]]
def test_asset_source_tile_has_no_row_path_requirement():
    dashboard, summary = parse_dashboard_yaml(VALID_DASHBOARD)
    server_tile = next(t for t in dashboard.tiles if t.id == "server_baselines")
    assert server_tile.row_path is None
    assert server_tile.source.category == "server"


def test_from_control_is_a_valid_parameter_mapping_source():
    """The parser allows from_control generically (the model is shared with workflow steps);
    rejecting it for workflows specifically is the yaml_validator's job, not the parser's."""
    mapping = DataSourceParameterMapping(name="x", from_control="date_from")
    assert mapping.from_control == "date_from"


def test_parameter_mapping_rejects_multiple_sources():
    with pytest.raises(Exception):
        DataSourceParameterMapping(name="x", from_control="date_from", value="literal")
