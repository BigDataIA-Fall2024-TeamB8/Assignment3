FROM apache/airflow:2.7.0

# Set the user to root to perform installations
USER 0
# Install Firefox
RUN apt-get update && apt-get install -y firefox-esr


# Install Chrome and ChromeDriver
RUN apt-get update && \
    apt-get install -y wget unzip && \
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -y ./google-chrome-stable_current_amd64.deb && \
    rm ./google-chrome-stable_current_amd64.deb && \
    CHROME_DRIVER_VERSION="130.0.6686.4" && \
    wget -N https://storage.googleapis.com/chrome-for-testing-public/$CHROME_DRIVER_VERSION/linux64/chromedriver-linux64.zip -P /tmp && \
    unzip /tmp/chromedriver-linux64.zip -d /usr/local/bin/ && \
    mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    rm -r /usr/local/bin/chromedriver-linux64 && \
    rm /tmp/chromedriver-linux64.zip && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /var/lib/apt/lists/*

# Verify installation
RUN google-chrome --version && /usr/local/bin/chromedriver --version

# Switch back to the default airflow user
USER airflow