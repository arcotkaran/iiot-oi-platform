from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'factory',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='factory_dbt_hourly',
    description='Run dbt models every hour to refresh analytics',
    default_args=default_args,
    start_date=datetime(2026, 4, 28),
    schedule='@hourly',
    catchup=False,
    tags=['factory', 'dbt'],
) as dag:

    run_dbt = BashOperator(
        task_id='run_dbt_models',
        bash_command='/home/airflow/.local/bin/dbt run --profiles-dir /opt/airflow/.dbt --project-dir /opt/airflow/dbt',
    )

    test_dbt = BashOperator(
        task_id='test_dbt_models',
        bash_command='/home/airflow/.local/bin/dbt test --profiles-dir /opt/airflow/.dbt --project-dir /opt/airflow/dbt',
    
)
    run_dbt >> test_dbt
