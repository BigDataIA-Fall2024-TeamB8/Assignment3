from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
import fitz  # PyMuPDF for PDF text extraction
from pinecone import Pinecone, ServerlessSpec
import boto3
import snowflake.connector
import requests
import tempfile
import os
import re

# Pinecone, Snowflake, OpenAI, and AWS S3 configurations
PINECONE_API_KEY = "pcsk_7Fp8Fo_8mCgGW2pWn8Eq9k6afeaoJL17KQ7wnFNvAwZpnHfDz53kg8TdBA5EVz7JCJC2Tq"
PINECONE_ENVIRONMENT = "us-east-1"
INDEX_NAME = "document-search"
EMBEDDING_DIMENSION = 1536
OPENAI_API_KEY = "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"
SNOWFLAKE_ACCOUNT = "srjvlcu-job01319"
SNOWFLAKE_USER = "SathvikV"
SNOWFLAKE_PASSWORD = "Bal27inferno$"
SNOWFLAKE_DATABASE = "CFAI_DATA"
SNOWFLAKE_SCHEMA = "CFAI_Data_Schema"
SNOWFLAKE_TABLE = "CFAI_Details"
S3_BUCKET_NAME = "cfai-data"
AWS_ACCESS_KEY_ID = "AKIAXEFUNUXJHBN2Z7SY"
AWS_SECRET_ACCESS_KEY = "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"

# Initialize clients
pc = Pinecone(api_key=PINECONE_API_KEY)
s3_client = boto3.client(
    's3',
    region_name="us-east-1",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002", openai_api_key=OPENAI_API_KEY)

# Set up Pinecone
spec = ServerlessSpec(cloud="aws", region=PINECONE_ENVIRONMENT)
if INDEX_NAME not in pc.list_indexes().names():
    pc.create_index(name=INDEX_NAME, dimension=EMBEDDING_DIMENSION, metric="cosine", spec=spec)
index = pc.Index(INDEX_NAME)

# Helper functions
def connect_snowflake():
    return snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA
    )

def get_presigned_url(s3_path: str):
    object_key = s3_path.replace(f"s3://{S3_BUCKET_NAME}/", "")
    return s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET_NAME, 'Key': object_key}, ExpiresIn=3600)

def sanitize_title(title):
    """Sanitize title to make it ASCII-compliant for Pinecone indexing."""
    title_ascii = title.encode("ascii", "ignore").decode()
    return re.sub(r'\W+', '_', title_ascii)

def extract_text_with_pymupdf(pdf_url):
    """Download and extract text from PDF using PyMuPDF."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
        response = requests.get(pdf_url)
        if response.status_code == 200:
            tmp_pdf.write(response.content)
        else:
            print(f"Failed to download PDF from URL: {pdf_url}")
            return ""
        
        tmp_pdf_path = tmp_pdf.name

    text = ""
    try:
        doc = fitz.open(tmp_pdf_path)
        for page_num in range(doc.page_count):
            page = doc[page_num]
            page_text = page.get_text("text")
            if page_text.strip():
                text += page_text + "\n"
        doc.close()
    except Exception as e:
        print(f"Error processing PDF with PyMuPDF: {e}")
    finally:
        os.remove(tmp_pdf_path)
    
    return text

def load_documents_into_pinecone():
    """Load documents from Snowflake, chunk and embed PDF content, and store in Pinecone."""
    conn = connect_snowflake()
    cur = conn.cursor()
    cur.execute(f"SELECT title, pdf_link FROM {SNOWFLAKE_TABLE}")
    rows = cur.fetchall()

    for row in rows:
        title, pdf_link = row
        sanitized_title = sanitize_title(title)
        presigned_pdf_url = get_presigned_url(pdf_link)

        # Extract text from PDF
        pdf_text = extract_text_with_pymupdf(presigned_pdf_url)

        if not pdf_text.strip():
            print(f"Warning: Could not extract text from PDF '{title}'. Skipping.")
            continue

        # Split text into chunks
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=200)
        chunks = text_splitter.split_text(pdf_text)

        for idx, chunk in enumerate(chunks):
            # Embed each chunk
            embedding = embeddings.embed_query(chunk)
            # Store embedding in Pinecone with metadata
            metadata = {"title": title, "chunk_id": idx, "pdf_link": pdf_link}
            vector_id = f"{sanitized_title}-{idx}"
            index.upsert([(vector_id, embedding, metadata)])
            print(f"Indexed chunk {idx} for title '{title}'")

    cur.close()
    conn.close()

# Airflow DAG
default_args = {
    'owner': 'airflow',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'pdf_indexing_to_pinecone',
    default_args=default_args,
    description='DAG to index PDFs to Pinecone',
    schedule_interval=timedelta(days=1),
    start_date=datetime(2023, 1, 1),
    catchup=False,
) as dag:

    index_documents_task = PythonOperator(
        task_id='index_documents_to_pinecone',
        python_callable=load_documents_into_pinecone,
    )

index_documents_task
