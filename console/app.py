"""
Operations console: a small read-only web app over the same Postgres tables that
feed Grafana. One page: headline numbers, machine status, the AI fault findings,
and the four condition-monitoring trends.

Deliberately plain: Python standard library plus psycopg2, no web framework and
no internet access. Read-only - it never writes to the database.
"""
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import psycopg2
from psycopg2.extras import RealDictCursor

PG = dict(
    host=os.environ.get("POSTGRES_HOST", "postgres"),
    port=int(os.environ.get("POSTGRES_PORT", "5432")),
    dbname=os.environ.get("POSTGRES_DB", "factory_db"),
    user=os.environ.get("POSTGRES_USER", "factory"),
    password=os.environ.get("POSTGRES_PASSWORD", ""),
)
PORT = int(os.environ.get("CONSOLE_PORT", "8090"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

MACHINES = {
    "cnc_mill": {"label": "CNC mill", "accent": "indigo"},
    "conveyor": {"label": "Conveyor", "accent": "teal"},
    "hydraulic_press": {"label": "Hydraulic press", "accent": "amber"},
}

# machine, column, key, label, unit, normal, warning, limit
TRENDS = [
    ("cnc_mill", "vibration_mms", "vibration", "Spindle vibration", "mm/s", 2.1, 2.5, 4.5),
    ("conveyor", "motor_load_pct", "motor_load", "Conveyor motor load", "%", 65, 70, 100),
    ("cnc_mill", "temperature_c", "cnc_temp", "CNC temperature", "\u00b0C", 62, 68, 85),
    ("hydraulic_press", "oil_temp_c", "oil_temp", "Press oil temperature", "\u00b0C", 52, 58, 75),
]

HEADLINE_SQL = """
SELECT
  (SELECT COUNT(DISTINCT machine_id) FROM machine_telemetry
     WHERE received_at > NOW()::timestamp - INTERVAL '2 minutes')                      AS reporting,
  (SELECT COUNT(*) FROM fault_findings
     WHERE status = 'active' AND last_seen > NOW()::timestamp - INTERVAL '15 minutes') AS open_findings,
  (SELECT COUNT(*) FROM fault_findings
     WHERE first_seen > NOW()::timestamp - INTERVAL '24 hours')                        AS findings_24h,
  (SELECT COUNT(*) FROM machine_telemetry
     WHERE received_at > NOW()::timestamp - INTERVAL '24 hours')                       AS readings_24h,
  (SELECT COUNT(*) FROM fault_findings
     WHERE status IN ('self-cleared', 'cleared after stop')
       AND last_seen > NOW()::timestamp - INTERVAL '24 hours')                         AS closed_24h
"""

LATEST_SQL = """
SELECT DISTINCT ON (machine_id)
  machine_id, status, fault, received_at, temperature_c, vibration_mms,
  motor_load_pct, belt_speed_mpm, pressure_bar, oil_temp_c
FROM machine_telemetry
WHERE received_at > NOW()::timestamp - INTERVAL '10 minutes'
ORDER BY machine_id, received_at DESC
"""

FINDINGS_SQL = """
SELECT id, first_seen, last_seen, occurrences, machine_id, finding_type, rule_severity,
       status, summary, ai_likely_cause, ai_severity, ai_what_to_check, ai_confidence,
       ai_model, ai_seconds, ai_error
FROM fault_findings
WHERE last_seen > NOW()::timestamp - INTERVAL '24 hours'
ORDER BY (status = 'active' AND last_seen > NOW()::timestamp - INTERVAL '15 minutes') DESC,
         last_seen DESC
LIMIT 40
"""

TREND_SQL = """
SELECT to_timestamp(FLOOR(EXTRACT(EPOCH FROM received_at) / %(bucket)s) * %(bucket)s)
         AT TIME ZONE 'UTC' AS bucket,
       AVG({col}) AS value
FROM machine_telemetry
WHERE machine_id = %(machine)s
  AND status = 'running'
  AND {col} IS NOT NULL
  AND received_at > NOW()::timestamp - %(hours)s * INTERVAL '1 hour'
GROUP BY 1 ORDER BY 1
"""


def iso(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value


def clean(row):
    return {k: iso(v) for k, v in row.items()}


def machine_readings(row):
    """The two or three numbers worth showing on a machine card."""
    out = []
    if row["machine_id"] == "cnc_mill":
        out = [("Temperature", row["temperature_c"], "\u00b0C"),
               ("Vibration", row["vibration_mms"], "mm/s")]
    elif row["machine_id"] == "conveyor":
        out = [("Motor load", row["motor_load_pct"], "%"),
               ("Temperature", row["temperature_c"], "\u00b0C"),
               ("Belt speed", row["belt_speed_mpm"], "m/min")]
    else:
        out = [("Oil temperature", row["oil_temp_c"], "\u00b0C"),
               ("Pressure", row["pressure_bar"], "bar")]
    return [{"label": l, "value": round(v, 1) if isinstance(v, float) else v, "unit": u}
            for l, v, u in out if v is not None]


def build_state(hours):
    bucket = max(30, int(hours * 3600 / 400))     # about 400 points per chart
    with psycopg2.connect(**PG) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(HEADLINE_SQL)
            headline = dict(cur.fetchone())

            cur.execute(LATEST_SQL)
            latest = {r["machine_id"]: r for r in cur.fetchall()}
            machines = []
            for mid, meta in MACHINES.items():
                row = latest.get(mid)
                machines.append({
                    "id": mid, "label": meta["label"], "accent": meta["accent"],
                    "status": row["status"] if row else "offline",
                    "fault": row["fault"] if row else None,
                    "last_seen": iso(row["received_at"]) if row else None,
                    "readings": machine_readings(row) if row else [],
                })

            cur.execute(FINDINGS_SQL)
            findings = []
            for r in cur.fetchall():
                f = clean(dict(r))
                f["checks"] = [c.strip() for c in (f.pop("ai_what_to_check") or "").split(";") if c.strip()]
                f["issue"] = f["finding_type"].replace("_", " ")
                f["machine_label"] = MACHINES.get(f["machine_id"], {}).get("label", f["machine_id"])
                findings.append(f)

            trends = []
            for machine, col, key, label, unit, normal, warn, limit in TRENDS:
                if not re.fullmatch(r"[a-z_]+", col):
                    continue                      # column names are from our own list, never user input
                cur.execute(TREND_SQL.format(col=col),
                            {"bucket": bucket, "machine": machine, "hours": hours})
                points = [{"t": iso(r["bucket"]), "v": round(float(r["value"]), 3)}
                          for r in cur.fetchall() if r["value"] is not None]
                trends.append({"key": key, "label": label, "machine": MACHINES[machine]["label"],
                               "accent": MACHINES[machine]["accent"], "unit": unit,
                               "normal": normal, "warn": warn, "limit": limit, "points": points})

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "hours": hours,
            "headline": headline, "machines": machines, "findings": findings, "trends": trends}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                with open(os.path.join(STATIC, "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if url.path == "/api/state":
                hours = float((parse_qs(url.query).get("hours") or ["6"])[0])
                hours = min(max(hours, 0.25), 72)
                return self._send(200, json.dumps(build_state(hours)), "application/json")
            if url.path == "/healthz":
                return self._send(200, "ok", "text/plain")
            self._send(404, "not found", "text/plain")
        except Exception as exc:                  # never leak a stack trace to the browser
            print(f"error handling {self.path}: {type(exc).__name__}: {exc}", flush=True)
            self._send(500, json.dumps({"error": type(exc).__name__}), "application/json")

    def log_message(self, fmt, *args):
        return                                    # quiet: one line per poll is just noise


if __name__ == "__main__":
    print(f"Console on http://0.0.0.0:{PORT} (database {PG['host']}:{PG['port']}/{PG['dbname']})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
