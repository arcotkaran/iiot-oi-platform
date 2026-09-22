FROM apache/airflow:2.9.0
# dbt was hand-installed inside the old container; bake the same versions into the image
RUN pip install --no-cache-dir dbt-core==1.11.9 dbt-postgres==1.10.0
