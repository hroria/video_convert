from pathlib import Path
from html import escape
import pandas as pd
import re


def generate_catalog_html(df: pd.DataFrame, output_path: str | Path = "db_catalog.html"):
    """
    Render a polished HTML catalog for interactive schema exploration, with:

    - Global search across server / db / schema / table / column / data type text
    - Dynamic summary cards (Servers, Databases, Schemas, Tables, Columns)
    - Export CSV button: exports ALL columns for all currently visible (filtered) tables
    - Horizontal database row tabs instead of a vertical list
    - Quick filters: Server / Database / Schema (cascading, with counts)
    - Reset Filters ghost button (only affects filters, not search)
    - Clickable column names:
        * Clicking a column (e.g. customer_id) filters to all tables that contain that column
        * Column filter COMBINES with global search + other filters
        * Shows a removable "Column: customer_id" chip under the search bar
        * Each column cell has a tooltip: "Click to show all tables that contain this column"
    - "X of Y objects shown" line (tables + columns) under the search bar
    - Light/Dark theme toggle + server chips on table cards
    """

    # ---- Required cols ----
    required_cols = {"db_name", "schema_name", "table_name", "column_name", "data_type"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    # ServerName is expected but we'll handle safely if missing
    has_server = "ServerName" in df.columns
    has_max_length = "max_length" in df.columns
    has_ordinal = "ordinal_position" in df.columns

    # Sort for stable grouping / display
    sort_cols = []
    if has_server:
        sort_cols.append("ServerName")
    sort_cols.extend(["db_name", "schema_name", "table_name"])
    if has_ordinal:
        sort_cols.append("ordinal_position")
    sort_cols.append("column_name")

    df_sorted = df.sort_values(sort_cols).reset_index(drop=True)

    if df_sorted.empty:
        raise ValueError("The DataFrame is empty. Provide at least one row to render the catalog.")

    total_servers = df_sorted["ServerName"].nunique() if has_server else 0
    total_databases = df_sorted["db_name"].nunique()
    total_schemas = df_sorted[["db_name", "schema_name"]].drop_duplicates().shape[0]
    total_tables = df_sorted[["db_name", "schema_name", "table_name"]].drop_duplicates().shape[0]
    total_columns = len(df_sorted)

    def fmt_value(value) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def pluralize(total: int, label: str) -> str:
        suffix = "" if total == 1 else "s"
        return f"{total:,} {label}{suffix}"

    def make_safe_id(*parts: str) -> str:
        raw = "-".join(str(part) for part in parts if part is not None)
        safe = re.sub(r"[^0-9a-zA-Z]+", "-", raw)
        safe = safe.strip("-")
        return safe or "section"

    # Build nested structure: db -> schema -> table -> rows
    catalog: dict[str, dict[str, dict[str, list[pd.Series]]]] = {}
    db_order: list[str] = []

    for _, row in df_sorted.iterrows():
        db = row["db_name"]
        schema = row["schema_name"]
        table = row["table_name"]

        if db not in catalog:
            catalog[db] = {}
            db_order.append(db)

        if schema not in catalog[db]:
            catalog[db][schema] = {}

        if table not in catalog[db][schema]:
            catalog[db][schema][table] = []

        catalog[db][schema][table].append(row)

    # Summary cards with IDs for JS to update (now includes Servers)
    cards = []
    if has_server:
        cards.append(
            """
            <div class="summary-card shadow-sm">
              <div class="summary-label">Servers</div>
              <div class="summary-value" id="summary-servers" data-base-value="{total}">{total_fmt}</div>
            </div>
            """.format(
                total=total_servers,
                total_fmt=f"{total_servers:,}",
            ).strip()
        )
    cards.extend(
        [
            f"""
            <div class="summary-card shadow-sm">
              <div class="summary-label">Databases</div>
              <div class="summary-value" id="summary-databases" data-base-value="{total_databases}">{total_databases:,}</div>
            </div>
            """.strip(),
            f"""
            <div class="summary-card shadow-sm">
              <div class="summary-label">Schemas</div>
              <div class="summary-value" id="summary-schemas" data-base-value="{total_schemas}">{total_schemas:,}</div>
            </div>
            """.strip(),
            f"""
            <div class="summary-card shadow-sm">
              <div class="summary-label">Tables</div>
              <div class="summary-value" id="summary-tables" data-base-value="{total_tables}">{total_tables:,}</div>
            </div>
            """.strip(),
            f"""
            <div class="summary-card shadow-sm">
              <div class="summary-label">Columns</div>
              <div class="summary-value" id="summary-columns" data-base-value="{total_columns}">{total_columns:,}</div>
            </div>
            """.strip(),
        ]
    )
    summary_cards_html = "\n".join(cards)

    # Hero subtitle now includes servers if present
    if has_server:
        hero_subtitle = f"{pluralize(total_servers, 'server')} • {pluralize(total_tables, 'table')} • {pluralize(total_columns, 'column')}"
    else:
        hero_subtitle = f"{pluralize(total_tables, 'table')} • {pluralize(total_columns, 'column')}"

    # For DataTables default ordering
    ordinal_index = None  # index into visible columns
    if has_ordinal:
        ordinal_index = 2
        if has_max_length:
            ordinal_index += 1

    tabs_nav_html: list[str] = []
    tabs_content_html: list[str] = []

    for idx, db in enumerate(db_order):
        tab_id = f"tab-{idx}"
        active_class = "active" if idx == 0 else ""
        show_class = "show active" if idx == 0 else ""

        schema_count = len(catalog[db])
        table_count = sum(len(tables) for tables in catalog[db].values())
        column_count = sum(
            len(columns)
            for tables in catalog[db].values()
            for columns in tables.values()
        )

        tabs_nav_html.append(
            f"""
            <li class="nav-item" role="presentation">
              <button class="nav-link {active_class}" id="{tab_id}-tab"
                      data-bs-toggle="tab" data-bs-target="#{tab_id}"
                      type="button" role="tab" aria-controls="{tab_id}"
                      aria-selected="{'true' if idx == 0 else 'false'}"
                      data-db-name="{escape(str(db))}">
                <span class="db-pill-title">{escape(str(db))}</span>
                <span class="db-pill-meta">{pluralize(schema_count, 'schema')} • {pluralize(table_count, 'table')}</span>
                <span class="db-pill-columns">{pluralize(column_count, 'column')}</span>
              </button>
            </li>
            """
        )

        schema_sections: list[str] = []
        for schema, tables_dict in catalog[db].items():
            schema_id = make_safe_id(tab_id, schema)
            schema_table_count = len(tables_dict)
            schema_column_count = sum(len(columns) for columns in tables_dict.values())

            table_cards: list[str] = []
            for table_name, rows in tables_dict.items():
                table_slug = make_safe_id(schema_id, table_name)
                collapse_id = f"collapse-{table_slug}"
                table_html_id = f"table-{table_slug}"
                column_count = len(rows)

                # Get server name for this table (assume same for all rows)
                server_raw = rows[0].get("ServerName") if has_server else ""
                server_name = escape(fmt_value(server_raw))

                header_columns = [
                    '<th scope="col">Column</th>',
                    '<th scope="col">Data type</th>',
                ]
                if has_max_length:
                    header_columns.append('<th scope="col" class="text-end">Max length</th>')
                if has_ordinal:
                    header_columns.append('<th scope="col" class="text-end">Ordinal</th>')

                body_rows = []
                for row in rows:
                    raw_column = fmt_value(row.get("column_name"))
                    column_name = escape(raw_column)
                    dtype = escape(fmt_value(row.get("data_type")))
                    row_cells = [
                        (
                            "<td class='column-name-cell' "
                            "data-column-name=\"{col}\" "
                            "data-bs-toggle=\"tooltip\" "
                            "data-bs-placement=\"top\" "
                            "title=\"Click to show all tables that contain this column\">"
                            "<code>{col}</code></td>"
                        ).format(col=column_name),
                        f"<td><span class='dtype-pill'>{dtype}</span></td>",
                    ]
                    if has_max_length:
                        max_length = escape(fmt_value(row.get("max_length")))
                        row_cells.append(f"<td class='text-end'>{max_length}</td>")
                    if has_ordinal:
                        ordinal_value = escape(fmt_value(row.get("ordinal_position")))
                        row_cells.append(f"<td class='text-end'>{ordinal_value}</td>")

                    body_rows.append(f"<tr>{''.join(row_cells)}</tr>")

                ordinal_attr = f' data-ordinal-index="{ordinal_index}"' if ordinal_index is not None else ""

                server_chip_html = ""
                if has_server and server_name:
                    server_chip_html = f"<span class='server-pill'><i class='bi bi-hdd-network me-1'></i>{server_name}</span>"

                table_cards.append(
                    f"""
                    <div class="accordion-item table-item shadow-sm"
                         data-server-name="{server_name}"
                         data-db-name="{escape(str(db))}"
                         data-schema-name="{escape(str(schema))}"
                         data-table-name="{escape(str(table_name))}"
                         data-column-count="{column_count}">
                      <h2 class="accordion-header" id="heading-{table_slug}">
                        <button class="accordion-button collapsed table-toggle" type="button"
                                data-bs-toggle="collapse" data-bs-target="#{collapse_id}"
                                aria-expanded="false" aria-controls="{collapse_id}">
                          <div class="w-100 d-flex flex-column flex-sm-row justify-content-between align-items-sm-center gap-2">
                            <div>
                              <p class="mini-label">Table</p>
                              <h5 class="mb-1">{escape(str(table_name))}</h5>
                              <div class="d-flex flex-wrap gap-2 align-items-center mt-1">
                                <div class="stat-pill">{pluralize(len(rows), 'column')}</div>
                                {server_chip_html}
                              </div>
                            </div>
                          </div>
                        </button>
                      </h2>
                      <div id="{collapse_id}" class="accordion-collapse collapse columns-collapse"
                           aria-labelledby="heading-{table_slug}" data-bs-parent="#tables-{schema_id}">
                        <div class="accordion-body">
                          <table class="table table-sm table-striped table-hover align-middle column-table"
                                 id="{table_html_id}"{ordinal_attr}>
                            <thead>
                              <tr>
                                {''.join(header_columns)}
                              </tr>
                            </thead>
                            <tbody>
                              {''.join(body_rows)}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                    """
                )

            schema_sections.append(
                f"""
                <div class="schema-accordion accordion mb-4" id="accordion-{schema_id}">
                  <div class="accordion-item shadow-sm">
                    <h2 class="accordion-header" id="heading-{schema_id}">
                      <button class="accordion-button collapsed" type="button"
                              data-bs-toggle="collapse" data-bs-target="#schema-{schema_id}"
                              aria-expanded="false" aria-controls="schema-{schema_id}">
                        <div>
                          <p class="schema-label text-uppercase">Schema</p>
                          <h4 class="mb-0">{escape(str(schema))}</h4>
                        </div>
                        <div class="schema-meta text-muted">
                          <span>{pluralize(schema_table_count, 'table')}</span>
                          <span class="mx-2">•</span>
                          <span>{pluralize(schema_column_count, 'column')}</span>
                        </div>
                      </button>
                    </h2>
                    <div id="schema-{schema_id}" class="accordion-collapse collapse"
                         aria-labelledby="heading-{schema_id}" data-bs-parent="#accordion-{schema_id}">
                      <div class="accordion-body">
                        <div class="accordion table-accordion" id="tables-{schema_id}">
                          {''.join(table_cards)}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                """
            )

        tabs_content_html.append(
            f"""
            <div class="tab-pane fade {show_class}" id="{tab_id}" role="tabpanel"
                 aria-labelledby="{tab_id}-tab">
              {''.join(schema_sections)}
            </div>
            """
        )

    # Quick filter bar HTML (server filter conditional) with count pills + Reset button
    server_filter_html = ""
    if has_server:
        server_filter_html = """
          <div class="filter-group" id="serverFilterGroup">
            <label class="form-label mb-1">Server
              <span id="serverFilterCount" class="filter-count-pill">0</span>
            </label>
            <select id="serverFilter" class="form-select form-select-sm">
              <option value="all">All servers</option>
            </select>
          </div>
        """

    filter_bar_html = f"""
      <div class="filter-bar">
        {server_filter_html}
        <div class="filter-group">
          <label class="form-label mb-1">Database
            <span id="dbFilterCount" class="filter-count-pill">0</span>
          </label>
          <select id="dbFilter" class="form-select form-select-sm">
            <option value="all">All databases</option>
          </select>
        </div>
        <div class="filter-group">
          <label class="form-label mb-1">Schema
            <span id="schemaFilterCount" class="filter-count-pill">0</span>
          </label>
          <select id="schemaFilter" class="form-select form-select-sm">
            <option value="all">All schemas</option>
          </select>
        </div>
        <div class="ms-auto">
          <button id="resetFiltersBtn" type="button" class="reset-filters-btn">
            <i class="bi bi-arrow-counterclockwise me-1"></i>Reset filters
          </button>
        </div>
      </div>
    """

    full_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Database Catalog</title>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">

  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/dataTables.bootstrap5.min.css">
  <link rel="stylesheet" href="https://cdn.datatables.net/responsive/2.5.0/css/responsive.bootstrap5.min.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">

  <style>
    :root {{
      --brand: #4f46e5;
      --brand-dark: #312e81;
      --brand-soft: #eef2ff;

      --bg: #f8fafc;
      --bg-soft: #f1f5f9;
      --surface: #ffffff;
      --border: #e2e8f0;

      --text: #0f172a;
      --text-muted: #64748b;

      scroll-behavior: smooth;
    }}

    body {{
      font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 2rem;
      transition: background 0.2s ease, color 0.2s ease;
    }}

    html, body {{
      height: auto;
    }}

    body.dark-theme {{
      --bg: #020617;
      --bg-soft: #020617;
      --surface: #020617;
      --border: #1f2937;

      --text: #f9fafb;
      --text-muted: #9ca3af;
      --brand-soft: rgba(79, 70, 229, 0.2);
    }}

    .hero-section {{
      background: radial-gradient(circle at top left, #6366f1, #312e81);
      border-radius: 24px;
      padding: 2.75rem;
      color: #fff;
      position: relative;
      overflow: hidden;
      box-shadow: 0 30px 60px rgba(99, 102, 241, 0.35);
    }}

    body.dark-theme .hero-section {{
      box-shadow: 0 30px 80px rgba(0, 0, 0, 0.8);
    }}

    .hero-section::after {{
      content: '';
      position: absolute;
      width: 220px;
      height: 220px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      right: -40px;
      top: -40px;
    }}

    .hero-eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.2em;
      font-size: 0.75rem;
      opacity: 0.7;
    }}

    .theme-toggle {{
      background: rgba(248, 250, 252, 0.9);
      border-radius: 999px;
      border: none;
      padding: 0.4rem 0.8rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 25px rgba(15, 23, 42, 0.35);
      color: #111827;
      transition: transform 0.13s ease, box-shadow 0.13s ease, background 0.13s ease;
    }}

    .theme-toggle:hover {{
      transform: translateY(-1px);
      box-shadow: 0 14px 32px rgba(15, 23, 42, 0.5);
    }}

    body.dark-theme .theme-toggle {{
      background: rgba(15, 23, 42, 0.95);
      color: #e5e7eb;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.85);
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 1rem;
      margin-top: 1.5rem;
    }}

    .summary-card {{
      background: var(--surface);
      border-radius: 18px;
      padding: 1.25rem 1.5rem;
      border: 1px solid rgba(255, 255, 255, 0.4);
      position: relative;
      overflow: hidden;
    }}

    .summary-card::after {{
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at top right, rgba(79, 70, 229, 0.12), transparent);
      opacity: 0.9;
      pointer-events: none;
    }}

    body.dark-theme .summary-card {{
      border-color: rgba(148, 163, 184, 0.45);
      box-shadow: 0 12px 26px rgba(0, 0, 0, 0.8);
    }}

    .summary-label {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--text-muted);
      margin-bottom: 0.35rem;
    }}

    .summary-value {{
      font-size: 1.8rem;
      font-weight: 700;
      color: var(--text);
    }}

    .global-search {{
      display: flex;
      gap: 0.75rem;
      align-items: center;
      margin-top: 1.75rem;
      flex-wrap: wrap;
    }}

    .global-search-input-wrapper {{
      position: relative;
      flex: 1;
      min-width: 260px;
    }}

    .global-search input {{
      border-radius: 999px;
      padding: 0.9rem 3rem 0.9rem 2.5rem;
      font-size: 1.02rem;
      border: 2px solid var(--border);
      background: var(--surface);
      color: var(--text);
      width: 100%;
      box-shadow: 0 10px 25px rgba(15, 23, 42, 0.04);
      transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
    }}

    .global-search input:focus {{
      border-color: var(--brand);
      box-shadow: 0 0 0 0.2rem rgba(79, 70, 229, 0.2);
      outline: none;
    }}

    .search-icon {{
      position: absolute;
      left: 0.9rem;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 1.1rem;
    }}

    .clear-search-btn {{
      position: absolute;
      right: 0.8rem;
      top: 50%;
      transform: translateY(-50%);
      border: none;
      background: transparent;
      color: var(--text-muted);
      font-size: 1.1rem;
      display: none;
      padding: 0;
    }}

    .clear-search-btn.visible {{
      display: inline-flex;
    }}

    .catalog-wrapper {{
      margin-top: 2.5rem;
    }}

    .catalog-header {{
      margin-bottom: 0.75rem;
    }}

    .catalog-header h2 {{
      font-weight: 600;
      color: var(--text);
    }}

    .catalog-header p {{
      color: var(--text-muted);
    }}

    .search-status-badge {{
      font-size: 0.8rem;
      padding: 0.35rem 0.7rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text-muted);
      white-space: nowrap;
    }}

    .results-overview {{
      margin-top: 0.4rem;
    }}

    .results-overview-text {{
      font-size: 0.8rem;
      color: var(--text-muted);
    }}

    .filter-chips {{
      margin-top: 0.35rem;
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    .filter-chip {{
      border: none;
      background: rgba(79, 70, 229, 0.08);
      color: var(--brand-dark);
      font-size: 0.78rem;
      border-radius: 999px;
      padding: 0.22rem 0.7rem;
      display: none;
      align-items: center;
      gap: 0.4rem;
      cursor: pointer;
    }}

    .filter-chip.visible {{
      display: inline-flex;
    }}

    body.dark-theme .filter-chip {{
      background: rgba(79, 70, 229, 0.3);
      color: #e5e7eb;
    }}

    .chip-label {{
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
    }}

    .chip-close {{
      font-size: 0.9rem;
      line-height: 1;
      opacity: 0.8;
    }}

    .chip-close:hover {{
      opacity: 1;
    }}

    .filter-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: flex-end;
      margin-bottom: 0.6rem;
      margin-top: 0.75rem;
    }}

    .filter-group {{
      min-width: 160px;
    }}

    .filter-group label {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--text-muted);
    }}

    .filter-group select {{
      border-radius: 999px;
      padding: 0.45rem 0.9rem;
      font-size: 0.85rem;
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
    }}

    .filter-count-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-left: 0.3rem;
      padding: 0.1rem 0.4rem;
      border-radius: 999px;
      font-size: 0.65rem;
      background: rgba(148, 163, 184, 0.15);
      color: var(--text-muted);
    }}

    .reset-filters-btn {{
      border: none;
      background: transparent;
      font-size: 0.8rem;
      color: var(--text-muted);
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      display: none;
      align-items: center;
      gap: 0.25rem;
      cursor: pointer;
      transition: background 0.15s ease, color 0.15s ease;
    }}

    .reset-filters-btn.visible {{
      display: inline-flex;
    }}

    .reset-filters-btn:hover {{
      background: rgba(148, 163, 184, 0.12);
      color: var(--text);
    }}

    .db-layout {{
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }}

    .db-tabs-wrapper {{
      position: sticky;
      top: 0.75rem;
      z-index: 20;
      padding: 0.5rem 0 0.35rem;
      background: linear-gradient(to bottom, rgba(248, 250, 252, 0.95), rgba(248, 250, 252, 0.9));
      backdrop-filter: blur(6px);
      border-bottom: 1px solid rgba(148, 163, 184, 0.25);
    }}

    body.dark-theme .db-tabs-wrapper {{
      background: linear-gradient(to bottom, rgba(15, 23, 42, 0.97), rgba(15, 23, 42, 0.94));
      border-bottom-color: rgba(30, 64, 175, 0.7);
    }}

    .db-tabs {{
      display: flex;
      flex-wrap: nowrap;
      overflow-x: auto;
      gap: 0.75rem;
      padding-bottom: 0.35rem;
      margin-bottom: 0;
      scrollbar-width: thin;
      scrollbar-color: rgba(148, 163, 184, 0.6) transparent;
    }}

    .db-tabs::-webkit-scrollbar {{
      height: 6px;
    }}

    .db-tabs::-webkit-scrollbar-track {{
      background: transparent;
    }}

    .db-tabs::-webkit-scrollbar-thumb {{
      background: rgba(148, 163, 184, 0.6);
      border-radius: 999px;
    }}

    .db-tabs .nav-item {{
      flex: 0 0 auto;
      min-width: 210px;
      max-width: 260px;
    }}

    .db-tabs .nav-link {{
      background: var(--surface);
      border-radius: 1rem;
      border: 1px solid transparent;
      padding: 0.85rem 1.05rem;
      color: var(--text);
      text-align: left;
      box-shadow: 0 10px 25px rgba(15, 23, 42, 0.08);
      transition: all 0.18s ease;
      display: flex;
      flex-direction: column;
      gap: 0.15rem;
    }}

    .db-tabs .nav-link:not(.active):hover {{
      border-color: rgba(79, 70, 229, 0.22);
      transform: translateY(-2px);
      box-shadow: 0 12px 28px rgba(148, 163, 184, 0.45);
    }}

    .db-tabs .nav-link.active {{
      background: radial-gradient(circle at top left, #818cf8, #4f46e5);
      color: #fff;
      box-shadow: 0 18px 38px rgba(49, 46, 129, 0.5);
    }}

    .db-pill-title {{
      display: block;
      font-weight: 600;
      font-size: 0.98rem;
      text-overflow: ellipsis;
      white-space: nowrap;
      overflow: hidden;
    }}

    .db-pill-meta,
    .db-pill-columns {{
      display: block;
      font-size: 0.8rem;
      opacity: 0.9;
    }}

    .db-pill-columns {{
      font-weight: 500;
    }}

    .schema-accordion .accordion-button {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      background: var(--surface);
      border-left: 5px solid var(--brand);
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
      color: var(--text);
      transition: transform 0.12s ease, box-shadow 0.12s ease;
    }}

    .schema-accordion .accordion-button:not(.collapsed) {{
      transform: translateY(-1px);
      box-shadow: 0 16px 32px rgba(15, 23, 42, 0.15);
    }}

    .schema-label {{
      font-size: 0.75rem;
      letter-spacing: 0.2em;
      color: var(--text-muted);
      margin-bottom: 0.25rem;
    }}

    .schema-meta {{
      font-weight: 500;
      font-size: 0.9rem;
      color: var(--text-muted);
    }}

    .table-accordion {{
      --bs-accordion-border-color: transparent;
      --bs-accordion-btn-focus-border-color: transparent;
      --bs-accordion-btn-focus-box-shadow: none;
      --bs-accordion-bg: var(--surface);
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}

    .table-item {{
      border: 1px solid var(--border);
      border-left: 4px solid var(--brand);
      border-radius: 16px;
      overflow: hidden;
      background: var(--surface);
      transition: box-shadow 0.14s ease, transform 0.14s ease, border-color 0.14s ease;
    }}

    .table-item.search-match {{
      border-color: rgba(79, 70, 229, 0.9);
      box-shadow: 0 14px 32px rgba(79, 70, 229, 0.35);
      transform: translateY(-1px);
    }}

    .table-toggle {{
      align-items: center;
      gap: 0.75rem;
    }}

    .table-toggle .mini-label {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.15em;
      color: var(--text-muted);
      margin-bottom: 0.35rem;
    }}

    .table-toggle:not(.collapsed) {{
      background: var(--brand-soft);
      color: var(--text);
      box-shadow: inset 0 -1px 0 rgba(15, 23, 42, 0.08);
    }}

    .table-item .accordion-body {{
      background: var(--bg-soft);
    }}

    .stat-pill {{
      display: inline-flex;
      align-items: center;
      padding: 0.35rem 0.75rem;
      border-radius: 999px;
      background: var(--brand-soft);
      color: var(--brand-dark);
      font-size: 0.85rem;
      font-weight: 600;
    }}

    .server-pill {{
      display: inline-flex;
      align-items: center;
      padding: 0.3rem 0.7rem;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.05);
      font-size: 0.82rem;
      color: var(--text-muted);
    }}

    body.dark-theme .server-pill {{
      background: rgba(15, 23, 42, 0.65);
      color: #e5e7eb;
    }}

    .columns-collapse {{
      background: var(--bg-soft);
      border-radius: 14px;
      padding: 1rem;
      border: 1px dashed rgba(15, 23, 42, 0.08);
    }}

    .column-table {{
      color: var(--text);
    }}

    .column-name-cell {{
      cursor: pointer;
    }}

    .column-name-cell:hover code {{
      background: rgba(79, 70, 229, 0.12);
    }}

    .column-table code {{
      background: rgba(99, 102, 241, 0.08);
      padding: 0.15rem 0.4rem;
      border-radius: 0.35rem;
      font-size: 0.85rem;
      color: var(--text);
      transition: background 0.1s ease;
    }}

    body.dark-theme .column-table code {{
      background: rgba(79, 70, 229, 0.35);
    }}

    .dtype-pill {{
      padding: 0.2rem 0.55rem;
      border-radius: 0.5rem;
      background: rgba(15, 23, 42, 0.05);
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--text);
    }}

    body.dark-theme .dtype-pill {{
      background: rgba(148, 163, 184, 0.25);
    }}

    .dataTables_wrapper .dataTables_filter input {{
      border-radius: 999px;
      padding: 0.35rem 1rem;
      border: 1px solid var(--border);
      box-shadow: none;
      background: var(--surface);
      color: var(--text);
    }}

    .dataTables_wrapper .dataTables_filter label {{
      font-weight: 500;
      color: var(--text);
    }}

    @media (max-width: 767px) {{
      body {{
        padding: 1.25rem;
      }}
      .hero-section {{
        padding: 2rem;
      }}
      .global-search {{
        flex-direction: column;
        align-items: stretch;
      }}
      .search-status-badge {{
        margin-top: 0.5rem;
      }}
      .db-tabs .nav-item {{
        min-width: 180px;
      }}
    }}
  </style>
