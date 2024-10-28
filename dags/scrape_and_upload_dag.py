from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import logging

# Import the function directly if already in the `dags` folder
from scraper_to_s3 import scrape_and_upload

# Default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'retries': 1,
}

# Define the DAG
with DAG(
    'scrape_and_upload_dag',
    default_args=default_args,
    description='A DAG to scrape CFA publications and upload to S3',
    schedule_interval=None,
    start_date=datetime(2023, 10, 1),
    catchup=False  # Optional: prevents backfill for past dates
) as dag:

    scrape_and_upload_task = PythonOperator(
        task_id='scrape_and_upload_task',
        python_callable=scrape_and_upload,
    )

    # Explicitly end with the task if desired
    scrape_and_upload_task
