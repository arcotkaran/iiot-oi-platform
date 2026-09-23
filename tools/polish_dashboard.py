"""
Restyle the Grafana dashboard: grouped rows, headline numbers, consistent colours,
and a layout that puts the AI findings near the top.

Run from the repo root:
    python3 tools/polish_dashboard.py

Writes a timestamped backup first. Safe to run twice (it rebuilds the layout from
the panels that are there, and keeps every panel's SQL exactly as it is).
"""
import json
import re
import shutil
import sys
import time

DASHBOARD = "grafana/dashboards/factory_oi_dashboard.json"
DS = {"type": "grafana-postgresql-datasource", "uid": "aflatmxdxjq4gc"}

# One colour per machine, used on every chart that splits by machine.
MACHINE_COLOURS = {"cnc_mill": "blue", "conveyor": "green", "hydraulic_press": "orange"}

# Old title -> (new title, unit, fixed colour or None)
RESTYLE = {
    "Machine Temperatures":               ("Machine temperatures", "celsius", None),
    "Hydraulic Press Pressure":           ("Press pressure", "pressurebar", None),
    "Hourly Average Temperature (dbt)":   ("Hourly average temperature", "celsius", None),
    "CNC Spindle Vibration (mm/s)":       ("Spindle vibration - CNC mill", "none", "purple"),
    "Conveyor Motor Load (%)":            ("Motor load - conveyor", "percent", "green"),
    "Hydraulic Press Oil Temperature (C)": ("Oil temperature - press", "celsius", "orange"),
    "Live Machine Status":                ("Live machine status", None, None),
    "AI Fault Findings (local LLM)":      ("AI fault findings", None, None),
}
# Faint threshold bands: title -> [(value, colour), ...]
THRESHOLDS = {
    "Spindle vibration - CNC mill": [(None, "green"), (2.5, "orange"), (3.5, "red")],
    "Motor load - conveyor":        [(None, "green"), (70, "orange"), (80, "red")],
    "Oil temperature - press":      [(None, "green"), (58, "orange"), (75, "red")],
}


