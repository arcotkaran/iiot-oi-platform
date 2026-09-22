"""
One-off installer for the fault finder. Run from the repo root:
    python3 tools/install_fault_finder.py
- Gives the Airflow service access to the analyzer code and the local AI
- Adds panels to the Grafana dashboard (vibration, motor load, press oil temperature, AI findings)
- Upgrades the AI findings table to show each finding's status and the AI's confidence
Safe to run twice: it skips anything already done.
"""
import json
import sys

COMPOSE = "docker-compose.yml"
DASHBOARD = "grafana/dashboards/factory_oi_dashboard.json"
DS = {"type": "grafana-postgresql-datasource", "uid": "aflatmxdxjq4gc"}


def patch_compose():
    text = open(COMPOSE).read()
    steps = [
        ('      AIRFLOW__CORE__LOAD_EXAMPLES: "False"\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n',
         '      OLLAMA_URL: http://ollama:11434\n      OLLAMA_MODEL: ${OLLAMA_MODEL}\n',
         "OLLAMA_URL: http://ollama:11434"),
        ('      - ./dbt/profiles.yml:/opt/airflow/.dbt/profiles.yml:ro\n',
         '      - ./analyzer:/opt/airflow/analyzer:ro\n',
         "./analyzer:/opt/airflow/analyzer"),
    ]
    for anchor, addition, marker in steps:
        if marker in text:
            print(f"compose: already has {marker!r}, skipping")
            continue
        if text.count(anchor) != 1:
            sys.exit(f"STOP: expected exactly one match for:\n{anchor}\nfound {text.count(anchor)}. Nothing changed.")
        text = text.replace(anchor, anchor + addition)
        print(f"compose: added {marker!r}")
    open(COMPOSE, "w").write(text)


def target(sql, fmt):
    return {"refId": "A", "datasource": DS, "editorMode": "code", "rawQuery": True,
            "format": fmt, "rawSql": sql}