</head>
<body>
<div class="container-fluid p-0">
  <header class="hero-section">
    <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">
      <div>
        <p class="hero-eyebrow mb-2">Schema Explorer</p>
        <h1 class="display-5 fw-semibold mb-2">Database Table Catalog</h1>
        <p class="lead mb-0">{hero_subtitle}</p>
      </div>
      <button id="themeToggle" type="button"
              class="btn btn-sm theme-toggle"
              aria-label="Toggle dark mode">
        <i class="bi bi-moon-stars"></i>
      </button>
    </div>
  </header>

  <section class="summary-grid">
    {summary_cards_html}
  </section>

  <section class="global-search">
    <div class="global-search-input-wrapper">
      <span class="search-icon">
        <i class="bi bi-search"></i>
      </span>
      <input id="globalSearchInput" type="text" class="form-control form-control-lg"
             placeholder="Global search… (server, database, schema, table, columns, data types)">
      <button id="clearSearchBtn" class="clear-search-btn" type="button" aria-label="Clear search">
        <i class="bi bi-x-circle-fill"></i>
      </button>
    </div>
    <button id="exportCsvBtn" class="btn btn-outline-secondary btn-lg">
      <i class="bi bi-download me-1"></i>
      Export CSV
    </button>
  </section>

  <section class="filter-chips">
    <button id="activeColumnChip" type="button" class="filter-chip" aria-label="Remove column filter">
      <span class="chip-label"></span>
      <span class="chip-close" aria-hidden="true">&times;</span>
    </button>
  </section>

  <section class="results-overview">
    <p id="resultsOverview" class="results-overview-text mb-0">
      <!-- JS will populate -->
    </p>
  </section>

  <section class="catalog-wrapper">
    <div class="db-layout">
      <div class="d-flex justify-content-between align-items-center catalog-header flex-wrap gap-2">
        <div>
          <h2 class="h5 mb-1">Databases</h2>
          <p class="small mb-0">Use quick filters or tap a database pill below to explore its schemas, tables, and columns.</p>
        </div>
        <span id="searchStatusBadge" class="search-status-badge">
          Showing all objects
        </span>
      </div>

      {filter_bar_html}

      <div class="db-tabs-wrapper">
        <ul class="nav nav-pills db-tabs" id="dbTabs" role="tablist">
          {''.join(tabs_nav_html)}
        </ul>
      </div>

      <div class="tab-content flex-grow-1 pt-2" id="dbTabsContent">
        {''.join(tabs_content_html)}
      </div>
    </div>
  </section>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/dataTables.bootstrap5.min.js"></script>
