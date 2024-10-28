import requests
from bs4 import BeautifulSoup
import boto3
import os
import logging

# Initialize S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scrape_and_upload():
    logger.info("Starting scrape_and_upload function...")

    base_url = "https://rpc.cfainstitute.org/en/research-foundation/publications"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # Scrape the main publications page
    logger.info("Fetching the main publications page...")
    response = requests.get(base_url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to load page. Status Code: {response.status_code}")
        return
    
    soup = BeautifulSoup(response.content, "html.parser")
    logger.info("Parsing the HTML content for publications...")

    # Find all publication entries
    publications = soup.find_all("div", class_="grid__item")  # Adjust class as necessary
    logger.info(f"Found {len(publications)} publications on the main page.")

    for publication in publications:
        # Extract title and link to detail page
        title_tag = publication.find("h2", class_="title")  # Adjust if needed
        if not title_tag:
            logger.warning("Title not found; skipping this publication.")
            continue
        
        title = title_tag.text.strip()
        detail_link = "https://rpc.cfainstitute.org" + title_tag.find("a")["href"]
        logger.info(f"Processing publication: {title} - {detail_link}")
        
        # Extract summary from the main page
        summary_tag = publication.find("p", class_="description")  # Adjust as necessary
        summary = summary_tag.text.strip() if summary_tag else "No summary available"
        
        # Visit detail page for additional content
        detail_response = requests.get(detail_link, headers=headers)
        if detail_response.status_code != 200:
            logger.error(f"Failed to load detail page for {title}. Status Code: {detail_response.status_code}")
            continue
        
        detail_soup = BeautifulSoup(detail_response.content, "html.parser")
        
        # Extract PDF link
        pdf_tag = detail_soup.find("a", text="Download PDF")  # Adjust text if necessary
        pdf_url = "https://rpc.cfainstitute.org" + pdf_tag["href"] if pdf_tag else None
        if pdf_url:
            logger.info(f"PDF found for {title}: {pdf_url}")
        
        # Extract image link
        image_tag = detail_soup.find("meta", property="og:image")
        image_url = image_tag["content"] if image_tag else None
        if image_url:
            logger.info(f"Image found for {title}: {image_url}")
        
        # Upload files to S3 if found
        if pdf_url:
            pdf_response = requests.get(pdf_url)
            pdf_key = f"pdfs/{title}.pdf"
            s3.upload_fileobj(pdf_response.raw, 'cfai-data', pdf_key)
            logger.info(f"Uploaded PDF for {title} to S3 as {pdf_key}")
        
        if image_url:
            image_response = requests.get(image_url)
            image_key = f"images/{title}.jpg"
            s3.upload_fileobj(image_response.raw, 'cfai-data', image_key)
            logger.info(f"Uploaded image for {title} to S3 as {image_key}")

if __name__ == "__main__":
    logger.info("Starting the publication processing pipeline...")
    scrape_and_upload()
    logger.info("Processing pipeline completed.")
