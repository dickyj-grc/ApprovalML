"""
Dashboard YAML syntax reference for AI-powered dashboard generation.

Kept as its own module (not folded into syntax_reference.py, which is workflow-only)
because dashboards are a fully separate document type — see DashboardParser in
parser.py and docs-site/src/content/docs/admin/syntax/dashboard-syntax.md, the
human-facing reference this text is distilled from. See lat.md/dashboards.md.

The stat-template catalog is deliberately NOT hand-listed here — it's rendered at
call time from `describe_stat_templates()` (src/app/services/stat_templates/factory.py),
passed in by the caller, so a newly-registered template shows up automatically instead
of going stale the way a hardcoded list would (the same principle factory.py's own
docstring calls out for whichever syntax reference ends up documenting templates).
packages/approvalml intentionally has no dependency on src/app — the backend depends on
this package, not the reverse — so this module never imports stat_templates itself.
"""

from typing import Any, Dict, List, Optional

DASHBOARD_SYNTAX_REFERENCE = """
DASHBOARD YAML — CORE STRUCTURE

kind: dashboard                              # Required, literal "dashboard" — no default, unlike workflow's kind
name: "Vendor Spend Overview"
description: "Quarterly vendor spend by region"
view_roles: ["finance_manager", "admin"]     # Optional — company_roles allowed to view

controls: []                                 # Optional — filter widgets
tiles: []                                    # Required, at least one, unique ids
layout:                                      # Required — placement
  sections: []
subscriptions: []                            # Optional — scheduled email delivery (schema only, not yet executed)

CONTROLS — dashboard-level filter widgets. A tile's data_processor.params[] reads a
control's resolved value via `from_control: <name>`. controls[].name must be unique and
is the wire identifier from_control references — keep it a stable slug, never renamed once
tiles reference it. `label` is optional, human-facing display text shown next to the widget
in the viewer (falls back to `name` when omitted) — always set it for anything shown to end
users, since a raw slug like "date_from" is not a good filter label.

controls:
  - name: date_from
    label: "From"
    type: date
  - name: pillar
    label: "Pillar"
    type: select                              # static options, one value
    options:
      - { label: "Growth & Web", value: "growth" }
  - name: severity
    type: multi_select                        # static options, resolves to a list
    options:
      - { label: "High", value: "high" }
  - name: timeframe
    type: date_range_preset                   # resolves server-side into {name}_from / {name}_to
    options:
      - { label: "Last 30 Days", value: "last_30_days" }

date_range_preset known option values: last_7_days, last_30_days, this_month, last_month,
this_quarter, last_quarter, this_year. Any other value is a validation error. When applied,
it expands into two derived control values before tile params resolve: `{name}_from` and
`{name}_to` — target those with from_control, not the raw preset name, when a tile needs
concrete dates:
  data_processor:
    params:
      - name: date_from
        from_control: timeframe_from
      - name: date_to
        from_control: timeframe_to

select/multi_select/date_range_preset all REQUIRE a non-empty options list. `date` requires none.

DEFAULTS — controls[].default pre-fills a control before a tile ever executes. SET ONE on every
control any tile's `data_processor.params[]` reads via `from_control`, UNLESS the whole point is
forcing the viewer to choose before anything loads: a control with no default stays unset until
the viewer picks a value, and any tile that needs it is held back (not executed, not an error) —
but a REQUIRED connector param with no default and no viewer value yet is exactly the setup that
used to reach the connector broken, so default an unconditionally-required date/select control:
  - name: date_from
    type: date
    default: today                              # or a literal ISO date, e.g. "2026-01-01"
  - name: pillar
    type: select
    default: growth                              # must be one of this control's own options[].value
  - name: timeframe
    type: date_range_preset
    default: last_30_days                        # must be one of this control's own options[].value
multi_select accepts a YAML list as its default (each element must be one of options[].value).

TILES — every tile is one flat object discriminated by `type`. Each tile needs EXACTLY ONE
of `data_processor` or `source` — never both, never neither. `id` must be unique within the
dashboard and is what layout.sections[].grid/.columns reference.

Common fields (all tile types):
  id            Required, unique.
  type          Required — table | stat | bar_chart | scatter | line_chart.
  label         Optional display title.
  data_processor  The same DataSourceConfig shape workflow `automatic` steps use — source_id or
                  source_name, params[], join[]. Use for any connector-backed tile.
  source        `{ type: asset, category: <str> }` — native asset-registry tile (see below).
                  Exactly one of data_processor/source, not both.
  row_path      JSONata expression selecting the row array out of the raw response.
                  Required for data_processor tiles; NOT used (and must be omitted) for source: asset tiles.
                  The JSONata root context depends on the raw connector response shape: a BARE LIST
                  response is wrapped as {"data": <list>} — use `row_path: "data"` for those. A
                  response that is ALREADY a JSON object (e.g. {"records": [...]}) is exposed AS-IS as
                  the root — name the real key holding the row array (e.g. `row_path: "records"`), NOT
                  `"data"`. Either way, never use `$` as the row_path — for a table/line_chart building
                  the row array with an inline `$ {...}` group-by, this yields an EMPTY result, not an
                  error; for other tile types it silently gets wrapped as a single bogus one-element
                  row list. For an inline group-by expression, start from the correct root key followed
                  by `{...}` (e.g. `data {...}` or `records {...}`), never `$ {...}`.
  filter        Optional JSONata predicate over the whole extracted `rows` array, applied after
                  row extraction and join enrichment, before type-specific processing. Valid on every type.

### table
  columns: [{ label, path }]   # Required, non-empty. path is a per-row JSONata expression.
- id: top_vendors
  type: table
  data_processor: { source_name: "Vendor Spend SQL" }
  row_path: "data"
  columns:
    - { label: "Vendor", path: "vendor.name" }
    - { label: "Total Spend", path: "totals.amount" }

### stat
  template: <name>       # Required — must exist in the stat template registry (see STAT TEMPLATES below).
  settings: { ... }      # Required shape depends entirely on the chosen template's own schema —
                          # DashboardTile itself has no built-in knowledge of metric/format/etc.
- id: total_spend
  type: stat
  template: kpi_badge
  data_processor: { source_name: "Vendor Spend SQL" }
  row_path: "data"
  settings:
    layout: badge                                 # inline | badge | value_first | historical
    format: currency                              # number | currency | percent
    metric: "totals.amount"
    agg: sum                                       # shorthand: metric becomes a plain per-row field, reduced by agg
    compare_metric: "totals.prior_period_amount"   # optional, same row set, no second query
    compare_label: "vs last month"
    higher_is_better: true                         # default true

### bar_chart
  x, y required. x is per-row JSONata (the grouping key). y is a plain field aggregated by
  `agg:` (sum|avg|count|min|max) OR, when agg is omitted, a full JSONata expression evaluated
  PER x-GROUP against that bucket's own {"rows": [...]} context (note the `rows.` prefix then).
- id: spend_by_region
  type: bar_chart
  data_processor: { source_name: "Vendor Spend SQL" }
  row_path: "data"
  x: "vendor.region.code"
  y: "totals.amount"
  agg: sum
# or, per-group arithmetic (no agg:):
- id: net_spend_by_region
  type: bar_chart
  x: "vendor.region.code"
  y: "$sum(rows.totals.amount) - $sum(rows.totals.refund_amount)"

### scatter
  x, y required (both per-row JSONata). Unaggregated — every row is one point.
  size (optional, bubble radius), point_label (optional, per-point tooltip field — NOT `label`,
  which is always the tile's display title on every tile type). quadrants (optional):
  x_threshold/y_threshold plus labels.{high_high,high_x_low_y,low_x_high_y,low_low}.
- id: error_vs_delay
  type: scatter
  data_processor: { source_name: "Audit Findings SQL" }
  row_path: "data"
  x: "error_rate"
  y: "sla_delay_hours"
  size: "dollar_risk"
  point_label: "vendor_name"
  quadrants:
    x_threshold: 5.0
    y_threshold: 24
    labels: { high_high: "Critical Process Failure", low_low: "Healthy" }

### line_chart
  x required (per-row JSONata, shared across all series). series required, at least one entry,
  each `{ label, path }` where path is a plain per-row field off the SAME row x came from — no
  separate fetch, no re-grouping. A row missing a series field renders a gap in that line.
- id: approved_vs_rejected_trend
  type: line_chart
  data_processor: { source_name: "Aptiwise Internal DB" }
  row_path: "data"
  x: "day"
  series:
    - { label: "Approved", path: "approved" }
    - { label: "Rejected", path: "rejected" }

NATIVE ASSET SOURCE — company-scoped JSON asset records, no connector needed:
- id: server_baselines
  type: table
  source: { type: asset, category: server }   # replaces data_processor entirely
  filter: "properties.tier = 'production'"
  columns:
    - { label: "Name", path: "name" }
    - { label: "OS Version", path: "properties.os_version" }
source: {type: asset} tiles have NO row_path (result is already [{name, properties}]) and only
`category` filtering (no schema_id/schema_name). Visibility is scoped per-viewer, same as the
Assets UI itself.

DATA PROCESSOR PARAMETERS — data_processor.params[] reuses the workflow DataSourceParameterMapping
shape, plus one dashboard-only source. Each entry needs EXACTLY ONE of from_field, from_asset
(+ optional property), value, or from_control:
  data_processor:
    params:
      - name: date_from
        from_control: date_from     # dashboard-only — reads a control's resolved value
      - name: project_id
        from_field: field.project_id
      - name: cursor
        from_asset: sync-checkpoint
        property: $.last_cursor
      - name: api_version
        value: "v3"

CROSS-SOURCE JOINS — data_processor.join[] is the identical batch-fetch-then-lookup mechanism
workflow automatic steps use, extended with `source_type: asset` to join against the asset
registry instead of an external connector:
  data_processor:
    join:
      - field: server_name
        source_type: asset          # data_source (default) | asset
        category: server            # optional, narrows candidates — asset joins only
        on: name                    # match key on the joined records
        pick: { tier: properties.tier, owner: properties.owner_name }
Fields: field (required, FK on primary row), source_type, source_id/source_name (required unless
source_type: asset, and must be ABSENT when source_type: asset), category, on (default "id"),
pick (default "name"; string or {output: source_field} map), as (required if pick is a string),
param (default "ids"), separator (default ", "), as_array (default false).

field/on/pick are shallow dotted paths, NOT JSONata — 'properties.tier' walks into a nested dict,
and a purely-numeric segment indexes into a list, e.g. 'product_id.1' reads the display-name half
of an Odoo many2one's [id, name] tuple ('product_id.0' reads the id half). Picking a many2one
field WITHOUT an index (pick: product_id) returns the raw [id, name] pair stringified as one
value (e.g. "[2778, 'Widget']") — almost never what's wanted; index into it instead.

This '.1'/'.0' dot-index convention belongs to field/on/pick ONLY. Never carry it into an actual
JSONata expression (row_path, filter, x, y, columns[].path, series[].path, settings.metric/
compare_metric) — a digit can't follow '.' as a JSONata path step ("The literal value N cannot
be used as a step within a path expression"). Use bracket indexing there instead: product_id[1],
never product_id.1.

`pick: "$"` (or `{output: "$"}` inside a dict pick) attaches each matched record as-is, whole,
instead of extracting one field — use this when the tile needs every joined field, not a chosen
few:
  join:
    - field: order_line
      source_id: src_...
      on: id
      pick: { lines: "$" }
      as_array: true          # → lines: [{id, name, product_id, price_total, ...}, ...]

WITH as_array: true, picked values keep their original type from the source record — a numeric
field (e.g. price_total) stays a number, not a string, so downstream `$sum(rows.lines.price)`-
style arithmetic works without a cast. WITHOUT as_array (the default), multiple matches are
joined into one string via `separator`, which unavoidably stringifies each value first.

ROW FILTERING (filter:) — available on every tile type, JSONata predicate over the whole rows
array. `and`/`or` are native keyword operators; negation is the $not(...) FUNCTION, not a `not`
keyword — `rows[not x]` is a parse error, use `rows[$not(x)]`.

TOP-N / SLICING — the range operator (`..`) only parses as an ARRAY LITERAL, e.g. `[0..4]` on its
own. It is NOT a valid index predicate directly against an expression — `sorted[0..4]` is a parse
error ("Expected ], got .."), even though that form works in the standalone JSONata reference
implementation. Wrap the range in its own brackets instead: `sorted[[0..4]]` (double brackets) —
the inner `[0..4]` builds the index array, the outer `[...]` applies it. Common top-N pattern:
  rows ^(>amount) [[0..4]]     -> top 5 rows by amount, descending

COUNT / SUM / ARITHMETIC — stat.settings.metric/compare_metric and bar_chart.y (when agg: is
omitted) are evaluated as ONE JSONata expression against the WHOLE extracted row array as
{"rows": [...]}, not per row:
  $sum(rows.amount)                                        -> total
  $count(rows)                                              -> row count
  $average(rows.amount)                                     -> average
  $count(rows[status='error'])                               -> filtered count
  (1 - $count(rows[status='error']) / $count(rows)) * 100    -> ratio / health-score style
  rows{region: $sum(amount)}                                 -> group-by, {"US": 700, "EU": 900}
`agg: sum|avg|count|min|max` remains as optional shorthand for the common single-plain-field
case. Per-row context: table.columns[].path, scatter.x/y/size/point_label, bar_chart.x,
line_chart.x/series[].path. Whole-set context: stat.settings.metric/compare_metric, bar_chart.y
(only when agg: is absent).

LAYOUT — reuses the exact workflow form.layout.sections shape, pointing grid/columns cells at
tile ids instead of form field names. `columns` mode (independent vertical stacks) suits
dashboards particularly well since tiles are commonly mixed-height:
  layout:
    sections:
      - id: overview
        title: "Overview"
        columns:
          - [ total_spend ]
          - [ top_vendors, spend_by_region ]
Every tile id referenced by a section must exist in `tiles`; every tile should normally appear
in at least one section or it will never be visible.

SUBSCRIPTIONS (schema only — delivery not implemented yet, but the shape is validated):
  subscriptions:
    - name: "Monday Morning Digest"
      schedule: "0 8 * * 1"           # cron syntax, same as workflow triggers
      recipients:
        - role: "finance_manager"      # role | email, at least one entry required
      control_values:
        date_from: "2026-01-01"
"""