def stat(pid, title, x, y, sql, unit="short", steps=None, w=6):
    return {
        "id": pid, "type": "stat", "title": title, "datasource": DS,
        "gridPos": {"h": 4, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": 0,
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": c, "value": v} for v, c in (steps or [(None, "text")])]}},
            "overrides": []},
        "options": {"graphMode": "none", "textMode": "auto", "colorMode": "value",
                    "justifyMode": "center",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
        "targets": [{"refId": "A", "datasource": DS, "rawQuery": True,
                     "format": "table", "editorMode": "code", "rawSql": sql}],
    }


def row(pid, title, y, collapsed=False, panels=None):
    return {"id": pid, "type": "row", "title": title, "collapsed": collapsed,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": panels or []}


def flatten(panels):
    """Pull panels back out of any collapsed rows, so re-running works."""
    out = []
    for p in panels:
        if p.get("type") == "row":
            out.extend(p.get("panels", []))
        else:
            out.append(p)
    return out


def find(panels, *titles):
    for t in titles:
        for p in panels:
            if p.get("title") == t:
                return p
    return None


def restyle(p):
    title = p.get("title")
    if title not in RESTYLE:
        return
    new_title, unit, colour = RESTYLE[title]
    p["title"] = new_title

    # Make the time range control the charts (some had a fixed 30-minute window).
    # Tables that show a "latest reading" snapshot keep their own short window.
    for t in p.get("targets", []) if p.get("type") == "timeseries" else []:
        sql = t.get("rawSql", "")
        fixed = re.sub(r"received_at\s*>\s*NOW\(\)(::timestamp)?\s*-\s*INTERVAL\s*'[^']+'",
                       "$__timeFilter(received_at)", sql)
        if fixed != sql and "$__timeFilter" not in sql:
            t["rawSql"] = fixed
            print(f"  {new_title}: now follows the dashboard time range")

    if p.get("type") != "timeseries":
        return
    d = p.setdefault("fieldConfig", {}).setdefault("defaults", {})
    if unit:
        d["unit"] = unit
    d.setdefault("custom", {}).update({
        "lineWidth": 2, "fillOpacity": 8, "showPoints": "never",
        "lineInterpolation": "smooth", "gradientMode": "opacity",
        "axisBorderShow": False, "axisSoftMin": None,
    })
    d["custom"].pop("axisSoftMin", None)
    if colour:
        d["color"] = {"mode": "fixed", "fixedColor": colour}
        p.setdefault("options", {})["legend"] = {"showLegend": False}
    else:
        d["color"] = {"mode": "palette-classic"}
        p.setdefault("options", {})["legend"] = {
            "showLegend": True, "displayMode": "list", "placement": "bottom", "calcs": []}
        # same colour for the same machine on every chart
        p["fieldConfig"]["overrides"] = [
            {"matcher": {"id": "byName", "options": m},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
            for m, c in MACHINE_COLOURS.items()]
    p.setdefault("options", {})["tooltip"] = {"mode": "multi", "sort": "none"}

    steps = THRESHOLDS.get(new_title)
    if steps:
        d["thresholds"] = {"mode": "absolute",
                           "steps": [{"color": c, "value": v} for v, c in steps]}
        d["custom"]["thresholdsStyle"] = {"mode": "dashed"}


def tidy_findings(p):
    """Readable findings table: wrapped text, sensible widths, colours."""
    p["options"] = {"showHeader": True, "cellHeight": "sm",
                    "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""}}
    p["fieldConfig"]["defaults"] = {
        "custom": {"cellOptions": {"type": "auto", "wrapText": True},
                   "align": "left", "inspect": True, "filterable": True},
    }
    widths = {"Last seen": 95, "Machine": 120, "Issue": 175, "Severity": 85,
              "AI confidence": 95, "Runs seen": 90}
    overrides = [
        {"matcher": {"id": "byName", "options": "Status"},
         "properties": [{"id": "custom.width", "value": 135},
                        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                        {"id": "mappings", "value": [{"type": "value", "options": {
                            "ACTIVE": {"color": "red", "index": 0},
                            "watch": {"color": "blue", "index": 1},
                            "self-cleared": {"color": "green", "index": 2},
                            "cleared after stop": {"color": "green", "index": 3},
                            "cleared": {"color": "text", "index": 4}}}]}]},
        {"matcher": {"id": "byName", "options": "Severity"},
         "properties": [{"id": "custom.width", "value": 85},
                        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                        {"id": "mappings", "value": [{"type": "value", "options": {
                            "high": {"color": "red", "index": 0},
                            "medium": {"color": "orange", "index": 1},
                            "low": {"color": "yellow", "index": 2}}}]}]},
        {"matcher": {"id": "byName", "options": "What was detected"},
         "properties": [{"id": "custom.width", "value": 430}]},
        {"matcher": {"id": "byName", "options": "What to check (AI)"},
         "properties": [{"id": "custom.width", "value": 300}]},
        {"matcher": {"id": "byName", "options": "Last seen"},
         "properties": [{"id": "unit", "value": "time:HH:mm"}]},
    ]
    overrides += [{"matcher": {"id": "byName", "options": n},
                   "properties": [{"id": "custom.width", "value": w}]}
                  for n, w in widths.items() if n != "Last seen"]
    p["fieldConfig"]["overrides"] = overrides


def tidy_status(p):
    p["options"] = {"showHeader": True, "cellHeight": "sm"}
    p["fieldConfig"]["defaults"] = {"custom": {"align": "left", "cellOptions": {"type": "auto"}}}
    p["fieldConfig"]["overrides"] = [
        {"matcher": {"id": "byName", "options": "status"},
         "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                        {"id": "mappings", "value": [{"type": "value", "options": {
                            "running": {"color": "green", "index": 0},
                            "stopped": {"color": "orange", "index": 1}}}]}]},
        {"matcher": {"id": "byName", "options": "temperature"},
         "properties": [{"id": "unit", "value": "celsius"}, {"id": "decimals", "value": 1}]},
    ]


