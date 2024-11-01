import os
import streamlit as st
import requests
import json
import base64
import boto3
from botocore.exceptions import NoCredentialsError
from PIL import Image
import io
from dotenv import load_dotenv

load_dotenv()
# Set API URL, default to localhost
API_URL = os.getenv("API_URL", "http://localhost:8000")

# Initialize session state variables
if "token" not in st.session_state:
    st.session_state.token = None  
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "selected_document" not in st.session_state:
    st.session_state.selected_document = None
if "summary" not in st.session_state:
    st.session_state.summary = ""
if "qa_answer" not in st.session_state:
    st.session_state.qa_answer = ""
if "research_note" not in st.session_state:
    st.session_state.research_note = ""
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "signup_successful" not in st.session_state:
    st.session_state.signup_successful = False
if "ok_clicked" not in st.session_state:
    st.session_state.ok_clicked = False
if "derived_note_content" not in st.session_state:  # To store derived note content
    st.session_state.derived_note_content = ""


# Helper function to make requests with an optional token
def make_request(endpoint, method="GET", json=None, params=None):
    # Check if token is available; if not, prompt the user to log in
    if not st.session_state.token:
        st.warning("Please log in to access this feature.")
        return None

    url = f"{API_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    
    try:
        response = requests.request(method, url, headers=headers, json=json, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"Request failed: {e}")
        return None


# Authentication functions
def signup(username, password, email):
    data = {"username": username, "password": password, "email": email}
    response = requests.post(f"{API_URL}/signup", json=data)
    if response.status_code == 200:
        st.success("Signed up successfully!")
        st.session_state.signup_successful = True
    else:
        st.error(f"Error: {response.status_code} - {response.text}")

def login(username, password):
    data = {"username": username, "password": password}
    response = requests.post(f"{API_URL}/login", data=data)
    if response.status_code == 200:
        token = response.json().get("access_token")
        st.session_state.token = token  # Store token in session_state
        st.session_state.logged_in = True
        st.session_state.page = "Documents"
        st.rerun()
    else:
        st.error(f"Login failed: {response.status_code} - {response.text}")

# Logout function to reset session state
def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state.page = "Home"
    st.session_state.logged_in = False
    st.rerun()

# Display header with the app name and design
def display_header():
    st.markdown(
        """
        <div style='display: flex; align-items: center; padding: 10px;'>
            <h1 style='color: #007BFF;'>AI-based Document Exploration</h1>
        </div>
        """,
        unsafe_allow_html=True
    )

# Sidebar for navigation with unique keys for buttons
def display_sidebar():
    st.sidebar.title("Navigation")
    if st.session_state.logged_in:
        st.sidebar.button("🔓 Logout", on_click=logout, key="sidebar_logout")
        st.sidebar.button("Documents", on_click=lambda: st.session_state.update(page="Documents"), key="nav_documents")
        st.sidebar.button("Global Q&A", on_click=lambda: st.session_state.update(page="Global_QA"), key="nav_global_qa")
        st.sidebar.button("Research Notes", on_click=lambda: st.session_state.update(page="Research_Notes"), key="nav_research_notes")
        st.sidebar.button("Search All Research Notes", on_click=lambda: st.session_state.update(page="Search_All_Research_Notes"), key="nav_search_notes")
    else:
        st.sidebar.button("Login", on_click=lambda: st.session_state.update(page="Login"), key="nav_login")
        st.sidebar.button("Sign Up", on_click=lambda: st.session_state.update(page="SignUp"), key="nav_signup")


# Convert S3 links to HTTP links for display
def convert_s3_to_http(s3_link):
    bucket_name = "cfai-data"
    return s3_link.replace("s3://", f"https://{bucket_name}.s3.amazonaws.com/")

# Function to display the content from report blocks
def display_report(report_data):
    text_blocks = []
    for block in report_data.get("blocks", []):
        if "text" in block:
            text_blocks.append(block["text"])
        elif "file_path" in block:
            st.image(block["file_path"], caption="Related Image from Document", use_column_width=True)
    st.session_state.research_note = "\n".join(text_blocks)
    st.write(st.session_state.research_note)


def display_pdf_preview(title, start_page=1, end_page=10):
    response = requests.get(
        f"http://localhost:8009/preview_pdf/{title}",
        params={"start_page": start_page, "end_page": end_page},
        headers={"Authorization": f"Bearer {st.session_state.token}"}
    )
    if response.status_code == 200:
        images_base64 = response.json()
        for img_data in images_base64:
            img_bytes = base64.b64decode(img_data)
            img = Image.open(io.BytesIO(img_bytes))
            st.image(img)
    else:
        st.error("Failed to load PDF preview")


