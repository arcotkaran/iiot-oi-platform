"""
Fault analysis: every 10 minutes, detect faults in recent telemetry with rule-based
checks, have a local LLM (Ollama) explain each new finding, and store the results
in public.fault_findings for Grafana.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="fault_analysis",
    description="Rule-based fault detection + local-AI explanation, every 10 minutes",
    schedule="*/10 * * * *",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    default_args={"owner": "factory", "retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["factory", "ai"],
) as dag:
    BashOperator(
        task_id="detect_and_explain",
        bash_command="python /opt/airflow/analyzer/fault_finder.py",
        execution_timeout=timedelta(minutes=8),
    )
