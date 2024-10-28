from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import boto3
import os
import logging
import requests
from bs4 import BeautifulSoup
import json

# Initialize S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize a global counter for sequential folder numbering
counter = 1

def scrape_and_upload():
    global counter
    logger.info("Starting scrape_and_upload function...")

    # Set up Chrome options for headless operation
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--remote-debugging-port=9222')
    options.add_argument('--window-size=1920x1080')

    # Initialize Chrome WebDriver with Service for ChromeDriverManager
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Loop through each page of the base URL
    base_url = "https://rpc.cfainstitute.org/en/research-foundation/publications"
    for page_number in range(1, 11):  # Assume there are 10 pages
        page_url = f"{base_url}?page={page_number}"
        driver.get(page_url)
        logger.info(f"Waiting for page {page_number} to load fully...")
        time.sleep(5)  # Wait for the page to fully render

        # Get page source and parse with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, "html.parser")
        logger.info(f"Page {page_number} loaded and parsed with BeautifulSoup.")
        
        # Locate publication entries
        publications = soup.find_all("div", class_="coveo-result-row")
        
        # Ensure we're only processing each publication entry once
        processed_titles = set()  # To track unique titles on the page
        logger.info(f"Found {len(publications)} publications on page {page_number}.")

        for publication in publications:
            # Extract title and check if we've already processed this title
            title_tag = publication.find("a", class_="CoveoResultLink")
            if not title_tag:
                logger.warning("Title link not found; skipping this publication.")
                continue

            title = title_tag.text.strip()
            if title in processed_titles:
                continue  # Skip duplicate entries
            processed_titles.add(title)

            # Generate a sequential folder name for each publication
            folder_name = f"{str(counter).zfill(4)}_{title.replace(' ', '_')}"
            counter += 1  # Increment counter for each unique publication

            detail_link = title_tag['href']
            if not detail_link.startswith("http"):
                detail_link = "https://rpc.cfainstitute.org" + detail_link

            # Extract the summary from the main page under the publication title
            summary_tag = publication.find("div", class_="result-body")
            summary = summary_tag.get_text(strip=True) if summary_tag else "No summary available"

            # Fetch and parse the detail page to extract PDF and image links
            detail_response = requests.get(detail_link)
            if detail_response.status_code != 200:
                logger.error(f"Failed to load detail page for {title}. Status Code: {detail_response.status_code}")
                continue
            detail_soup = BeautifulSoup(detail_response.content, "html.parser")

            # Prepare JSON metadata file with title, summary, and detail link
            metadata = {
                "title": title,
                "summary": summary,
                "detail_link": detail_link
            }
            metadata_key = f"{folder_name}/metadata.json"
            s3.put_object(Bucket='cfai-data', Key=metadata_key, Body=json.dumps(metadata))
            logger.info(f"Uploaded metadata for {title} to S3 as {metadata_key}")

            # Extract and upload PDF
            pdf_url = None
            pdf_tag = detail_soup.find("a", class_="content-asset-primary", href=True)
            if pdf_tag and "Read Book" in pdf_tag.text:
                pdf_url = pdf_tag["href"]
                if pdf_url and not pdf_url.startswith("http"):
                    pdf_url = "https://rpc.cfainstitute.org" + pdf_url

            if pdf_url:
                try:
                    pdf_response = requests.get(pdf_url, stream=True)
                    if pdf_response.status_code == 200:
                        pdf_key = f"{folder_name}/{title.replace(' ', '_')}.pdf"
                        s3.upload_fileobj(pdf_response.raw, 'cfai-data', pdf_key)
                        logger.info(f"Uploaded PDF for {title} to S3 as {pdf_key}")
                    else:
                        logger.error(f"Failed to download PDF for {title}. Status Code: {pdf_response.status_code}")
                except Exception as e:
                    logger.error(f"Exception while uploading PDF for {title}: {e}")
            else:
                logger.warning(f"No PDF URL found for {title}. Checking all <a> tags for possible PDF links.")
                
                # Check all <a> tags for potential PDF links
                all_a_tags = detail_soup.find_all("a", href=True)
                for tag in all_a_tags:
                    tag_text = tag.get_text(strip=True)
                    href = tag['href']
                    if "pdf" in href.lower() or "Read Book" in tag_text:
                        pdf_url = href if href.startswith("http") else "https://rpc.cfainstitute.org" + href
                        logger.info(f"Potential PDF link identified for {title}: {pdf_url}")
                        # Download and upload this PDF
                        try:
                            pdf_response = requests.get(pdf_url, stream=True)
                            if pdf_response.status_code == 200:
                                pdf_key = f"{folder_name}/{title.replace(' ', '_')}.pdf"
                                s3.upload_fileobj(pdf_response.raw, 'cfai-data', pdf_key)
                                logger.info(f"Uploaded PDF for {title} to S3 as {pdf_key}")
                            else:
                                logger.error(f"Failed to download PDF from potential link for {title}. Status Code: {pdf_response.status_code}")
                        except Exception as e:
                            logger.error(f"Exception while uploading PDF from potential link for {title}: {e}")
                        break  # Stop after finding the first valid PDF link

            # Extract and upload image
            image_tag = detail_soup.find("meta", property="og:image")
            image_url = image_tag["content"] if image_tag else None

            if image_url:
                try:
                    image_response = requests.get(image_url, stream=True)
                    if image_response.status_code == 200:
                        image_key = f"{folder_name}/cover_image.jpg"
                        s3.upload_fileobj(image_response.raw, 'cfai-data', image_key)
                        logger.info(f"Uploaded image for {title} to S3 as {image_key}")
                    else:
                        logger.error(f"Failed to download image for {title}. Status Code: {image_response.status_code}")
                except Exception as e:
                    logger.error(f"Failed to upload image for {title}. Error: {e}")

    # Close the driver after scraping all pages
    driver.quit()
    logger.info("Scraping completed for all pages.")

if __name__ == "__main__":
    logger.info("Starting the publication processing pipeline...")
    scrape_and_upload()
    logger.info("Processing pipeline completed.")
