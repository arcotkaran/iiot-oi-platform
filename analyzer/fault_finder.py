"""
Fault finder: rule-based detection + local-AI explanation.

Runs every 10 minutes (Airflow DAG `fault_analysis`):
  1. DETECT  - plain statistics over recent telemetry (cannot hallucinate)
  2. EXPLAIN - each NEW finding goes to a small local LLM (Ollama) for
               likely cause / severity / what to check
  3. STORE   - results land in public.fault_findings (shown in Grafana)
  4. FOLLOW UP - when a reading that was flagged comes back down, the finding is
               closed as "self-cleared" or "cleared after stop", and the episode
               itself is logged as a low-priority "watch" note for later review.
               Repeated self-clearing episodes are escalated.

Detection never depends on the AI: if the model is down, findings are
still saved, with the error recorded.

Usage:
  python fault_finder.py            normal run (writes to the database)
  python fault_finder.py --dry-run  detect + explain, print only, no writes
"""
import os
import sys
import json
import time
import statistics
import urllib.request
from datetime import timedelta

# ============================================================
# CONFIGURATION
# ============================================================
PG = dict(
    host=os.environ.get("POSTGRES_HOST", "postgres"),
    port=int(os.environ.get("POSTGRES_PORT", "5432")),
    dbname=os.environ.get("POSTGRES_DB", "factory_db"),
    user=os.environ.get("POSTGRES_USER", "factory"),
    password=os.environ.get("POSTGRES_PASSWORD", ""),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
AI_ENABLED = os.environ.get("AI_ENABLED", "true").lower() == "true"
DEDUP_MINUTES = 25          # same machine + issue within this window = same finding
LOOKBACK_MINUTES = 60       # telemetry fetched per run

# What "healthy" looks like for each machine (like a commissioning baseline).
REF = {
    "cnc_vibration_normal": 2.1, "cnc_vibration_warn": 2.5,
    "cnc_vibration_alarm": 3.5, "cnc_vibration_limit": 4.5,
    "conveyor_load_normal": 65.0, "conveyor_load_warn": 70.0, "conveyor_load_alarm": 80.0,
    "conveyor_temp_normal": 45.0, "conveyor_temp_warn": 48.0, "conveyor_temp_alarm": 53.0,
    "cnc_temp_normal": 62.0, "cnc_temp_warn": 68.0,
    "press_oil_normal": 52.0, "press_oil_warn": 58.0,
    "silence_seconds": 15,      # no data for longer than this = a gap
    "stuck_seconds": 30,        # identical non-zero reading for this long = stuck sensor
    "trips_per_hour_warn": 3,   # protective shutdowns per hour considered abnormal
    "trip_recent_minutes": 20,  # a trip older than this is history, not an active problem
    "recurring_episodes": 3,    # self-clearing episodes in 24 h that make it worth a closer look
}
THERMAL = {
    "cnc_mill":        {"fault": "OVERHEAT",     "field": "temperature_c", "trip": 85.0,
                        "normal": REF["cnc_temp_normal"], "warn": REF["cnc_temp_warn"], "label": "Temperature"},
    "hydraulic_press": {"fault": "OIL_OVERTEMP", "field": "oil_temp_c",    "trip": 75.0,
                        "normal": REF["press_oil_normal"], "warn": REF["press_oil_warn"], "label": "Oil temperature"},
}
MACHINE_CONTEXT = {
    "cnc_mill": "CNC milling machine, spindle ~3200 rpm, normal spindle vibration ~2.1 mm/s, "
                "normal running temperature ~62 C, protective shutdown (OVERHEAT) at 85 C.",
    "conveyor": "Belt conveyor driven by an electric motor. Normal motor load ~65%, "
                "belt speed ~12.5 m/min, running temperature ~45 C.",
    "hydraulic_press": "Hydraulic press cycling up to ~180 bar, normal oil temperature ~52 C, "
                       "protective shutdown (OIL_OVERTEMP) at 75 C oil temperature.",
    "pipeline": "The data pipeline (MQTT broker, Kafka, database writer) carrying telemetry "
                "from all machines to the database.",
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


# ============================================================
# SMALL HELPERS
# ============================================================
def mean(values):
    return statistics.mean(values) if values else None


def slope_per_min(points):
    """Least-squares slope of (datetime, value) points, in units per minute."""
    if len(points) < 10:
        return 0.0
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 60 for t, _ in points]
    ys = [v for _, v in points]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def machine_rows(rows, machine, since=None):
    return [r for r in rows if r["machine_id"] == machine and (since is None or r["ts"] >= since)]


def finding(machine, ftype, severity, summary, evidence):
    return {"machine_id": machine, "finding_type": ftype, "severity": severity,
            "summary": summary, "evidence": evidence}


# ============================================================
# DETECTORS  (pure functions: rows + now -> list of findings)
# ============================================================
def detect_vibration(rows, now):
    recent = [r for r in machine_rows(rows, "cnc_mill", now - timedelta(minutes=10))
              if r["status"] == "running" and r["vibration_mms"] is not None]
    if len(recent) < 60:
        return []
    avg = mean([r["vibration_mms"] for r in recent])
    if avg < REF["cnc_vibration_warn"]:
        return []
    trend_pts = [(r["ts"], r["vibration_mms"]) for r in machine_rows(rows, "cnc_mill", now - timedelta(minutes=20))
                 if r["status"] == "running" and r["vibration_mms"] is not None]
    trend = slope_per_min(trend_pts)
    ev = {"avg_vibration_last_10min_mm_s": round(avg, 2),
          "normal_vibration_mm_s": REF["cnc_vibration_normal"],
          "trend_mm_s_per_min": round(trend, 3)}
    summary = (f"Spindle vibration averaging {avg:.2f} mm/s over the last 10 min "
               f"(normal ~{REF['cnc_vibration_normal']}), trend {trend:+.3f} mm/s per min.")
    if trend > 0.01 and avg < REF["cnc_vibration_limit"]:
        eta = (REF["cnc_vibration_limit"] - avg) / trend
        ev["minutes_until_4_5_mm_s_at_current_trend"] = round(eta, 1)
        summary += f" At this rate it reaches {REF['cnc_vibration_limit']} mm/s in about {eta:.0f} min."
    summary += " No vibration fault code has been raised by the machine."
    sev = "high" if avg >= REF["cnc_vibration_alarm"] else "medium"
    return [finding("cnc_mill", "vibration_rising", sev, summary, ev)]


def detect_motor_strain(rows, now):
    recent = [r for r in machine_rows(rows, "conveyor", now - timedelta(minutes=10))
              if r["status"] == "running" and r["motor_load_pct"] is not None]
    if len(recent) < 60:
        return []
    load = mean([r["motor_load_pct"] for r in recent])
    temp = mean([r["temperature_c"] for r in recent if r["temperature_c"] is not None])
    speed = mean([r["belt_speed_mpm"] for r in recent if r["belt_speed_mpm"] is not None])
    if load < REF["conveyor_load_warn"] and (temp is None or temp < REF["conveyor_temp_warn"]):
        return []
    ev = {"avg_motor_load_pct": round(load, 1), "normal_motor_load_pct": REF["conveyor_load_normal"],
          "avg_temperature_c": round(temp, 1) if temp is not None else None,
          "normal_temperature_c": REF["conveyor_temp_normal"],
          "avg_belt_speed_mpm": round(speed, 2) if speed is not None else None, "normal_belt_speed_mpm": 12.5}
    summary = (f"Conveyor motor load averaging {load:.1f}% over the last 10 min (normal ~65%), "
               f"running temperature {temp:.1f} C (normal ~45 C), belt speed {speed:.2f} m/min (normal ~12.5).")
    sev = "high" if load >= REF["conveyor_load_alarm"] or (temp or 0) >= REF["conveyor_temp_alarm"] else "medium"
    return [finding("conveyor", "motor_strain", sev, summary, ev)]


def detect_stuck_sensor(rows, now):
    """A live pressure reading always varies; an identical non-zero value repeated is a frozen sensor."""
    press = machine_rows(rows, "hydraulic_press", now - timedelta(minutes=15))
    best, run = None, []
    for r in press:
        p = r["pressure_bar"]
        if p is not None and p > 0 and run and p == run[-1]["pressure_bar"]:
            run.append(r)
        else:
            run = [r] if (p is not None and p > 0) else []
        if run and (best is None or len(run) > len(best)):
            best = list(run)
    if not best:
        return []
    secs = (best[-1]["ts"] - best[0]["ts"]).total_seconds()
    if secs < REF["stuck_seconds"]:
        return []
    statuses = sorted({r["status"] for r in best})
    ongoing = bool(press) and best[-1] is press[-1]
    ev = {"frozen_value_bar": best[0]["pressure_bar"], "frozen_for_seconds": round(secs),
          "machine_status_while_frozen": statuses, "still_frozen": ongoing}
    summary = (f"Pressure reading stuck at exactly {best[0]['pressure_bar']} bar for {secs:.0f} s "
               f"while the press reported status {', '.join(statuses)}.")
    sev = "medium"
    if "stopped" in statuses:
        summary += " A stopped press cannot hold that pressure, so the reading is not credible."
        sev = "high"
    summary += " Still frozen." if ongoing else " Reading has since resumed changing."
    return [finding("hydraulic_press", "stuck_sensor", sev, summary, ev)]


def detect_silence(rows, now):
    """Gaps in data. All machines silent together = pipeline problem; one machine = that machine's comms."""
    window = now - timedelta(minutes=15)
    recent = [r for r in rows if r["ts"] >= window]
    if not recent:
        return [finding("pipeline", "pipeline_gap", "high",
                        "No telemetry at all from any machine in the last 15 minutes.",
                        {"minutes_without_data": 15, "ongoing": True})]
    limit = REF["silence_seconds"]
    out = []

    # Whole-pipeline gaps: no message from ANY machine
    all_ts = sorted(r["ts"] for r in recent)
    pipe_gaps = [(a, b) for a, b in zip(all_ts, all_ts[1:]) if (b - a).total_seconds() > limit]
    if (now - all_ts[-1]).total_seconds() > limit:
        pipe_gaps.append((all_ts[-1], now))
    if pipe_gaps:
        longest = max(pipe_gaps, key=lambda g: g[1] - g[0])
        secs = (longest[1] - longest[0]).total_seconds()
        ongoing = longest[1] == now
        out.append(finding("pipeline", "pipeline_gap", "high" if ongoing else "medium",
                           f"All machines went silent together for {secs:.0f} s"
                           f"{' and are still silent' if ongoing else ''}. "
                           f"A shared-infrastructure problem, not a single machine.",
                           {"longest_gap_seconds": round(secs), "gaps_in_window": len(pipe_gaps),
                            "ongoing": ongoing}))

    # Single-machine gaps: this machine silent while others kept reporting
    for m in ("cnc_mill", "conveyor", "hydraulic_press"):
        ts = [r["ts"] for r in recent if r["machine_id"] == m]
        others = [r["ts"] for r in recent if r["machine_id"] != m]
        gaps = [(a, b) for a, b in zip(ts, ts[1:]) if (b - a).total_seconds() > limit]
        if ts and (now - ts[-1]).total_seconds() > limit:
            gaps.append((ts[-1], now))
        gaps = [(a, b) for a, b in gaps
                if sum(1 for o in others if a < o < b) > (b - a).total_seconds()]   # others kept talking
        if not gaps:
            continue
        longest = max(gaps, key=lambda g: g[1] - g[0])
        secs = (longest[1] - longest[0]).total_seconds()
        ongoing = longest[1] == now
        out.append(finding(m, "data_dropout", "high" if ongoing else "medium",
                           f"{m} sent no data for {secs:.0f} s while the other machines kept reporting"
                           f"{' - still silent' if ongoing else ''}. Points to this machine's "
                           f"controller or network link rather than the pipeline.",
                           {"longest_gap_seconds": round(secs), "ongoing": ongoing}))
    return out


def detect_temperature(rows, now):
    """Running hotter than normal, with an early warning before a protective trip."""
    out = []
    for m, cfg in THERMAL.items():
        recent = [r for r in machine_rows(rows, m, now - timedelta(minutes=10))
                  if r["status"] == "running" and r[cfg["field"]] is not None]
        if len(recent) < 120:
            continue
        avg = mean([r[cfg["field"]] for r in recent])
        if avg < cfg["warn"]:
            continue
        pts = [(r["ts"], r[cfg["field"]]) for r in machine_rows(rows, m, now - timedelta(minutes=10))
               if r["status"] == "running" and r[cfg["field"]] is not None]
        rate = slope_per_min(pts)
        latest = recent[-1][cfg["field"]]
        ev = {"avg_last_10min_c": round(avg, 1), "normal_c": cfg["normal"], "latest_c": latest,
              "trend_c_per_min": round(rate, 2), "trip_limit_c": cfg["trip"]}
        summary = (f"{cfg['label']} averaging {avg:.1f} C over the last 10 min (normal ~{cfg['normal']:.0f} C), "
                   f"latest {latest:.1f} C, trend {rate:+.2f} C per min.")
        sev = "medium"
        if rate > 0.05:
            eta = (cfg["trip"] - latest) / rate
            ev["minutes_to_trip_at_current_trend"] = round(eta, 1)
            summary += f" At this rate the {cfg['fault']} trip at {cfg['trip']:.0f} C is about {eta:.0f} min away."
            if eta <= 10:
                sev = "high"
        elif rate < -0.05:
            summary += " It is now falling."
        if cfg["trip"] - latest <= 6:
            sev = "high"
        out.append(finding(m, "temperature_rising", sev, summary, ev))
    return out


def detect_thermal_trips(rows, now):
    """Protective shutdowns (OVERHEAT / OIL_OVERTEMP) the machine itself reported."""
    out = []
    for m, cfg in THERMAL.items():
        mr = machine_rows(rows, m)
        if len(mr) < 60:
            continue
        trip_times = [b["ts"] for a, b in zip(mr, mr[1:]) if b["fault"] == cfg["fault"] and a["fault"] != cfg["fault"]]
        if not trip_times or (now - trip_times[-1]) > timedelta(minutes=REF["trip_recent_minutes"]):
            continue
        span_h = max((mr[-1]["ts"] - mr[0]["ts"]).total_seconds() / 3600, 1 / 60)
        trips = len(trip_times)
        downtime = sum(1 for r in mr if r["fault"] == cfg["fault"]) / len(mr) * 100
        ev = {"protective_trips_in_window": trips, "window_minutes": round(span_h * 60),
              "last_trip_utc": trip_times[-1].strftime("%H:%M:%S"),
              "percent_time_stopped_by_trips": round(downtime, 1), "trip_limit_c": cfg["trip"],
              "current_status": mr[-1]["status"]}
        if trips / span_h >= REF["trips_per_hour_warn"] and trips >= 3:
            summary = (f"{m} tripped on {cfg['fault']} {trips} times in the last {span_h * 60:.0f} min "
                       f"and was stopped by trips {downtime:.0f}% of the time. Last trip at "
                       f"{ev['last_trip_utc']} UTC.")
            out.append(finding(m, "thermal_trip_cycling", "high" if downtime >= 15 else "medium", summary, ev))
        else:
            summary = (f"{m} tripped on {cfg['fault']} ({cfg['trip']:.0f} C limit) "
                       f"{'once' if trips == 1 else f'{trips} times'} in the last {span_h * 60:.0f} min, "
                       f"last at {ev['last_trip_utc']} UTC.")
            out.append(finding(m, "protective_trip", "medium", summary, ev))
    return out


# Signals watched for "went up, then came back down" episodes.
EXCURSION_SIGNALS = [
    # machine, field, name, unit, normal, warning level, active findings this episode can close
    ("cnc_mill", "vibration_mms", "vibration", "mm/s", REF["cnc_vibration_normal"], REF["cnc_vibration_warn"],
     ["vibration_rising"]),
    ("cnc_mill", "temperature_c", "temperature", "C", REF["cnc_temp_normal"], REF["cnc_temp_warn"],
     ["temperature_rising", "protective_trip", "thermal_trip_cycling"]),
    ("conveyor", "motor_load_pct", "motor_load", "%", REF["conveyor_load_normal"], REF["conveyor_load_warn"],
     ["motor_strain"]),
    ("hydraulic_press", "oil_temp_c", "oil_temp", "C", REF["press_oil_normal"], REF["press_oil_warn"],
     ["temperature_rising", "protective_trip", "thermal_trip_cycling"]),
]
PROTECTIVE_CODES = {"OVERHEAT", "OIL_OVERTEMP"}


def detect_excursions(rows, now):
    """A reading that climbed above its warning level earlier in the hour and is now back to normal."""
    out = []
    for m, field, name, unit, normal, warn, closes in EXCURSION_SIGNALS:
        mr = machine_rows(rows, m)
        run = [r for r in mr if r["status"] == "running" and r[field] is not None]
        is_temp = field in ("temperature_c", "oil_temp_c")
        if len(run) < 600:
            continue
        # 2-minute buckets across the hour. A bucket counts as "elevated" if the running
        # average is above the warning level OR (for temperatures) the machine tripped on
        # overtemperature in it: a trip cools the machine down, but the problem is still there.
        buckets = {}
        for r in mr:
            k = int((r["ts"] - mr[0]["ts"]).total_seconds() // 120)
            buckets.setdefault(k, []).append(r)
        series = []
        for _, b in sorted(buckets.items()):
            vals = [x[field] for x in b if x["status"] == "running" and x[field] is not None]
            avg = mean(vals) if len(vals) >= 30 else None
            tripped = is_temp and any(x["fault"] in PROTECTIVE_CODES for x in b)
            series.append({"start": b[0]["ts"], "end": b[-1]["ts"], "avg": avg,
                           "elevated": tripped or (avg is not None and avg >= warn)})
        if len(series) < 8 or not any(x["elevated"] for x in series):
            continue
        last_hi = max(i for i, x in enumerate(series) if x["elevated"])
        if (now - series[last_hi]["end"]) < timedelta(minutes=8):
            continue
        # Walk back to the start of the episode, bridging short dips (e.g. restarts after a trip)
        first_hi, i, dips = last_hi, last_hi - 1, 0
        while i >= 0:
            if series[i]["elevated"]:
                first_hi, dips = i, 0
            else:
                dips += 1
                if dips > 2:
                    break
            i -= 1
        episode = series[first_hi:last_hi + 1]
        peaks = [x for x in episode if x["avg"] is not None]
        if not peaks:
            continue
        top = max(peaks, key=lambda x: x["avg"])
        peak, peak_start = top["avg"], top["start"]
        last10 = [r[field] for r in run if r["ts"] >= now - timedelta(minutes=10)]
        last5 = [r[field] for r in run if r["ts"] >= now - timedelta(minutes=5)]
        if len(last10) < 120 or len(last5) < 60:
            continue
        current10, current = mean(last10), mean(last5)
        if current10 >= warn or current >= normal + 0.5 * (warn - normal):
            continue

        onset = series[first_hi]["start"] if first_hi > 0 else None
        cleared = series[last_hi]["end"]
        pre = [x["avg"] for x in series[:first_hi] if x["avg"] is not None]
        baseline = mean(pre[-5:]) if pre else None

        # Any stops during the episode, and the codes the machine gave for them
        window_start = onset or mr[0]["ts"]
        stops, codes = 0, {}
        prev = None
        for r in mr:
            if window_start <= r["ts"] <= cleared + timedelta(minutes=2):
                if r["status"] == "stopped" and (prev is None or prev["status"] != "stopped"):
                    stops += 1
                    code = r["fault"] or "no code"
                    codes[code] = codes.get(code, 0) + 1
            prev = r
        how = "on its own" if stops == 0 else "after a stop"

        ev = {"signal": name, "unit": unit, "normal": normal, "warning_level": warn,
              "level_before": round(baseline, 2) if baseline is not None else None,
              "peak_2min_avg": round(peak, 2), "peak_at_utc": peak_start.strftime("%H:%M"),
              "above_warning_from_utc": onset.strftime("%H:%M") if onset else "before window",
              "back_below_warning_utc": cleared.strftime("%H:%M"),
              "minutes_above_warning": round((cleared - onset).total_seconds() / 60) if onset else None,
              "minutes_rising_to_peak": round((peak_start - onset).total_seconds() / 60) if onset else None,
              "minutes_from_peak_to_back_below_warning": round((cleared - peak_start).total_seconds() / 60),
              "current_5min_avg": round(current, 2),
              "returned_to_normal": how, "stops_during_episode": codes or None}
        label = name.replace("_", " ")
        summary = (f"{m} {label} rose from ~{(baseline if baseline is not None else normal):.1f} to a peak of "
                   f"{peak:.2f} {unit} around {ev['peak_at_utc']} UTC")
        if onset:
            summary += (f" (above the {warn:g} {unit} warning level for about "
                        f"{ev['minutes_above_warning']} min)")
        summary += f", and is now back to {current:.2f} {unit}."
        if stops == 0:
            summary += (" It came back down with no stop and no fault code from the machine. "
                        "No cause has been identified.")
        else:
            summary += (" It came back down after the machine stopped (codes: "
                        + ", ".join(f"{c} x{n}" for c, n in codes.items()) + ").")
        f = finding(m, f"{name}_rise_cleared", "low", summary, ev)
        f["closes"] = closes
        f["closed_status"] = "self-cleared" if stops == 0 else "cleared after stop"
        out.append(f)
    return out


DETECTORS = [detect_vibration, detect_motor_strain, detect_stuck_sensor, detect_silence,
             detect_temperature, detect_thermal_trips, detect_excursions]


def detect_all(rows, now):
    found = []
    for d in DETECTORS:
        try:
            found.extend(d(rows, now))
        except Exception as e:   # one broken detector must not stop the others
            print(f"  detector {d.__name__} failed: {type(e).__name__}: {e}", flush=True)
    # While a machine is trip-cycling, "running hot" on the same machine is the same story.
    cycling = {f["machine_id"] for f in found if f["finding_type"] == "thermal_trip_cycling"}
    return [f for f in found if not (f["finding_type"] == "temperature_rising" and f["machine_id"] in cycling)]


# ============================================================
# LOCAL AI (Ollama)
# ============================================================
AI_SCHEMA = {
    "type": "object",
    "properties": {
        "likely_cause": {"type": "string"},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
        "what_to_check": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["likely_cause", "severity", "what_to_check", "confidence"],
}
AI_SYSTEM = (
    "You are a maintenance assistant in a factory. You receive an issue that rule-based "
    "monitoring has already detected, with the measured evidence. Explain the most likely "
    "physical cause, rate the severity, and list 2 to 4 concrete checks for a maintenance "
    "technician. Base your answer only on the evidence given and do not invent readings. "
    "Say how confident you are (low, medium or high). If the evidence shows the reading has "
    "already come back to normal, the cause may be uncertain: give the most plausible "
    "explanations, and recommend what to record or watch for rather than urgent repair, "
    "unless the evidence shows it keeps happening. Reply only with JSON."
)


def ask_ai(f, others):
    prompt = (
        f"Machine: {f['machine_id']} ({MACHINE_CONTEXT.get(f['machine_id'], '')})\n"
        f"Detected issue: {f['finding_type']} (rule severity: {f['severity']})\n"
        f"Summary: {f['summary']}\n"
        f"Evidence: {json.dumps(f['evidence'], default=str)}\n"
        f"Other issues detected on this machine right now: {'; '.join(others) if others else 'none'}"
    )
    body = {"model": OLLAMA_MODEL, "stream": False, "format": AI_SCHEMA, "keep_alive": "5m",
            "options": {"temperature": 0.2, "num_ctx": 2048},
            "messages": [{"role": "system", "content": AI_SYSTEM},
                         {"role": "user", "content": prompt}]}
    started = time.time()
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            reply = json.loads(json.load(resp)["message"]["content"])
        checks = reply.get("what_to_check") or []
        if isinstance(checks, str):
            checks = [checks]
        sev = str(reply.get("severity", "")).lower()
        conf = str(reply.get("confidence", "")).lower()
        return {"likely_cause": str(reply.get("likely_cause", "")).strip()[:500] or None,
                "severity": sev if sev in SEVERITY_RANK else None,
                "what_to_check": "; ".join(str(c).strip() for c in checks[:5])[:1000] or None,
                "confidence": conf if conf in SEVERITY_RANK else None,
                "model": OLLAMA_MODEL, "seconds": round(time.time() - started, 1), "error": None}
    except Exception as e:
        return {"likely_cause": None, "severity": None, "what_to_check": None, "confidence": None,
                "model": OLLAMA_MODEL, "seconds": round(time.time() - started, 1),
                "error": f"{type(e).__name__}: {e}"[:300]}


def explain(f, all_findings):
    if not AI_ENABLED:
        return {"likely_cause": None, "severity": None, "what_to_check": None, "confidence": None,
                "model": None, "seconds": None, "error": "AI disabled"}
    others = [o["summary"] for o in all_findings
              if o["machine_id"] == f["machine_id"] and o is not f]
    return ask_ai(f, others)


# ============================================================
# DATABASE
# ============================================================
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.fault_findings (
    id               SERIAL PRIMARY KEY,
    first_seen       TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_seen        TIMESTAMP   NOT NULL DEFAULT NOW(),
    occurrences      INTEGER     NOT NULL DEFAULT 1,
    machine_id       VARCHAR(50) NOT NULL,
    finding_type     VARCHAR(50) NOT NULL,
    rule_severity    VARCHAR(10) NOT NULL,
    summary          TEXT        NOT NULL,
    evidence         JSONB,
    ai_likely_cause  TEXT,
    ai_severity      VARCHAR(10),
    ai_what_to_check TEXT,
    ai_model         VARCHAR(100),
    ai_seconds       REAL,
    ai_error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_fault_findings_last_seen ON public.fault_findings (last_seen);
ALTER TABLE public.fault_findings ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE public.fault_findings ADD COLUMN IF NOT EXISTS ai_confidence VARCHAR(10);
"""

FETCH_SQL = """
SELECT machine_id, received_at, temperature_c, vibration_mms, motor_load_pct, belt_speed_mpm,
       pressure_bar, oil_temp_c, status, fault
FROM public.machine_telemetry
WHERE received_at > NOW()::timestamp - %s * INTERVAL '1 minute'
ORDER BY received_at, id
"""
COLS = ["machine_id", "ts", "temperature_c", "vibration_mms", "motor_load_pct", "belt_speed_mpm",
        "pressure_bar", "oil_temp_c", "status", "fault"]


def save(cur, f, all_findings):
    """Insert a new finding, or update the open one. Returns ('new'|'updated'|'escalated', ai)."""
    cur.execute("""SELECT id, rule_severity FROM public.fault_findings
                   WHERE machine_id = %s AND finding_type = %s AND status IN ('active', 'watch')
                     AND last_seen > NOW()::timestamp - %s * INTERVAL '1 minute'
                   ORDER BY last_seen DESC LIMIT 1""",
                (f["machine_id"], f["finding_type"], DEDUP_MINUTES))
    existing = cur.fetchone()
    is_episode = f["finding_type"].endswith("_rise_cleared")
    result, ai = None, None

    if existing:
        fid, old_sev = existing
        escalated = SEVERITY_RANK[f["severity"]] > SEVERITY_RANK.get(old_sev, 0)
        new_sev = f["severity"] if escalated else old_sev
        if is_episode:   # same episode seen again: keep the original write-up
            cur.execute("""UPDATE public.fault_findings SET last_seen = NOW(), occurrences = occurrences + 1
                           WHERE id = %s""", (fid,))
        else:
            cur.execute("""UPDATE public.fault_findings
                           SET last_seen = NOW(), occurrences = occurrences + 1,
                               rule_severity = %s, summary = %s, evidence = %s
                           WHERE id = %s""",
                        (new_sev, f["summary"], json.dumps(f["evidence"], default=str), fid))
        result = "updated"
        if escalated:   # got worse: ask the AI again
            ai = explain(f, all_findings)
            write_ai(cur, fid, ai)
            result = "escalated"
    else:
        if is_episode:
            # How often has this signal done this lately? Repeats are worth a proper look.
            cur.execute("""SELECT COUNT(*) FROM public.fault_findings
                           WHERE machine_id = %s AND finding_type = %s
                             AND first_seen > NOW()::timestamp - INTERVAL '24 hours'""",
                        (f["machine_id"], f["finding_type"]))
            episodes = cur.fetchone()[0] + 1
            f["evidence"]["episodes_last_24h"] = episodes
            if episodes >= REF["recurring_episodes"]:
                f["severity"] = "medium"
        ai = explain(f, all_findings)   # the AI sees the measurements and count, not our verdict
        if is_episode:
            f["summary"] += (f" Episode {f['evidence']['episodes_last_24h']} of this kind in 24 h: "
                             f"a recurring pattern worth investigating."
                             if f["severity"] == "medium" else " Logged for review; watch for a repeat.")
        cur.execute("""INSERT INTO public.fault_findings
                       (machine_id, finding_type, rule_severity, summary, evidence, status,
                        ai_likely_cause, ai_severity, ai_what_to_check, ai_confidence, ai_model, ai_seconds, ai_error)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (f["machine_id"], f["finding_type"], f["severity"], f["summary"],
                     json.dumps(f["evidence"], default=str), "watch" if is_episode else "active",
                     ai["likely_cause"], ai["severity"], ai["what_to_check"], ai["confidence"],
                     ai["model"], ai["seconds"], ai["error"]))
        result = "new"

    if is_episode and f.get("closes"):
        # The original alarm for this signal is over: close it with how it ended.
        cur.execute("""UPDATE public.fault_findings SET status = %s
                       WHERE machine_id = %s AND finding_type = ANY(%s) AND status = 'active'
                         AND last_seen > NOW()::timestamp - INTERVAL '90 minutes'""",
                    (f["closed_status"], f["machine_id"], f["closes"]))
        if cur.rowcount:
            print(f"      closed {cur.rowcount} earlier finding(s) as '{f['closed_status']}'", flush=True)
    return result, ai


def write_ai(cur, fid, ai):
    cur.execute("""UPDATE public.fault_findings SET ai_likely_cause = %s, ai_severity = %s,
                   ai_what_to_check = %s, ai_confidence = %s, ai_model = %s, ai_seconds = %s, ai_error = %s
                   WHERE id = %s""",
                (ai["likely_cause"], ai["severity"], ai["what_to_check"], ai["confidence"], ai["model"],
                 ai["seconds"], ai["error"], fid))


def print_ai(ai):
    if not ai:
        return
    if ai["error"]:
        print(f"      AI: (no answer) {ai['error']}", flush=True)
    else:
        print(f"      AI ({ai['seconds']}s): cause = {ai['likely_cause']} | severity = {ai['severity']} "
              f"| confidence = {ai['confidence']}", flush=True)
        print(f"      AI check: {ai['what_to_check']}", flush=True)


def main():
    import psycopg2
    dry = "--dry-run" in sys.argv
    conn = psycopg2.connect(**PG)
    try:
        with conn.cursor() as cur:
            if not dry:
                cur.execute(TABLE_SQL)
                conn.commit()
            cur.execute("SELECT NOW()::timestamp")
            now = cur.fetchone()[0]
            cur.execute(FETCH_SQL, (LOOKBACK_MINUTES,))
            rows = [dict(zip(COLS, r)) for r in cur.fetchall()]

        found = detect_all(rows, now)
        print(f"Fault finder {'DRY RUN ' if dry else ''}at {now:%Y-%m-%d %H:%M:%S} UTC | "
              f"{len(rows)} readings checked | {len(found)} finding(s) | AI: "
              f"{OLLAMA_MODEL if AI_ENABLED else 'off'}", flush=True)

        for f in found:
            print(f"  [{f['severity'].upper():6}] {f['machine_id']} / {f['finding_type']}: {f['summary']}", flush=True)
            if dry:
                print_ai(explain(f, found))
                continue
            with conn.cursor() as cur:
                status, ai = save(cur, f, found)
            conn.commit()
            print(f"      -> {status}", flush=True)
            print_ai(ai)
        if not found:
            print("  All clear.", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