# Homepage content with an emoticon and description
def homepage_content():
    st.markdown(
        """
        <div style='font-weight: bold;'>
            <h2>👋 Welcome to the AI Document Explorer</h2>
            <p>Use our tool to analyze and extract insights from your documents with AI-powered assistance!</p>
        </div>
        """,
        unsafe_allow_html=True
    )

# Login page
def login_section():
    st.markdown("<h2>🔐 Login</h2>", unsafe_allow_html=True)
    username = st.text_input("👤 Username", key="login_username")
    password = st.text_input("🔑 Password", type="password", key="login_password")
    if st.button("Login", key="login_button"):
        login(username, password)

# Sign-up page with a success dialog box
def signup_section():
    st.markdown("<h2>📝 Sign Up</h2>", unsafe_allow_html=True)
    new_username = st.text_input("👤 New Username", key="signup_username")
    new_password = st.text_input("🔑 New Password", type="password", key="signup_password")
    email = st.text_input("📧 Email", key="signup_email")
    
    if not st.session_state.signup_successful:
        if st.button("Sign Up", key="signup_button"):
            signup(new_username, new_password, email)

    if st.session_state.signup_successful and not st.session_state.ok_clicked:
        st.success("User successfully registered!")
        if st.button("OK", key="signup_ok_button"):
            st.session_state.ok_clicked = True
            st.session_state.page = 'Login'
            st.rerun()

# Document selection, summary generation, and Q&A section for the selected document

def fetch_and_display_pdf(document_title):
    # Check if the token exists before proceeding
    if not st.session_state.token:
        st.warning("Please log in to view the PDF preview.")
        return

    try:
        # Fetch PDF data from FastAPI endpoint
        response = requests.get(
            f"{API_URL}/preview_pdf/{document_title}",
            headers={"Authorization": f"Bearer {st.session_state.token}"}
        )
        response.raise_for_status()
        pdf_base64 = response.json().get("pdf_base64")

        # Display PDF in an iframe within an expander
        pdf_viewer = st.expander("📄 Preview Selected PDF")
        with pdf_viewer:
            pdf_data_uri = f"data:application/pdf;base64,{pdf_base64}"
            st.markdown(f'<iframe src="{pdf_data_uri}" width="700" height="1000"></iframe>', unsafe_allow_html=True)
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching PDF for preview: {e}")




def documents_page():
    # Ensure user is logged in
    if not st.session_state.token:
        st.warning("Please log in to view documents.")
        return

    response = make_request("/documents")
    if response:
        documents = response
        selected_doc = st.selectbox("Select a Document", documents, index=0 if st.session_state.selected_document is None else documents.index(st.session_state.selected_document), key="select_document")
        
        if selected_doc:
            st.session_state.selected_document = selected_doc
            doc_details = make_request(f"/document/{selected_doc}")
            
            if doc_details:
                st.write(f"**Title:** {doc_details['title']}")
                st.write(f"**Summary:** {doc_details['summary']}")

                pdf_link = doc_details.get('pdf_link')
                if pdf_link:
                    st.markdown(f"[PDF Link]({pdf_link})", unsafe_allow_html=True)
                else:
                    st.error("PDF link not found.")
                
                # Display Image Link with download and preview
                image_url = convert_s3_to_http(doc_details['image_link'])
                st.markdown(f"[Image Link]({image_url})", unsafe_allow_html=True)
                st.image(image_url, caption="Document Image Preview", use_column_width=True)

                if st.button("Generate Summary", key="generate_summary_button"):
                    summary_response = make_request(f"/document/{doc_details['title']}/generate_summary")
                    if summary_response:
                        st.write("**Generated Summary:**")
                        display_report(summary_response)
                    else:
                        st.session_state.summary = "Summary generation failed."
                
                st.markdown("### Ask a Question about this Document")
                user_question = st.text_input("Enter your question", key="document_question")
                if st.button("Ask Document-Specific Question", key="document_specific_qa_button"):
                    qa_response = make_request(f"/document/{st.session_state.selected_document}/qa", params={"question": user_question})
                    if qa_response:
                        st.write("**Answer:**")
                        display_report(qa_response)
                    else:
                        st.error("Could not retrieve an answer.")
                
                if st.session_state.research_note:
                    if st.button("Validate Research Note", key="validate_note_button"):
                        validate_research_note()
                    if st.button("Delete Research Note", key="delete_note_button"):
                        st.session_state.research_note = ""
                        st.write("Research Note deleted.")
    else:
        st.error("Could not load documents")

# Function to validate research note
def validate_research_note():
    embedding = generate_embedding(st.session_state.research_note)
    metadata = {
        "title": st.session_state.selected_document,
        "note": st.session_state.research_note
    }
    store_in_pinecone(embedding, metadata)
    st.write("Research Note validated and stored.")