<script src="https://cdn.datatables.net/responsive/2.5.0/js/responsive.min.js"></script>
<script src="https://cdn.datatables.net/responsive/2.5.0/js/responsive.bootstrap5.min.js"></script>

<script>
  document.addEventListener('DOMContentLoaded', function () {{
    const initializedTables = {{}};

    // ---------- THEME TOGGLE ----------
    const bodyEl = document.body;
    const themeToggle = document.getElementById('themeToggle');
    const THEME_KEY = 'catalog-theme';

    function applyTheme(theme) {{
      const isDark = theme === 'dark';

      if (isDark) {{
        bodyEl.classList.add('dark-theme');
      }} else {{
        bodyEl.classList.remove('dark-theme');
      }}

      if (themeToggle) {{
        themeToggle.innerHTML = isDark
          ? '<i class="bi bi-sun"></i>'
          : '<i class="bi bi-moon-stars"></i>';
        themeToggle.setAttribute(
          'aria-label',
          isDark ? 'Switch to light theme' : 'Switch to dark theme'
        );
      }}
    }}

    function getInitialTheme() {{
      try {{
        const stored = window.localStorage.getItem(THEME_KEY);
        if (stored === 'light' || stored === 'dark') {{
          return stored;
        }}
      }} catch (e) {{}}

      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {{
        return 'dark';
      }}
      return 'light';
    }}

    const initialTheme = getInitialTheme();
    applyTheme(initialTheme);

    if (themeToggle) {{
      themeToggle.addEventListener('click', function () {{
        const isDark = bodyEl.classList.contains('dark-theme');
        const next = isDark ? 'light' : 'dark';
        applyTheme(next);
        try {{
          window.localStorage.setItem(THEME_KEY, next);
        }} catch (e) {{}}
      }});
    }}

    // ---------- Bootstrap tooltips for column cells ----------
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (tooltipTriggerEl) {{
      new bootstrap.Tooltip(tooltipTriggerEl);
    }});

    // ---------- DataTables lazy init ----------
    $(document).on('shown.bs.collapse', '.columns-collapse', function () {{
      const $table = $(this).find('table.column-table').first();
      const tableId = $table.attr('id');

      if (!tableId || initializedTables[tableId]) {{
        return;
      }}

      const ordinalIndex = $table.data('ordinal-index');

      $table.DataTable({{
        paging: false,
        info: false,
        responsive: true,
        order: ordinalIndex !== undefined ? [[ordinalIndex, 'asc']] : [[0, 'asc']],
        columnDefs: ordinalIndex !== undefined ? [{{ targets: ordinalIndex, type: 'num' }}] : [],
        language: {{
          search: '',
          searchPlaceholder: 'Search columns...'
        }}
      }});

      initializedTables[tableId] = true;
    }});

    // ---------- GLOBAL SEARCH + FILTERS + COLUMN FILTER + SUMMARY + EXPORT ----------
    const globalInput = document.getElementById('globalSearchInput');
    const exportBtn = document.getElementById('exportCsvBtn');
    const clearBtn = document.getElementById('clearSearchBtn');
    const searchStatusBadge = document.getElementById('searchStatusBadge');
    const resultsOverviewEl = document.getElementById('resultsOverview');

    const summaryServersEl = document.getElementById('summary-servers');
    const summaryDbsEl = document.getElementById('summary-databases');
    const summarySchemasEl = document.getElementById('summary-schemas');
    const summaryTablesEl = document.getElementById('summary-tables');
    const summaryColumnsEl = document.getElementById('summary-columns');

    const serverFilter = document.getElementById('serverFilter');
    const dbFilter = document.getElementById('dbFilter');
    const schemaFilter = document.getElementById('schemaFilter');

    const serverCountEl = document.getElementById('serverFilterCount');
    const dbCountEl = document.getElementById('dbFilterCount');
    const schemaCountEl = document.getElementById('schemaFilterCount');

    const resetFiltersBtn = document.getElementById('resetFiltersBtn');

    const activeColumnChip = document.getElementById('activeColumnChip');
    const activeColumnChipLabel = activeColumnChip ? activeColumnChip.querySelector('.chip-label') : null;

    let columnFilter = null;         // lowercase column name
    let columnFilterLabel = '';      // original label

    const baseSummary = {{
      servers: summaryServersEl ? Number(summaryServersEl.dataset.baseValue || '0') : 0,
      databases: summaryDbsEl ? Number(summaryDbsEl.dataset.baseValue || '0') : 0,
      schemas: summarySchemasEl ? Number(summarySchemasEl.dataset.baseValue || '0') : 0,
      tables: summaryTablesEl ? Number(summaryTablesEl.dataset.baseValue || '0') : 0,
      columns: summaryColumnsEl ? Number(summaryColumnsEl.dataset.baseValue || '0') : 0
    }};

    function setSummary(servers, dbs, schemas, tables, cols) {{
      if (summaryServersEl) summaryServersEl.textContent = servers.toLocaleString();
      if (summaryDbsEl) summaryDbsEl.textContent = dbs.toLocaleString();
      if (summarySchemasEl) summarySchemasEl.textContent = schemas.toLocaleString();
      if (summaryTablesEl) summaryTablesEl.textContent = tables.toLocaleString();
      if (summaryColumnsEl) summaryColumnsEl.textContent = cols.toLocaleString();
    }}

    function setSearchStatus(text) {{
      if (!searchStatusBadge) return;
      searchStatusBadge.textContent = text;
    }}

    function updateResultsOverview(visibleTables, visibleColumns) {{
      if (!resultsOverviewEl) return;
      const totalTables = baseSummary.tables;
      const totalColumns = baseSummary.columns;

      if (visibleTables === totalTables && visibleColumns === totalColumns) {{
        resultsOverviewEl.textContent =
          'Showing all ' + visibleTables.toLocaleString() + ' tables (' +
          visibleColumns.toLocaleString() + ' columns)';
      }} else {{
        resultsOverviewEl.textContent =
          'Showing ' + visibleTables.toLocaleString() + ' of ' + totalTables.toLocaleString() +
          ' tables (' + visibleColumns.toLocaleString() + ' of ' + totalColumns.toLocaleString() +
          ' columns)';
      }}
    }}

    const searchEntries = [];
    const serverOptionMap = new Map(); // lower -> label
    const dbOptionMap = new Map();
    const schemaOptionMap = new Map();
    const rowCombos = []; // for cascading relationships

    document.querySelectorAll('.table-item').forEach(tableCard => {{
      const schemaAcc = tableCard.closest('.schema-accordion');
      const tabPane = tableCard.closest('.tab-pane');

      const serverLabel = tableCard.dataset.serverName || '';
      const dbLabel = tableCard.dataset.dbName || '';
      const schemaLabel = tableCard.dataset.schemaName || '';
      const tableLabel = tableCard.dataset.tableName || '';

      const serverName = (serverLabel || '').toLowerCase();
      const dbName = (dbLabel || '').toLowerCase();
      const schemaName = (schemaLabel || '').toLowerCase();
      const tableName = (tableLabel || '').toLowerCase();
      const columnCount = Number(tableCard.dataset.columnCount || '0');

      const tableBodyText = tableCard.innerText.toLowerCase();
      const fullText = serverName + ' ' + dbName + ' ' + schemaName + ' ' + tableName + ' ' + tableBodyText;

      const columnsCollapse = tableCard.querySelector('.columns-collapse');

      // Collect column names for this table (for columnFilter)
      const columnNamesSet = new Set();
      tableCard.querySelectorAll('tbody tr').forEach(tr => {{
        const firstTd = tr.querySelector('td');
        if (!firstTd) return;
        const name = (firstTd.innerText || '').trim().toLowerCase();
        if (name) columnNamesSet.add(name);
      }});
      const columnNames = Array.from(columnNamesSet);

      searchEntries.push({{
        tableCard,
        schemaAcc,
        tabPane,
        columnsCollapse,
        fullText,
        serverName,
        dbName,
        schemaName,
        tableName,
        columnCount,
        columnNames
      }});

      if (serverLabel) {{
        serverOptionMap.set(serverName, serverLabel);
      }}
      if (dbLabel) {{
        dbOptionMap.set(dbName, dbLabel);
      }}
      if (schemaLabel) {{
        schemaOptionMap.set(schemaName, schemaLabel);
      }}

      rowCombos.push({{
        serverName,
        dbName,
        schemaName,
        serverLabel,
        dbLabel,
        schemaLabel
      }});
    }});

    function resetSelectKeepAll(selectEl) {{
      if (!selectEl) return;
      while (selectEl.options.length > 1) {{
        selectEl.remove(1);
      }}
    }}

    function setOptionsFromMap(selectEl, allowedMap, selectedValue) {{
      if (!selectEl) return;
      resetSelectKeepAll(selectEl);

      const entries = Array.from(allowedMap.entries()).sort((a, b) => {{
        const labelA = a[1] || '';
        const labelB = b[1] || '';
        return labelA.localeCompare(labelB);
      }});

      for (const [val, label] of entries) {{
        const opt = document.createElement('option');
        opt.value = val || '';
        opt.textContent = label;
        selectEl.appendChild(opt);
      }}

      if (selectedValue && selectedValue !== 'all' && allowedMap.has(selectedValue)) {{
        selectEl.value = selectedValue;
      }} else {{
        selectEl.value = 'all';
      }}
    }}

    function updateResetFiltersVisibility() {{
      const serverSel = serverFilter ? (serverFilter.value || 'all').toLowerCase() : 'all';
      const dbSel = dbFilter ? (dbFilter.value || 'all').toLowerCase() : 'all';
      const schemaSel = schemaFilter ? (schemaFilter.value || 'all').toLowerCase() : 'all';

      const anyActive =
        (serverFilter && serverSel !== 'all') ||
        (dbFilter && dbSel !== 'all') ||
        (schemaFilter && schemaSel !== 'all');

      if (resetFiltersBtn) {{
        if (anyActive) {{
          resetFiltersBtn.classList.add('visible');
        }} else {{
          resetFiltersBtn.classList.remove('visible');
        }}
      }}
    }}

    function updateFilterOptions() {{
      const serverSel = serverFilter ? (serverFilter.value || 'all').toLowerCase() : 'all';
      const dbSel = dbFilter ? (dbFilter.value || 'all').toLowerCase() : 'all';
      const schemaSel = schemaFilter ? (schemaFilter.value || 'all').toLowerCase() : 'all';

      // Server options depend on db/schema selection
      if (serverFilter) {{
        const allowedServerMap = new Map();
        for (const c of rowCombos) {{
          if (dbSel !== 'all' && c.dbName !== dbSel) continue;
          if (schemaSel !== 'all' && c.schemaName !== schemaSel) continue;
          if (!c.serverName) continue;
          const label = serverOptionMap.get(c.serverName) || c.serverLabel || c.serverName;
          allowedServerMap.set(c.serverName, label);
        }}
        if (serverCountEl) {{
          serverCountEl.textContent = allowedServerMap.size.toString();
        }}
        setOptionsFromMap(serverFilter, allowedServerMap, serverSel);
      }}

      // DB options depend on server/schema selection
      if (dbFilter) {{
        const allowedDbMap = new Map();
        for (const c of rowCombos) {{
          if (serverSel !== 'all' && c.serverName !== serverSel) continue;
          if (schemaSel !== 'all' && c.schemaName !== schemaSel) continue;
          if (!c.dbName) continue;
          const label = dbOptionMap.get(c.dbName) || c.dbLabel || c.dbName;
          allowedDbMap.set(c.dbName, label);
        }}
        if (dbCountEl) {{
          dbCountEl.textContent = allowedDbMap.size.toString();
        }}
        setOptionsFromMap(dbFilter, allowedDbMap, dbSel);
      }}

      // Schema options depend on server/db selection
      if (schemaFilter) {{
        const allowedSchemaMap = new Map();
        for (const c of rowCombos) {{
          if (serverSel !== 'all' && c.serverName !== serverSel) continue;
          if (dbSel !== 'all' && c.dbName !== dbSel) continue;
          if (!c.schemaName) continue;
          const label = schemaOptionMap.get(c.schemaName) || c.schemaLabel || c.schemaName;
          allowedSchemaMap.set(c.schemaName, label);
        }}
        if (schemaCountEl) {{
          schemaCountEl.textContent = allowedSchemaMap.size.toString();
        }}
        setOptionsFromMap(schemaFilter, allowedSchemaMap, schemaSel);
      }}

      updateResetFiltersVisibility();
    }}

    function clearColumnFilter() {{
      columnFilter = null;
      columnFilterLabel = '';
      if (activeColumnChip) {{
        activeColumnChip.classList.remove('visible');
      }}
    }}

    // Initial filter population (all values)
    updateFilterOptions();

    function resetCatalogVisibility() {{
      document.querySelectorAll('.schema-accordion, .table-item').forEach(el => {{
        el.style.display = '';
        el.classList.remove('search-match');
      }});
      document.querySelectorAll('.tab-pane').forEach(pane => {{
        pane.style.display = '';
      }});
      document.querySelectorAll('.db-tabs .nav-link').forEach(link => {{
        link.style.display = '';
      }});

      clearColumnFilter();

      setSummary(
        baseSummary.servers,
        baseSummary.databases,
        baseSummary.schemas,
        baseSummary.tables,
        baseSummary.columns
      );
      updateResultsOverview(baseSummary.tables, baseSummary.columns);
      setSearchStatus('Showing all objects');

      if (clearBtn) {{
        clearBtn.classList.remove('visible');
      }}

      if (serverFilter) serverFilter.value = 'all';
      if (dbFilter) dbFilter.value = 'all';
      if (schemaFilter) schemaFilter.value = 'all';
      updateFilterOptions();
    }}

    function debounce(fn, delay) {{
      let timeout;
      return function () {{
        const args = arguments;
        clearTimeout(timeout);
        timeout = setTimeout(function () {{
          fn.apply(null, args);
        }}, delay);
      }};
    }}

    const runCombinedSearchAndFilters = function () {{
      const qRaw = (globalInput && globalInput.value || '').trim();
      const q = qRaw.toLowerCase();

      const serverSel = serverFilter ? (serverFilter.value || 'all').toLowerCase() : 'all';
      const dbSel = dbFilter ? (dbFilter.value || 'all').toLowerCase() : 'all';
      const schemaSel = schemaFilter ? (schemaFilter.value || 'all').toLowerCase() : 'all';

      const hasSearch = q.length > 0;
      const hasServerFilter = serverSel !== 'all';
      const hasDbFilter = dbSel !== 'all';
      const hasSchemaFilter = schemaSel !== 'all';
      const hasColumnFilter = !!columnFilter;

      if (!hasSearch && !hasServerFilter && !hasDbFilter && !hasSchemaFilter && !hasColumnFilter) {{
        resetCatalogVisibility();
        return;
      }}

      const tokens = [];
      if (hasSearch) tokens.push('Search: "' + qRaw + '"');
      if (hasServerFilter && serverFilter) {{
        const label = serverFilter.options[serverFilter.selectedIndex]?.textContent || '';
        tokens.push('Server: ' + label);
      }}
      if (hasDbFilter && dbFilter) {{
        const label = dbFilter.options[dbFilter.selectedIndex]?.textContent || '';
        tokens.push('Database: ' + label);
      }}
      if (hasSchemaFilter && schemaFilter) {{
        const label = schemaFilter.options[schemaFilter.selectedIndex]?.textContent || '';
        tokens.push('Schema: ' + label);
      }}
      if (hasColumnFilter && columnFilterLabel) {{
        tokens.push('Column: ' + columnFilterLabel);
      }}
      setSearchStatus(tokens.join(' • ') || 'Filtered view');

      document.querySelectorAll('.table-item').forEach(el => {{
        el.style.display = 'none';
        el.classList.remove('search-match');
      }});

      const schemaHasMatch = new Set();
      const dbHasMatch = new Set();

      const serverSet = new Set();
      const dbSet = new Set();
      const schemaSet = new Set();
      const tableSet = new Set();
      let totalCols = 0;

      let expandedCount = 0;
      const MAX_EXPANDED = 25;

      for (const entry of searchEntries) {{
        const {{
          tableCard,
          schemaAcc,
          tabPane,
          columnsCollapse,
          fullText,
          serverName,
          dbName,
          schemaName,
          tableName,
          columnCount,
          columnNames
        }} = entry;

        if (hasSearch && fullText.indexOf(q) === -1) continue;
        if (hasServerFilter && serverName !== serverSel) continue;
        if (hasDbFilter && dbName !== dbSel) continue;
        if (hasSchemaFilter && schemaName !== schemaSel) continue;
        if (hasColumnFilter && (!columnNames || columnNames.indexOf(columnFilter) === -1)) continue;

        tableCard.style.display = '';
        tableCard.classList.add('search-match');

        if (schemaAcc && schemaAcc.id) schemaHasMatch.add(schemaAcc.id);
        if (tabPane && tabPane.id) dbHasMatch.add(tabPane.id);

        if (serverName) serverSet.add(serverName);
        if (dbName) dbSet.add(dbName);
        if (schemaName) schemaSet.add(dbName + '|' + schemaName);
        if (tableName) tableSet.add(dbName + '|' + schemaName + '|' + tableName);
        totalCols += columnCount;

        if (expandedCount < MAX_EXPANDED && columnsCollapse && window.bootstrap) {{
          const colCollapse = bootstrap.Collapse.getOrCreateInstance(columnsCollapse, {{ toggle: false }});
          colCollapse.show();
          expandedCount++;
        }}
      }}

      setSummary(serverSet.size, dbSet.size, schemaSet.size, tableSet.size, totalCols);
      updateResultsOverview(tableSet.size, totalCols);

      document.querySelectorAll('.schema-accordion').forEach(schemaAcc => {{
        const has = schemaHasMatch.has(schemaAcc.id);
        schemaAcc.style.display = has ? '' : 'none';
        if (has && window.bootstrap) {{
          const schemaCollapse = schemaAcc.querySelector('.accordion-collapse');
          if (schemaCollapse) {{
            const schCollapse = bootstrap.Collapse.getOrCreateInstance(schemaCollapse, {{ toggle: false }});
            schCollapse.show();
          }}
        }}
      }});

      document.querySelectorAll('.tab-pane').forEach(tabPane => {{
        const has = dbHasMatch.has(tabPane.id);
        tabPane.style.display = has ? '' : 'none';

        const tabButton = document.querySelector('[data-bs-target="#' + tabPane.id + '"]');
        if (tabButton) {{
          tabButton.style.display = has ? '' : 'none';
        }}
      }});

      let activeTab = document.querySelector('.db-tabs .nav-link.active');
      if (!activeTab || activeTab.style.display === 'none') {{
        const links = document.querySelectorAll('.db-tabs .nav-link');
        let firstVisible = null;
        for (const link of links) {{
          if (link.style.display !== 'none') {{
            firstVisible = link;
            break;
          }}
        }}
        if (firstVisible && window.bootstrap) {{
          const tab = new bootstrap.Tab(firstVisible);
          tab.show();
        }}
      }}

      if (clearBtn && qRaw.length > 0) {{
        clearBtn.classList.add('visible');
      }} else if (clearBtn && qRaw.length === 0) {{
        clearBtn.classList.remove('visible');
      }}
    }};

    if (globalInput) {{
      globalInput.addEventListener('input', debounce(runCombinedSearchAndFilters, 150));
    }}

    if (clearBtn) {{
      clearBtn.addEventListener('click', function () {{
        if (!globalInput) return;
        globalInput.value = '';
        runCombinedSearchAndFilters();
      }});
    }}

    if (serverFilter) {{
      serverFilter.addEventListener('change', function () {{
        updateFilterOptions();
        runCombinedSearchAndFilters();
      }});
    }}
    if (dbFilter) {{
      dbFilter.addEventListener('change', function () {{
        updateFilterOptions();
        runCombinedSearchAndFilters();
      }});
    }}
    if (schemaFilter) {{
      schemaFilter.addEventListener('change', function () {{
        updateFilterOptions();
        runCombinedSearchAndFilters();
      }});
    }}

    if (resetFiltersBtn) {{
      resetFiltersBtn.addEventListener('click', function () {{
        if (serverFilter) serverFilter.value = 'all';
        if (dbFilter) dbFilter.value = 'all';
        if (schemaFilter) schemaFilter.value = 'all';
        updateFilterOptions();
        runCombinedSearchAndFilters();
      }});
    }}

    // Column filter chip click (clear)
    if (activeColumnChip) {{
      activeColumnChip.addEventListener('click', function () {{
        clearColumnFilter();
        runCombinedSearchAndFilters();
      }});
    }}

    // Click on column name cell => set columnFilter
    document.addEventListener('click', function (e) {{
      const cell = e.target.closest('.column-name-cell');
      if (!cell) return;

      // Use attribute first, fall back to innerText
      const rawName = (cell.getAttribute('data-column-name') || cell.innerText || '').trim();
      if (!rawName) return;

      const lower = rawName.toLowerCase();
      columnFilter = lower;
      columnFilterLabel = rawName;

      // Show / update the chip
      if (activeColumnChip && activeColumnChipLabel) {{
        const safeLabel = rawName.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        activeColumnChipLabel.innerHTML =
          '<span class="me-1"><i class="bi bi-columns-gap"></i></span>' +
          '<span>Column: <code>' + safeLabel + '</code></span>';
        activeColumnChip.classList.add('visible');
      }}

      runCombinedSearchAndFilters();
    }});

    // Initialize overview for full catalog on first load
    updateResultsOverview(baseSummary.tables, baseSummary.columns);

    // ---------- EXPORT CSV ----------
    function csvEscape(value) {{
      const v = String(value == null ? '' : value);
      const needsQuotes = /[",\\n]/.test(v);
      const escaped = v.replace(/"/g, '""');
      return needsQuotes ? '"' + escaped + '"' : escaped;
    }}

    if (exportBtn) {{
      exportBtn.addEventListener('click', function () {{
        const q = (globalInput && globalInput.value ? globalInput.value : '').trim();

        const rows = [];
        const header = ['server', 'database', 'schema', 'table',
                        'column_name', 'data_type', 'max_length', 'ordinal_position'];
        rows.push(header);

        // Only export currently visible tables (after search/filters/column filter)
        document.querySelectorAll('.table-item').forEach(tableCard => {{
          if (tableCard.style.display === 'none') return;

          const server = tableCard.dataset.serverName || '';
          const db = tableCard.dataset.dbName || '';
          const schema = tableCard.dataset.schemaName || '';
          const table = tableCard.dataset.tableName || '';

          const tableEl = tableCard.querySelector('table.column-table');
          if (!tableEl) return;

          const headerCells = tableEl.querySelectorAll('thead th');
          let hasMaxLen = false;
          let hasOrdinal = false;
          headerCells.forEach(th => {{
            const text = (th.textContent || '').toLowerCase();
            if (text.indexOf('max length') !== -1) hasMaxLen = true;
            if (text.indexOf('ordinal') !== -1) hasOrdinal = true;
          }});

          tableEl.querySelectorAll('tbody tr').forEach(tr => {{
            const tds = tr.querySelectorAll('td');
            if (!tds.length) return;

            const columnName = (tds[0].innerText || '').trim();
            const dataType = (tds[1].innerText || '').trim();

            let maxLen = '';
            let ordinal = '';

            if (hasMaxLen && hasOrdinal) {{
              maxLen = (tds[2] && tds[2].innerText || '').trim();
              ordinal = (tds[3] && tds[3].innerText || '').trim();
            }} else if (hasMaxLen && !hasOrdinal) {{
              maxLen = (tds[2] && tds[2].innerText || '').trim();
            }} else if (!hasMaxLen && hasOrdinal) {{
              ordinal = (tds[2] && tds[2].innerText || '').trim();
            }}

            rows.push([server, db, schema, table, columnName, dataType, maxLen, ordinal]);
          }});
        }});

        if (rows.length <= 1) {{
          alert('No matching rows to export. Try adjusting search or filters.');
          return;
        }}

        const csvContent = rows
          .map(r => r.map(csvEscape).join(','))
          .join('\\n');

        const blob = new Blob([csvContent], {{ type: 'text/csv;charset=utf-8;' }});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');

        const safeQuery = q || (columnFilterLabel ? 'column_' + columnFilterLabel : 'filtered');
        a.href = url;
        a.download = 'schema_report_' + safeQuery.replace(/[^0-9a-zA-Z-_]+/g, '_') + '.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }});
    }}
  }});
</script>
</body>
</html>
"""

    output_path = Path(output_path)
    output_path.write_text(full_html, encoding="utf-8")
    print(f"Catalog HTML written to: {output_path.resolve()}")
