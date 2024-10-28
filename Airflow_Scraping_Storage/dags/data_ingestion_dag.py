from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import boto3
import os

# Define default_args for the DAG
default_args = {
    "owner": "data_pipeline",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# Initialize the DAG
dag = DAG(
    "data_ingestion_pipeline",
    default_args=default_args,
    description="A simple data ingestion pipeline",
    schedule_interval=timedelta(days=1),
    start_date=datetime(2023, 1, 1),
    catchup=False,
)

# Define the scraping function
def scrape_data():
    # Set up Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = "/usr/bin/google-chrome"

    # Set up Chrome service to use the correct chromedriver path
    service = Service(executable_path="/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Add your scraping code here
    driver.get("https://rpc.cfainstitute.org/en/research-foundation/publications#sort=%40officialz32xdate%20descending&f:SeriesContent=[Research%20Foundation]")  # Replace with your target URL
    data = driver.page_source
    driver.quit()
    return data

# Define the task for scraping and uploading to S3
def scrape_and_store_data():
    data = scrape_data()

    # Set up S3 client
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name="us-east-1",
    )

    # Upload data to S3
    s3.put_object(
        Bucket="cfai-data",  # Replace with your S3 bucket name
        Key="data/scraped_data.html",
        Body=data,
    )

# Define the PythonOperator to call the scraping and uploading function
scrape_and_upload_task = PythonOperator(
    task_id="scrape_and_upload_to_s3",
    python_callable=scrape_and_store_data,
    dag=dag,
)

# Set task sequence
scrape_and_upload_task