# Helper function to generate embedding using OpenAI API
def generate_embedding(text):
    response = make_request("/generate_embedding", method="POST", json={"text": text})
    return response.get("embedding") if response else None

# Helper function to store validated research notes in Pinecone
def store_in_pinecone(embedding, metadata):
    
    research_note_payload = {
        "title": metadata["title"],
        "note": metadata["note"]
    }
    
    
    
    # Send the request with the research note payload
    response = make_request("/store_research_note", method="POST", json=research_note_payload)
    
    if response:
        
        return response
    else:
        
        return None



def global_qa_section():
    st.markdown("## Global Q&A")
    user_question = st.text_input("Ask a question across all documents", key="global_qa_question")
    if st.button("Ask Global Question", key="global_qa_button"):
        qa_response = make_request("/qa", params={"question": user_question})
        if qa_response:
            st.write("**Answer:**")
            display_report(qa_response)
        else:
            st.error("Could not retrieve an answer.")








def research_notes_page():
    st.markdown("## Search Research Notes")
    publications = make_request("/documents")
    if publications:
        selected_publication = st.selectbox("Select a Publication", publications, key="select_publication")
        if selected_publication:
            # Display research notes for the selected publication
            research_notes = make_request(f"/research_notes/{selected_publication}")
            if research_notes:
                st.write(f"### Research Notes for '{selected_publication}':")
                for result in research_notes["results"]:
                    # Use the topic of the research note instead of the title in the expander
                    topic = result.get("note").splitlines()[0]  # Extract the first line as the topic
                    with st.expander(f"Note: {topic}"):
                        st.write(result["note"])
            else:
                st.error(f"No research notes found for '{selected_publication}'.")

            # Add search functionality within the selected publication's research notes
            st.markdown("## Publication-Specific Research Notes Q&A")
            search_query = st.text_input("Ask a question about research notes in this publication", key="publication_research_notes_query")
            
            if st.button("Search Publication-Specific Research Notes", key="search_publication_notes_button"):
                search_results = make_request(
                    "/search_publication_notes",
                    params={"query": search_query, "title": selected_publication}
                )
                
                if search_results:
                    derived_note_text = "\n".join(block["text"] if isinstance(block, dict) else block for block in search_results["blocks"])
                    st.write("### Answer:")
                    st.write(derived_note_text)
                    
                    # Store the derived note in session state for potential saving
                    st.session_state["derived_note_content"] = derived_note_text

                    # Add the "Save Derived Note" button
                    if st.button("Save Derived Note", key="save_derived_note_button"):
                        save_derived_note()  # Call the helper function to save the derived note
                else:
                    st.error("No relevant answer found.")
    else:
        st.error("Failed to load publications.")

def save_derived_note():
    # Check if derived note content is available in session state
    derived_note_content = st.session_state.get("derived_note_content", None)
    if derived_note_content:
        # Make the request to the /save_derived_note endpoint with the derived note content
        response = make_request(
            "/save_derived_note",
            method="POST",
            json={"note_content": derived_note_content}
        )
        
        if response:
            st.success("Derived note saved successfully.")
        else:
            st.error("Failed to save derived note in Pinecone.")
    else:
        st.error("No derived note content to save.")
        

        
def search_all_research_notes_page():
    st.markdown("## Research Notes Q&A")
    search_query = st.text_input("Ask a question about research notes", key="research_notes_query")
    
    if st.button("Search Research Notes", key="search_research_notes_button"):
        search_results = make_request("/search_research_notes", params={"query": search_query})
        
        if search_results:
            derived_note_text = "\n".join(block["text"] for block in search_results["blocks"])
            st.session_state["derived_note_content"] = derived_note_text
            st.write("### Answer:")
            st.write(derived_note_text)
            
           
        else:
            st.error("No relevant answer found.")

    # Use on_click to call save_derived_note function without triggering a rerun immediately
    st.button("Save Derived Note", on_click=save_derived_note, key="save_derived_note_button")




# Main app function to route between different pages
def app():
    display_header()
    display_sidebar()

    if st.session_state.page == 'Home':
        homepage_content()
    elif st.session_state.page == 'Login':
        login_section()
    elif st.session_state.page == 'SignUp':
        signup_section()
    elif st.session_state.page == "Documents" and st.session_state.logged_in:
        documents_page()
    elif st.session_state.page == "Global_QA" and st.session_state.logged_in:
        global_qa_section()
    elif st.session_state.page == "Research_Notes" and st.session_state.logged_in:
        research_notes_page()
    elif st.session_state.page == "Search_All_Research_Notes" and st.session_state.logged_in:
        search_all_research_notes_page()

# Run the app
if __name__ == '__main__':
    app()
