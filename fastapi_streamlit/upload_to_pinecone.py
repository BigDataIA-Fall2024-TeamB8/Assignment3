import os
import requests
import tempfile
from datetime import datetime
import re
from pathlib import Path
from langchain_community.embeddings import OpenAIEmbeddings
from langchain.embeddings.openai import OpenAIEmbeddings
from pinecone import Pinecone, ServerlessSpec
import boto3
import snowflake.connector
import pymupdf  # PyMuPDF for PDF text extraction
from llama_parse import LlamaParse  # LlamaParse for multimodal text/image extraction
from llama_index.core.schema import TextNode
from typing import List
from dotenv import load_dotenv


load_dotenv()


# Configure Pinecone, OpenAI, and AWS S3 using environment variables
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT")
NEW_INDEX_NAME = os.getenv("NEW_INDEX_NAME")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Initialize Pinecone client and create a new index if it doesn't exist
pc = Pinecone(api_key=PINECONE_API_KEY)
spec = ServerlessSpec(cloud="aws", region=PINECONE_ENVIRONMENT)
if NEW_INDEX_NAME not in pc.list_indexes().names():
    pc.create_index(name=NEW_INDEX_NAME, dimension=EMBEDDING_DIMENSION, metric="cosine", spec=spec)
index = pc.Index(NEW_INDEX_NAME)

# S3 client for handling document downloads
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Initialize OpenAI embeddings
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002", openai_api_key=OPENAI_API_KEY)

# Helper functions for PDF processing
def get_presigned_url(s3_path: str):
    object_key = s3_path.replace(f"s3://{S3_BUCKET_NAME}/", "")
    return s3_client.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET_NAME, 'Key': object_key}, ExpiresIn=3600)

def extract_text_and_images(pdf_path: str):
    """Extract text and images from PDF."""
    parser = LlamaParse(result_type="markdown", use_vendor_multimodal_model=True, vendor_multimodal_model_name="anthropic-sonnet-3.5")
    json_result = parser.get_json_result(pdf_path)
    return json_result[0]["pages"]

def download_pdf_from_s3(s3_path: str):
    url = get_presigned_url(s3_path)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
        response = requests.get(url)
        tmp_pdf.write(response.content)
        return tmp_pdf.name

def get_image_files(image_dir: Path) -> List[Path]:
    return sorted([file for file in image_dir.iterdir() if file.is_file()], key=lambda f: int(re.search(r"-(\d+)\.jpg$", f.name).group(1)))

def store_multimodal_to_pinecone(pages, title, pdf_link):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=200)
    
    for idx, page in enumerate(pages):
        text = page["md"]
        images = page.get("images", [])
        
        # Chunk text
        chunks = text_splitter.split_text(text)
        
        for chunk_idx, chunk in enumerate(chunks):
            # Create unique vector_id
            vector_id = f"{title}_page{idx+1}_chunk{chunk_idx}_{datetime.now().timestamp()}"
            metadata = {
                "title": title,
                "pdf_link": pdf_link,
                "page": idx + 1,
                "chunk_index": chunk_idx,
                "parsed_text_markdown": chunk,
                "images": images  # Attach images if available
            }
            # Get embedding and upsert
            embedding = embeddings.embed_query(chunk)
            index.upsert([(vector_id, embedding, metadata)])
            print(f"Indexed chunk {chunk_idx} for page {idx + 1} of '{title}'")

def process_publication(s3_path: str, title: str):
    pdf_path = download_pdf_from_s3(s3_path)
    pages = extract_text_and_images(pdf_path)
    store_multimodal_to_pinecone(pages, title, s3_path)
    os.remove(pdf_path)  # Clean up the temporary file

# Example of running the script
if __name__ == "__main__":
    # Replace with the path and title for your test publication in S3
    test_s3_path = "s3://cfai-data/path_to_your_test_pdf.pdf"
    test_title = "Sample Publication for Multimodal Testing"
    
    process_publication(test_s3_path, test_title)