def patch_dashboard():
    dash = json.load(open(DASHBOARD))
    panels = dash.setdefault("panels", [])
    titles = {p.get("title") for p in panels}
    next_id = max([p.get("id", 0) for p in panels] + [0]) + 1
    bottom = max([p.get("gridPos", {}).get("y", 0) + p.get("gridPos", {}).get("h", 0) for p in panels] + [0])

    new = [
        {"title": "CNC Spindle Vibration (mm/s)", "type": "timeseries",
         "gridPos": {"h": 8, "w": 12, "x": 0, "y": bottom},
         "fieldConfig": {"defaults": {"unit": "none", "custom": {"lineWidth": 2},
                         "thresholds": {"mode": "absolute", "steps": [
                             {"color": "green", "value": None}, {"color": "orange", "value": 2.5},
                             {"color": "red", "value": 3.5}]},
                         "color": {"mode": "fixed", "fixedColor": "purple"}}, "overrides": []},
         "options": {"legend": {"showLegend": False}},
         "targets": [target("SELECT received_at AS time, vibration_mms AS \"vibration\"\n"
                            "FROM machine_telemetry\nWHERE machine_id = 'cnc_mill' AND status = 'running'\n"
                            "  AND $__timeFilter(received_at)\nORDER BY 1", "time_series")]},
        {"title": "Conveyor Motor Load (%)", "type": "timeseries",
         "gridPos": {"h": 8, "w": 12, "x": 12, "y": bottom},
         "fieldConfig": {"defaults": {"unit": "percent", "custom": {"lineWidth": 2},
                         "color": {"mode": "fixed", "fixedColor": "orange"}}, "overrides": []},
         "options": {"legend": {"showLegend": False}},
         "targets": [target("SELECT received_at AS time, motor_load_pct AS \"motor load\"\n"
                            "FROM machine_telemetry\nWHERE machine_id = 'conveyor' AND status = 'running'\n"
                            "  AND $__timeFilter(received_at)\nORDER BY 1", "time_series")]},
        {"title": "AI Fault Findings (local LLM)", "type": "table",
         "gridPos": {"h": 10, "w": 24, "x": 0, "y": bottom + 8},
         "options": {"showHeader": True, "cellHeight": "md"},
         "fieldConfig": {"defaults": {"custom": {"cellOptions": {"type": "auto"}, "inspect": True}},
                         "overrides": [
                             {"matcher": {"id": "byName", "options": "Status"},
                              "properties": [{"id": "custom.width", "value": 90}]},
                             {"matcher": {"id": "byName", "options": "Severity"},
                              "properties": [{"id": "custom.width", "value": 90},
                                             {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                             {"id": "mappings", "value": [{"type": "value", "options": {
                                                 "high": {"color": "red", "index": 0},
                                                 "medium": {"color": "orange", "index": 1},
                                                 "low": {"color": "yellow", "index": 2}}}]}]}]},
         "targets": [target(
             "SELECT\n"
             "  CASE WHEN last_seen > NOW()::timestamp - INTERVAL '15 minutes' THEN 'ACTIVE' ELSE 'cleared' END AS \"Status\",\n"
             "  last_seen AS \"Last seen\",\n  machine_id AS \"Machine\",\n  finding_type AS \"Issue\",\n"
             "  rule_severity AS \"Severity\",\n  summary AS \"What was detected\",\n"
             "  COALESCE(ai_likely_cause, '(AI unavailable)') AS \"Likely cause (AI)\",\n"
             "  ai_what_to_check AS \"What to check (AI)\",\n  occurrences AS \"Runs seen\"\n"
             "FROM fault_findings\nWHERE last_seen > NOW()::timestamp - INTERVAL '24 hours'\n"
             "ORDER BY (last_seen > NOW()::timestamp - INTERVAL '15 minutes') DESC, last_seen DESC\nLIMIT 25",
             "table")]},
    ]
    added = 0
    for p in new:
        if p["title"] in titles:
            print(f"dashboard: already has '{p['title']}', skipping")
            continue
        p["id"] = next_id
        p["datasource"] = DS
        next_id += 1
        panels.append(p)
        added += 1
        print(f"dashboard: added '{p['title']}'")
    if added:
        dash["version"] = (dash.get("version") or 0) + 1
        json.dump(dash, open(DASHBOARD, "w"), indent=2)


FINDINGS_SQL = (
    "SELECT\n"
    "  CASE WHEN status = 'active' AND last_seen > NOW()::timestamp - INTERVAL '15 minutes' THEN 'ACTIVE'\n"
    "       WHEN status = 'active' THEN 'cleared'\n"
    "       ELSE status END AS \"Status\",\n"
    "  last_seen AS \"Last seen\",\n  machine_id AS \"Machine\",\n  finding_type AS \"Issue\",\n"
    "  rule_severity AS \"Severity\",\n  summary AS \"What was detected\",\n"
    "  COALESCE(ai_likely_cause, '(AI unavailable)') AS \"Likely cause (AI)\",\n"
    "  ai_confidence AS \"AI confidence\",\n"
    "  ai_what_to_check AS \"What to check (AI)\",\n  occurrences AS \"Runs seen\"\n"
    "FROM fault_findings\nWHERE last_seen > NOW()::timestamp - INTERVAL '24 hours'\n"
    "ORDER BY (status = 'active' AND last_seen > NOW()::timestamp - INTERVAL '15 minutes') DESC, last_seen DESC\n"
    "LIMIT 30")
STATUS_COLOURS = {"ACTIVE": {"color": "red", "index": 0}, "watch": {"color": "blue", "index": 1},
                  "self-cleared": {"color": "green", "index": 2}, "cleared after stop": {"color": "green", "index": 3},
                  "cleared": {"color": "text", "index": 4}}


def upgrade_dashboard():
    dash = json.load(open(DASHBOARD))
    panels = dash["panels"]
    changed = False

    table = next((p for p in panels if p.get("title") == "AI Fault Findings (local LLM)"), None)
    if table is None:
        sys.exit("STOP: findings table not found - run the original installer first.")
    if table["targets"][0]["rawSql"] == FINDINGS_SQL:
        print("dashboard: findings table already upgraded, skipping")
    else:
        table["targets"][0]["rawSql"] = FINDINGS_SQL
        overrides = [o for o in table["fieldConfig"]["overrides"]
                     if o["matcher"]["options"] not in ("Status", "AI confidence")]
        overrides += [
            {"matcher": {"id": "byName", "options": "Status"},
             "properties": [{"id": "custom.width", "value": 130},
                            {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                            {"id": "mappings", "value": [{"type": "value", "options": STATUS_COLOURS}]}]},
            {"matcher": {"id": "byName", "options": "AI confidence"},
             "properties": [{"id": "custom.width", "value": 110}]},
        ]
        table["fieldConfig"]["overrides"] = overrides
        table["gridPos"]["h"] = 12
        print("dashboard: findings table upgraded (status + AI confidence)")
        changed = True

    title = "Hydraulic Press Oil Temperature (C)"
    if any(p.get("title") == title for p in panels):
        print(f"dashboard: already has '{title}', skipping")
    else:
        bottom = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in panels)
        panels.append({
            "id": max(p.get("id", 0) for p in panels) + 1, "datasource": DS,
            "title": title, "type": "timeseries",
            "gridPos": {"h": 8, "w": 24, "x": 0, "y": bottom},
            "fieldConfig": {"defaults": {"unit": "celsius", "custom": {"lineWidth": 2},
                            "thresholds": {"mode": "absolute", "steps": [
                                {"color": "green", "value": None}, {"color": "orange", "value": 58},
                                {"color": "red", "value": 75}]},
                            "color": {"mode": "fixed", "fixedColor": "red"}}, "overrides": []},
            "options": {"legend": {"showLegend": False}},
            "targets": [target("SELECT received_at AS time, oil_temp_c AS \"oil temperature\"\n"
                               "FROM machine_telemetry\nWHERE machine_id = 'hydraulic_press' AND status = 'running'\n"
                               "  AND $__timeFilter(received_at)\nORDER BY 1", "time_series")]})
        print(f"dashboard: added '{title}'")
        changed = True

    if changed:
        dash["version"] = (dash.get("version") or 0) + 1
        json.dump(dash, open(DASHBOARD, "w"), indent=2)


if __name__ == "__main__":
    patch_compose()
    patch_dashboard()
    upgrade_dashboard()
    print("done")