def get_dashboard_syntax_reference(stat_templates: Optional[List[Dict[str, Any]]] = None) -> str:
    """Get the complete Dashboard YAML syntax reference for AI generation.

    `stat_templates`, when given, is the output of stat_templates.factory.describe_stat_templates()
    — rendered into a STAT TILE TEMPLATES section so the registry never goes stale in the prompt.
    Passed in rather than imported here so this package keeps no dependency on src/app.
    """
    templates_section = _render_stat_templates_section(stat_templates)
    return DASHBOARD_SYNTAX_REFERENCE.strip() + "\n\n" + templates_section


def _render_stat_templates_section(stat_templates: Optional[List[Dict[str, Any]]]) -> str:
    if not stat_templates:
        return (
            "STAT TILE TEMPLATES\n"
            "  kpi_badge — settings: layout (inline|badge|value_first|historical, default inline), "
            "format (number|currency|percent, default number), metric (required, JSONata), "
            "agg (sum|avg|count|min|max, optional shorthand), compare_metric (optional), "
            "compare_label (optional), higher_is_better (default true)."
        )
    lines = ["STAT TILE TEMPLATES — a stat tile's `template:` must be one of these names, and its "
             "`settings:` must match that template's own schema:"]
    for tpl in stat_templates:
        name = tpl.get("name", "?")
        schema = tpl.get("settings_schema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        prop_lines = []
        for prop_name, prop_def in props.items():
            marker = "required" if prop_name in required else "optional"
            desc = prop_def.get("description") or prop_def.get("title") or ""
            prop_lines.append(f"      {prop_name} ({marker}): {desc}".rstrip())
        lines.append(f"  {name}:\n" + "\n".join(prop_lines))
    return "\n".join(lines)
