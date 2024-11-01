from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, EmailStr
from typing import List, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone
from langchain_nvidia_ai_endpoints import ChatNVIDIA
import snowflake.connector
import pyodbc
from botocore.exceptions import BotoCoreError, ClientError
import os
import boto3
import base64
import logging
import time
from io import BytesIO
import requests
from datetime import datetime
from pdf2image import convert_from_bytes
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_pine")

# Initialize FastAPI app
app = FastAPI()

# Constants and configurations loaded from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
INDEX_NAME = os.getenv("INDEX_NAME")
RESEARCH_NOTES_INDEX_NAME = os.getenv("RESEARCH_NOTES_INDEX_NAME")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", 1536))

# Database connection settings loaded from environment variables
RDS_ENDPOINT = os.getenv("RDS_ENDPOINT")
RDS_USERNAME = os.getenv("RDS_USERNAME")
RDS_PASSWORD = os.getenv("RDS_PASSWORD")
RDS_DATABASE = os.getenv("RDS_DATABASE")

CONNECTION_STRING = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={RDS_ENDPOINT},1433;"
    f"DATABASE={RDS_DATABASE};"
    f"UID={RDS_USERNAME};"
    f"PWD={RDS_PASSWORD}"
)

# AWS S3 Client initialized using environment variables
s3_client = boto3.client(
    's3',
    region_name="us-east-1",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

# Initialize OpenAI, Pinecone, and NVIDIA AI components using environment variables
embeddings = OpenAIEmbeddings(model="text-embedding-ada-002", openai_api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)
research_notes_index = pc.Index(RESEARCH_NOTES_INDEX_NAME)

# NVIDIA client using environment variables for API key and model parameters
client = ChatNVIDIA(
    model=os.getenv("NVIDIA_MODEL", "meta/llama-3.2-3b-instruct"),
    api_key=os.getenv("NVIDIA_API_KEY"),
    temperature=float(os.getenv("NVIDIA_TEMPERATURE", 0.2)),
    top_p=float(os.getenv("NVIDIA_TOP_P", 0.7)),
    max_tokens=int(os.getenv("NVIDIA_MAX_TOKENS", 1024)),
    timeout=int(os.getenv("NVIDIA_TIMEOUT", 20))
)

# JWT token handling
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dummy vector for metadata-only queries
dummy_vector = [0.0] * EMBEDDING_DIMENSION

# Prompts
system_prompt = """\
You are a report generation assistant tasked with producing a comprehensive, well-detailed report.
Given parsed context, provide a detailed report with interleaved text and images. For each visual reference, include a descriptive paragraph that contextualizes the image within the explanation. Each image should reinforce key points, and all text should fully explain the data, trends, and nuances illustrated by the visuals.
"""

system_prompt_notes = """\
You are a helpful assistant that provides answers based on relevant research notes.
Given the context below, respond to the question with a concise, informative answer. Use information from the research notes to support your response.
"""

# JWT token and authentication functions
def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta if expires_delta else datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username

def get_db_connection():
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        return conn
    except pyodbc.Error as e:
        logger.error("Database connection failed: %s", e)
        raise HTTPException(status_code=500, detail="Database connection failed")


# Retry function for NVIDIA API
def nvidia_api_retry(prompt, max_retries=3):
    retries = 0
    while retries < max_retries:
        try:
            logger.info(f"Attempt {retries + 1} for NVIDIA API.")
            response = client.stream([{"role": "user", "content": prompt}])
            return "".join(chunk.content for chunk in response)
        except Exception as e:
            retries += 1
            logger.warning(f"Retry {retries}/{max_retries} due to error: {e}")
            time.sleep(2)
    raise HTTPException(status_code=500, detail="NVIDIA API failed after retries.")

# Models
class TextBlock(BaseModel):
    text: str = Field(..., description="Text for this block.")

class ImageBlock(BaseModel):
    file_path: str = Field(..., description="File path to the image.")

class ReportOutput(BaseModel):
    blocks: List[Union[TextBlock, ImageBlock]] = Field(..., description="A list of text and image blocks.")

class Document(BaseModel):
    title: str
    summary: str
    pdf_link: str
    image_link: str

class DocumentSummary(BaseModel):
    title: str
    summary: str

class ResearchNoteRequest(BaseModel):
    text: str

class Token(BaseModel):
    access_token: str
    token_type: str

# User model for signup
class User(BaseModel):
    username: str
    password: str
    email: EmailStr

class ResearchNote(BaseModel):
    title: str
    note: str
    document_id: Union[str, None] = None  # Optional field for document ID

class DerivedNoteRequest(BaseModel):
    note_content: str


# Helper function to connect to Snowflake
def connect_snowflake():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA")
    )

