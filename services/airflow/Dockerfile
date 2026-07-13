# Airflow image for the self_improvement_daily DAG.
#
# Pinned to Airflow 2.10.x on purpose: the DAG uses the 2.9/2.10 dataset API
# (airflow.datasets.Dataset + DatasetOrTimeSchedule). Airflow 3.x renamed these
# to Asset / AssetOrTimeSchedule, so the DAG would fail to import there.
#
# The DAG imports command_center.improvement.discovery.dag_support, so the image
# carries command_center's runtime deps. The package itself is mounted live at
# /opt/airflow/repo/src (PYTHONPATH) by docker-compose, so DAG/code edits need no
# rebuild — only a dependency change requires rebuilding this image.
FROM apache/airflow:2.10.5

# command_center base runtime deps (kept in sync with pyproject [project].dependencies).
# Versioned floors match pyproject so the DAG parses against the same contracts.
RUN pip install --no-cache-dir \
    "pydantic>=2.10" \
    "pyyaml>=6.0" \
    "httpx>=0.28" \
    "pydantic-settings>=2.2" \
    "tenacity>=8.2"

ENV PYTHONPATH=/opt/airflow/repo/src
