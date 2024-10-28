# Instructions for Setting Up Assignment 3

This repository contains the setup and code for Assignment 3, which includes Airflow DAGs for data ingestion and data scraping to S3.

GitHub Repository: [Assignment3 - BigDataIA-Fall2024-TeamB8](https://github.com/BigDataIA-Fall2024-TeamB8/Assignment3/tree/Sathvik)

## Repository Directory Structure

```plaintext
Airflow_Scraping_Storage/
dags/
postgres_data/
scripts/
.env
.gitignore
Dockerfile
docker-compose.yml
requirements.txt
README.md
```

# Steps to Set Up the Project

## 1 Clone the Repository
First, clone the repository to your local machine:

```bash
git clone https://github.com/BigDataIA-Fall2024-TeamB8/Assignment3.git
cd Assignment3
```

## 2. Set Up Environment Variables
Create a .env file in the root of the Assignment3 directory if it’s not already present. This file should contain environment variables such as AWS credentials and any API keys required for the application.

For example, your .env file might look like this:

```plaintext
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
```

Ensure that .env contains the correct variables for your environment. Do not commit this file to GitHub, as it contains sensitive information.

## 3. Install Docker (If Not Already Installed)
Make sure Docker is installed on your machine. You can download it from Docker's official website.

## 4. Build and Run Docker Containers
This project uses Docker Compose to set up the environment, including Airflow. To build and start the containers, run the following command from the project’s root directory:

```bash
docker-compose up --build
```
This will:


Build the Docker images specified in the Dockerfile.
Set up Airflow and any other dependencies.
Start the containers.
Note: The initial build may take some time.

## 5. Verify the Airflow Setup
Once the containers are up and running, you should be able to access the Airflow web interface at:

```plaintext
http://localhost:8080
```

Login credentials are usually:

Username: airflow
Password: airflow
Check the DAGs section in the Airflow interface to verify that your DAGs (data_ingestion_dag.py, scrape_and_upload_dag.py, scraper_to_s3.py) are visible and available.

Create an Airflow User Credential
If needed, create an Airflow user credential with the following command (replace with your values):

```bash
docker-compose exec webserver airflow users create --username <your_username> --firstname <FirstName> --lastname <LastName> --role Admin --email <email@example.com> --password <your_password>
```

## 6. Install Python Dependencies (Optional)
If you need to run scripts outside of Docker, install dependencies listed in requirements.txt:

```bash
pip install -r requirements.txt
```

## 7. Running the DAGs
Data Ingestion DAG: This DAG, defined in data_ingestion_dag.py, handles data ingestion tasks.
Scraper and Upload DAG: This DAG, defined in scrape_and_upload_dag.py, uses scraper_to_s3.py to scrape and upload data to S3.
To run a DAG:

Go to the Airflow web interface.
Switch on the DAG you want to run.
Airflow will start executing the tasks based on the DAG's schedule or on-demand if triggered manually.


## 8. Viewing Logs
Logs for each task are available in the Airflow web interface. Alternatively, you can check logs from the host machine in the logs directory.

## 9. Stopping the Containers
To stop the Docker containers, run:

```bash
docker-compose down
```
This will stop all running services.

