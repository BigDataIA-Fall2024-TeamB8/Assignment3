import boto3
import snowflake.connector
import json

# Load environment variables for sensitive information
SNOWFLAKE_USER = os.getenv('SNOWFLAKE_USER')
SNOWFLAKE_PASSWORD = os.getenv('SNOWFLAKE_PASSWORD')
SNOWFLAKE_ACCOUNT = os.getenv('SNOWFLAKE_ACCOUNT')
SNOWFLAKE_WAREHOUSE = os.getenv('SNOWFLAKE_WAREHOUSE')
SNOWFLAKE_DATABASE = os.getenv('SNOWFLAKE_DATABASE')
SNOWFLAKE_SCHEMA = os.getenv('SNOWFLAKE_SCHEMA')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
bucket_name = os.getenv('BUCKET_NAME', 'cfai-data')  # Default bucket name if not set

# Connecting to Snowflake
print("Connecting to Snowflake...")
try:
    conn = snowflake.connector.connect(
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        account=SNOWFLAKE_ACCOUNT,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA,
        insecure_mode=True  # This may be removed based on your Snowflake configuration
    )
    cursor = conn.cursor()
    print("Connected to Snowflake successfully.")
except Exception as e:
    print("Failed to connect to Snowflake:", e)

# S3 connection setup
print("Connecting to S3...")
try:
    s3 = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    print("Connected to S3 successfully.")
except Exception as e:
    print("Failed to connect to S3:", e)

# Use the bucket name for any S3 operations
print(f"Bucket name set to: {bucket_name}")

# List folders in S3 bucket
print(f"Listing folders in S3 bucket '{bucket_name}'...")
response = s3.list_objects_v2(Bucket=bucket_name, Delimiter='/')
for prefix in response.get('CommonPrefixes', []):
    folder_name = prefix['Prefix'].strip('/')
    id = folder_name.split('_')[0]  # Extract the ID from the folder name (first four digits)
    print(f"\nProcessing folder: {folder_name}, ID: {id}")

    # Initialize variables
    title = None
    summary = None
    image_link = None
    pdf_link = None

    # List files in each folder
    folder_objects = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix['Prefix'])
    for obj in folder_objects.get('Contents', []):
        file_key = obj['Key']
        print(f"Found file: {file_key}")

        # Assign links based on file type
        if file_key.endswith('.jpg'):
            image_link = f's3://{bucket_name}/{file_key}'
            print(f"Image link set: {image_link}")
        elif file_key.endswith('.pdf'):
            pdf_link = f's3://{bucket_name}/{file_key}'
            print(f"PDF link set: {pdf_link}")
        elif file_key.endswith('.json'):
            # Read JSON metadata file for title and summary
            print(f"Reading metadata from {file_key}...")
            try:
                obj_data = s3.get_object(Bucket=bucket_name, Key=file_key)
                metadata = json.loads(obj_data['Body'].read().decode('utf-8'))
                title = metadata.get('title')
                summary = metadata.get('summary') or "No summary available"  # Use a placeholder if summary is None
                print(f"Metadata extracted - Title: {title}, Summary: {summary}")
            except Exception as e:
                print(f"Failed to read metadata from {file_key}:", e)

    # Insert into Snowflake table
    if id and title and image_link and pdf_link:
        try:
            print("Inserting data into Snowflake...")
            cursor.execute("""
                INSERT INTO CFAI_TAB (ID, Title, Summary, Image_link, PDF_link)
                VALUES (%s, %s, %s, %s, %s)
            """, (id, title, summary, image_link, pdf_link))
            print("Data inserted successfully.")
        except Exception as e:
            print("Failed to insert data into Snowflake:", e)
    else:
        print("Skipping insertion due to missing data (required fields: ID, Title, Image_link, PDF_link).")

# Close the cursor and connection
print("Data load completed successfully.")
cursor.close()
conn.close()
print("Snowflake connection closed.")