# Helper function to generate a presigned URL for S3 objects
def get_presigned_url(s3_path: str):
    bucket_name = os.getenv("S3_BUCKET_NAME", "cfai-data")  # Default bucket name if not set
    object_key = s3_path.replace(f"s3://{bucket_name}/", "")
    s3_client = boto3.client(
        's3',
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1")  # Default region if not set
    )
    return s3_client.generate_presigned_url('get_object', Params={'Bucket': bucket_name, 'Key': object_key}, ExpiresIn=3600)

@app.post("/signup")
def signup(user: User):
    conn = None
    try:
        hashed_password = hash_password(user.password)
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user already exists
        cursor.execute("SELECT * FROM Users WHERE username = ?", user.username)
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="User already exists")

        # Insert new user
        cursor.execute("INSERT INTO Users (username, password, Email_ID) VALUES (?, ?, ?)",
                       user.username, hashed_password, user.email)
        conn.commit()
    except pyodbc.Error as e:
        logger.error("Signup failed: %s", e)
        raise HTTPException(status_code=500, detail="Signup failed")
    finally:
        if conn:
            conn.close()
    return {"message": "User signed up successfully!"}

# Login endpoint
class Token(BaseModel):
    access_token: str
    token_type: str

@app.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM Users WHERE username = ?", form_data.username)
        user_record = cursor.fetchone()

        if not user_record or not verify_password(form_data.password, user_record[0]):
            raise HTTPException(status_code=400, detail="Invalid credentials")

        access_token = create_access_token(data={"sub": form_data.username}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        return {"access_token": access_token, "token_type": "bearer"}
    except pyodbc.Error as e:
        logger.error("Login failed: %s", e)
        raise HTTPException(status_code=500, detail="Login failed")
    finally:
        if conn:
            conn.close()



# Endpoint to generate embedding for a research note
@app.post("/generate_embedding", response_model=dict, dependencies=[Depends(get_current_user)])
def generate_embedding(request: ResearchNoteRequest):
    embedding = embeddings.embed_query(request.text)
    return {"embedding": embedding}



@app.post("/store_research_note", response_model=dict, dependencies=[Depends(get_current_user)])
def store_research_note(note: ResearchNote):
    logger.info("Received request to store research note.")
    try:
        logger.info(f"Generating embedding for note: {note.note[:50]}...")
        embedding = embeddings.embed_query(note.note)
        
        metadata = {
            "title": note.title,
            "note": note.note,
            "document_id": note.document_id or note.title
        }

        # Sanitize vector ID to be ASCII-compatible
        note_id = urllib.parse.quote(f"{note.title}_{datetime.now().timestamp()}")
        
        # Upsert to Pinecone
        logger.info(f"Attempting to upsert note with ID: {note_id}")
        research_notes_index.upsert([(note_id, embedding, metadata)])
        
        logger.info("Research note stored successfully in Pinecone.")
        return {"message": "Research note stored successfully."}
    except Exception as e:
        logger.error(f"Error storing research note for title '{note.title}': {e}")
        raise HTTPException(status_code=500, detail="Error storing research note.")



# Endpoint to fetch all research notes for a specific publication
@app.get("/research_notes/{title}", response_model=dict, dependencies=[Depends(get_current_user)])
def get_research_notes_by_title(title: str):
    try:
        results = research_notes_index.query(
            vector=dummy_vector,
            filter={"title": {"$eq": title}},
            top_k=100,
            include_metadata=True
        )
        notes = [{"note": match.metadata.get("note", ""), "title": match.metadata.get("title", "Unknown")} for match in results.matches]
        return {"results": notes}
    except Exception as e:
        logger.error(f"Error fetching research notes for title '{title}': {e}")
        raise HTTPException(status_code=500, detail="Error fetching research notes.")

# Updated search_research_notes with save option
@app.get("/search_research_notes", response_model=ReportOutput, dependencies=[Depends(get_current_user)])
def search_research_notes(query: str):
    try:
        query_embedding = embeddings.embed_query(query)
        results = research_notes_index.query(vector=query_embedding, top_k=5, include_metadata=True)
        
        if not results.matches:
            return ReportOutput(blocks=[TextBlock(text="No relevant context found for this question.")])

        # Use the report prompt to format the response in report style
        context_text = "\n".join(
            f"{match.metadata.get('note', '')} (Source: {match.metadata.get('title', 'Unknown')})"
            for match in results.matches
        )
        
        # Construct a report-based prompt using `system_prompt`
        qa_prompt = f"{system_prompt}\n\nContext:\n{context_text}\n\nQuestion: {query}"
        answer = nvidia_api_retry(qa_prompt)
        
        return ReportOutput(blocks=[TextBlock(text=answer)])

    except Exception as e:
        logger.error(f"Error in search research notes Q&A: {e}")
        raise HTTPException(status_code=500, detail="Error processing research notes query.")


# Endpoint to save derived notes to the research notes index
@app.post("/save_derived_note", response_model=dict, dependencies=[Depends(get_current_user)])
def save_derived_note_endpoint(request: DerivedNoteRequest):
    logger.info(f"Received request to save derived note with content: {request.note_content[:100]}...")
    try:
        # Generate embedding for the derived note
        derived_note_embedding = embeddings.embed_query(request.note_content)
        logger.info("Embedding generated for derived note.")

        # Metadata for Pinecone upsert
        metadata = {
            "title": "Derived Note",
            "note": request.note_content
        }
        vector_id = f"derived_note_{datetime.utcnow().timestamp()}"
        
        # Upsert to Pinecone
        logger.info("Attempting to upsert derived note into Pinecone.")
        research_notes_index.upsert([(vector_id, derived_note_embedding, metadata)])
        logger.info("Derived note successfully upserted to Pinecone.")
        
        return {"message": "Derived note saved successfully"}
    except Exception as e:
        logger.error(f"Error saving derived note: {e}")
        raise HTTPException(status_code=500, detail="Failed to save derived note")


@app.get("/search_publication_notes", response_model=ReportOutput, dependencies=[Depends(get_current_user)])
def search_publication_notes(query: str, title: str):
    try:
        # Generate the query embedding
        query_embedding = embeddings.embed_query(query)

        # Perform a Pinecone query, filtering by title
        results = research_notes_index.query(
            vector=query_embedding,
            top_k=5,
            filter={"title": {"$eq": title}},  # Filter by publication title
            include_metadata=True
        )

        if not results.matches:
            return ReportOutput(blocks=["No relevant context found for this question."])

        # Gather context from results for the prompt
        context_text = "\n".join(
            f"{match.metadata.get('note', '')} (Source: {match.metadata.get('title', 'Unknown')})"
            for match in results.matches
        )

        # Use NVIDIA LLM to generate a detailed report
        qa_prompt = f"{system_prompt}\n\nContext:\n{context_text}\n\nQuestion: {query}"
        answer = nvidia_api_retry(qa_prompt)

        return ReportOutput(blocks=[{"text": answer}])

    except Exception as e:
        logger.error(f"Error in search publication-specific notes: {e}")
        raise HTTPException(status_code=500, detail="Error processing publication-specific query.")



# Endpoint for retrieving list of document titles
@app.get("/documents", response_model=List[str], dependencies=[Depends(get_current_user)])
def get_documents():
    try:
        conn = connect_snowflake()
        cur = conn.cursor()
        cur.execute("SELECT title FROM CFAI_TAB")
        titles = [row[0] for row in cur.fetchall()]
        return titles
    except Exception as e:
        logger.error("Error retrieving document titles: %s", e)
        raise HTTPException(status_code=500, detail="Error retrieving document titles.")
    finally:
        cur.close()
        conn.close()

# Endpoint to get detailed information about a selected publication
@app.get("/document/{title}", response_model=Document, dependencies=[Depends(get_current_user)])
def get_document_details(title: str):
    try:
        conn = connect_snowflake()
        cur = conn.cursor()
        cur.execute("SELECT title, summary, pdf_link, image_link FROM CFAI_TAB WHERE title = %s", (title,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found.")
        pdf_link = get_presigned_url(row[2])
        image_link = get_presigned_url(row[3])
        return Document(title=row[0], summary=row[1], pdf_link=pdf_link, image_link=image_link)
    except Exception as e:
        logger.error("Error retrieving document details: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

# Additional protected endpoints continue similarly with authentication via `Depends(get_current_user)` as needed.


@app.get("/document/{title}/generate_summary", response_model=ReportOutput, dependencies=[Depends(get_current_user)])
def generate_summary(title: str):
    try:
        # Query Pinecone for broader content on the title
        result = index.query(
            vector=embeddings.embed_query("introduction " + title),
            top_k=5,  # Increase number of chunks for richer content
            include_metadata=True
        )

        # Check for Pinecone matches
        if not result.matches:
            logger.warning("No relevant content found in Pinecone for title: %s", title)
            raise HTTPException(status_code=404, detail="No relevant content found.")

        # Update the system prompt for a concise summary
        concise_prompt = (
            "Provide a concise summary of the following content in two to three paragraphs, "
            "highlighting key points without formatting it as a report."
        )

        # Construct a summary prompt for NVIDIA with available context
        introduction_content = " ".join(match.metadata.get("text_snippet", "") for match in result.matches)
        summary_prompt = f"{concise_prompt}\n\nContent:\n{introduction_content}"
        logger.info("Prompt length for NVIDIA API: %d characters", len(summary_prompt))

        # Get summary from NVIDIA API
        summary_text = nvidia_api_retry(summary_prompt)
        logger.info("Received summary from NVIDIA API")

        # Prepare the response with only the summary text and add images from each match
        report_blocks = [TextBlock(text=summary_text)]
        for match in result.matches:
            for url in match.metadata.get("image_urls", []):
                report_blocks.append(ImageBlock(file_path=url))

        return ReportOutput(blocks=report_blocks)

    except HTTPException as e:
        # Reraise HTTPException for correct error handling
        raise e
    except Exception as e:
        logger.error(f"Unexpected error generating summary for title '{title}': {str(e)}")
        raise HTTPException(status_code=500, detail="Error generating summary")



@app.get("/document/{title}/qa", response_model=ReportOutput, dependencies=[Depends(get_current_user)])
def document_specific_qa(title: str, question: str):
    try:
        # Embed the question to retrieve relevant context
        question_embedding = embeddings.embed_query(question)
        result = index.query(
            vector=question_embedding,
            top_k=10,  # Gather relevant chunks
            include_metadata=True
        )

        if not result.matches:
            logger.warning("No matches found for the query in Pinecone.")
            return ReportOutput(blocks=[TextBlock(text="No relevant context found for this question. Try rephrasing or broadening your query.")])

        # Construct context and form the report-based prompt
        context = "\n".join(match.metadata.get("text_snippet", "") for match in result.matches[:5])
        qa_prompt = f"{system_prompt}\n\nBased on the following context from '{title}':\n\n{context}\n\nQuestion: {question}"

        # Query NVIDIA API for a detailed response
        answer = nvidia_api_retry(qa_prompt)
        report_blocks = [TextBlock(text=answer)]

        # Include images where available in the response
        for match in result.matches[:3]:  # Add images from top 3 relevant chunks
            for url in match.metadata.get("image_urls", []):
                report_blocks.append(ImageBlock(file_path=url))

        return ReportOutput(blocks=report_blocks)

    except Exception as e:
        logger.error(f"Error in document-specific QA: {e}")
        raise HTTPException(status_code=500, detail="Error processing QA request.")



# Global Q&A endpoint with a streamlined query
@app.get("/qa", response_model=ReportOutput, dependencies=[Depends(get_current_user)])
def global_qa(question: str):
    try:
        logger.info("Starting global Q&A.")
        question_embedding = embeddings.embed_query(question)
        result = index.query(vector=question_embedding, top_k=5, include_metadata=True)

        if not result.matches:
            return ReportOutput(blocks=[TextBlock(text="No relevant context found for this question.")])

        # Construct a concise context from the first few matches
        context_text = "\n".join(
            f"{match.metadata.get('text_snippet', '')} (Source: {match.metadata.get('title', 'Unknown PDF')})"
            for match in result.matches[:3]  # Limit to 3 for efficiency
        )
        qa_prompt = f"{system_prompt}\n\nBased on the following context from relevant documents:\n\n{context_text}\n\nQuestion: {question}"

        # Query NVIDIA API
        answer = nvidia_api_retry(qa_prompt)
        report_blocks = [TextBlock(text=answer)]
        
        # Only the first image if available
        for match in result.matches[:1]:
            if "image_path" in match.metadata:
                report_blocks.append(ImageBlock(file_path=match.metadata["image_path"]))

        return ReportOutput(blocks=report_blocks)
    except Exception as e:
        logger.error("Error in global Q&A: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