def main():
    dash = json.load(open(DASHBOARD))
    shutil.copy(DASHBOARD, f"{DASHBOARD}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
    panels = flatten(dash.get("panels", []))
    if not panels:
        sys.exit("STOP: no panels found, nothing changed.")

    for p in panels:
        restyle(p)

    findings = find(panels, "AI fault findings", "AI Fault Findings (local LLM)")
    status = find(panels, "Live machine status", "Live Machine Status")
    if findings:
        tidy_findings(findings)
    if status:
        tidy_status(status)

    # Drop any headline stats from a previous run, so re-running doesn't duplicate them.
    STAT_TITLES = {"Machines reporting", "Open findings", "Findings, last 24 h", "Readings, last 24 h"}
    panels = [p for p in panels if not (p.get("type") == "stat" and p.get("title") in STAT_TITLES)]

    next_id = max([p.get("id", 0) for p in panels] + [100]) + 1
    stats = [
        stat(next_id, "Machines reporting", 0, 1,
             "SELECT COUNT(DISTINCT machine_id) AS \"machines\"\nFROM machine_telemetry\n"
             "WHERE received_at > NOW()::timestamp - INTERVAL '2 minutes'",
             steps=[(None, "red"), (3, "green")]),
        stat(next_id + 1, "Open findings", 6, 1,
             "SELECT COUNT(*) AS \"open\"\nFROM fault_findings\n"
             "WHERE status = 'active' AND last_seen > NOW()::timestamp - INTERVAL '15 minutes'",
             steps=[(None, "green"), (1, "orange"), (4, "red")]),
        stat(next_id + 2, "Findings, last 24 h", 12, 1,
             "SELECT COUNT(*) AS \"findings\"\nFROM fault_findings\n"
             "WHERE first_seen > NOW()::timestamp - INTERVAL '24 hours'"),
        stat(next_id + 3, "Readings, last 24 h", 18, 1,
             "SELECT COUNT(*) AS \"readings\"\nFROM machine_telemetry\n"
             "WHERE received_at > NOW()::timestamp - INTERVAL '24 hours'"),
    ]

    def place(p, x, y, w, h):
        p["gridPos"] = {"h": h, "w": w, "x": x, "y": y}
        return p

    layout = [row(next_id + 10, "Overview", 0)] + stats
    y = 5
    if status:
        layout.append(place(status, 0, y, 24, 6))
        y += 6
    layout.append(row(next_id + 11, "AI fault findings", y))
    y += 1
    if findings:
        layout.append(place(findings, 0, y, 24, 13))
        y += 13
    layout.append(row(next_id + 12, "Condition monitoring", y))
    y += 1
    pairs = [("Spindle vibration - CNC mill", "Motor load - conveyor"),
             ("Machine temperatures", "Oil temperature - press")]
    for left, right in pairs:
        for i, t in enumerate((left, right)):
            p = find(panels, t)
            if p:
                layout.append(place(p, 12 * i, y, 12, 8))
        y += 8
    press = find(panels, "Press pressure")
    if press:
        layout.append(place(press, 0, y, 24, 7))
        y += 7

    dbt = find(panels, "Hourly average temperature")
    if dbt:
        layout.append(row(next_id + 13, "Analytics (dbt)", y, collapsed=True,
                          panels=[place(dbt, 0, y + 1, 24, 8)]))

    placed = {id(p) for p in layout} | {id(p) for r in layout if r.get("type") == "row"
                                        for p in r.get("panels", [])}
    leftovers = [p for p in panels if id(p) not in placed]
    for p in leftovers:
        y += 8
        layout.append(place(p, 0, y, 24, 8))
        print(f"  kept unrecognised panel at the bottom: {p.get('title')}")

    dash["panels"] = layout
    dash["title"] = "Factory Operational Intelligence"
    dash["description"] = ("Live machine telemetry, rule-based fault detection and "
                           "local-AI explanations for a simulated factory floor.")
    dash["refresh"] = "30s"
    dash["time"] = {"from": "now-6h", "to": "now"}
    dash["timepicker"] = {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m", "1h"]}
    dash["graphTooltip"] = 1          # shared crosshair across charts
    dash["editable"] = True
    dash["style"] = "dark"
    dash["tags"] = ["factory", "iiot", "ai"]
    dash["version"] = (dash.get("version") or 0) + 1

    json.dump(dash, open(DASHBOARD, "w"), indent=2)
    print(f"\ndashboard rewritten: {len(stats)} new stat panels, "
          f"{sum(1 for p in layout if p.get('type') == 'row')} rows, version {dash['version']}")


if __name__ == "__main__":
    main()
