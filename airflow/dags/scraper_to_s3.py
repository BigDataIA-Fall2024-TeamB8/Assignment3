from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
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

def initialize_chrome_driver(headless=True):
    """Initialize Chrome WebDriver with enhanced headless options for compatibility."""
    chrome_options = ChromeOptions()
    if headless:
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=chrome_service, options=chrome_options)

def initialize_firefox_driver():
    """Alternative WebDriver using Firefox with headless options."""
    firefox_options = FirefoxOptions()
    firefox_options.add_argument('--headless')
    firefox_service = FirefoxService(GeckoDriverManager().install())
    return webdriver.Firefox(service=firefox_service, options=firefox_options)

def scrape_and_upload():
    global counter
    logger.info("Starting scrape_and_upload function...")

    # Initialize Chrome driver, with Firefox as fallback
    try:
        driver = initialize_chrome_driver()
    except Exception as e:
        logger.warning("Chrome WebDriver failed to initialize; switching to Firefox. Error: %s", e)
        driver = initialize_firefox_driver()

    urls = [
        "https://rpc.cfainstitute.org/en/research-foundation/publications#sort=%40officialz32xdate%20descending&numberOfResults=50&f:SeriesContent=[Research%20Foundation]",
        "https://rpc.cfainstitute.org/en/research-foundation/publications#first=50&sort=%40officialz32xdate%20descending&numberOfResults=50&f:SeriesContent=[Research%20Foundation]"
    ]

    for url in urls:
        driver.get(url)
        logger.info(f"Loading URL: {url}")
        time.sleep(5)

        # Parse the page source with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, "html.parser")
        publications = soup.find_all("div", class_="coveo-result-row")
        processed_titles = set()

        for publication in publications:
            title_tag = publication.find("a", class_="CoveoResultLink")
            if not title_tag:
                continue

            title = title_tag.text.strip()
            if title in processed_titles:
                continue
            processed_titles.add(title)

            folder_name = f"{str(counter).zfill(4)}_{title.replace(' ', '_')}"
            counter += 1

            detail_link = title_tag['href']
            if not detail_link.startswith("http"):
                detail_link = "https://rpc.cfainstitute.org" + detail_link

            # Extract summary directly from the publication listing page
            summary_tag = publication.find("div", class_="result-body")
            summary = summary_tag.get_text(strip=True) if summary_tag else "No summary available"

            # Scrape PDF link and image from the detail page
            pdf_url = None
            image_url = None
            detail_response = requests.get(detail_link)
            if detail_response.status_code == 200:
                detail_soup = BeautifulSoup(detail_response.content, "html.parser")
                
                # PDF link extraction
                pdf_tag = detail_soup.find("a", class_="content-asset-primary", href=True)
                if pdf_tag and "Read Book" in pdf_tag.text:
                    pdf_url = pdf_tag["href"]
                    if pdf_url and not pdf_url.startswith("http"):
                        pdf_url = "https://rpc.cfainstitute.org" + pdf_url

                # Alternative search if no primary PDF link found
                if not pdf_url:
                    all_a_tags = detail_soup.find_all("a", href=True)
                    for tag in all_a_tags:
                        if "pdf" in tag['href'].lower() or "Read Book" in tag.get_text(strip=True):
                            pdf_url = tag['href'] if tag['href'].startswith("http") else "https://rpc.cfainstitute.org" + tag['href']
                            break

                # Image link extraction
                image_tag = detail_soup.find("meta", property="og:image")
                image_url = image_tag["content"] if image_tag else None

            # Upload metadata to S3 (including title, summary, and detail link)
            metadata = {"title": title, "summary": summary, "detail_link": detail_link}
            metadata_key = f"{folder_name}/metadata.json"
            s3.put_object(Bucket='cfai-data', Key=metadata_key, Body=json.dumps(metadata))
            logger.info(f"Uploaded metadata for {title} to S3 as {metadata_key}")

            # Download and upload PDF if available
            if pdf_url:
                try:
                    pdf_response = requests.get(pdf_url, stream=True)
                    pdf_key = f"{folder_name}/{title.replace(' ', '_')}.pdf"
                    if pdf_response.status_code == 200:
                        s3.upload_fileobj(pdf_response.raw, 'cfai-data', pdf_key)
                        logger.info(f"Uploaded PDF for {title} to S3 as {pdf_key}")
                    else:
                        logger.error(f"Failed to download PDF for {title}. Status Code: {pdf_response.status_code}")
                except Exception as e:
                    logger.error(f"Error uploading PDF for {title}: {e}")

            # Download and upload image if available
            if image_url:
                try:
                    image_response = requests.get(image_url, stream=True)
                    image_key = f"{folder_name}/cover_image.jpg"
                    if image_response.status_code == 200:
                        s3.upload_fileobj(image_response.raw, 'cfai-data', image_key)
                        logger.info(f"Uploaded image for {title} to S3 as {image_key}")
                    else:
                        logger.error(f"Failed to download image for {title}. Status Code: {image_response.status_code}")
                except Exception as e:
                    logger.error(f"Failed to upload image for {title}. Error: {e}")
        
    driver.quit()
    logger.info("Scraping completed for all URLs.")

if __name__ == "__main__":
    logger.info("Starting the publication processing pipeline...")
    scrape_and_upload()
    logger.info("Processing pipeline completed.")
