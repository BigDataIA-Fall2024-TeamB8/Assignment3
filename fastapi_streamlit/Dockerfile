# Use Python base image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy the code into the container
COPY . .

# Install curl, gnupg, and other required packages for ODBC
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    gcc g++ \
    unixodbc-dev \
    unixodbc \
    libpq-dev \
    build-essential

# Install the Microsoft ODBC Driver for SQL Server and accept EULA
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql17 && \
    ACCEPT_EULA=Y apt-get install -y mssql-tools unixodbc-dev && \
    echo 'export PATH="$PATH:/opt/mssql-tools/bin"' >> ~/.bashrc

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expose both FastAPI and Streamlit ports
EXPOSE 8000 8501

# Command to run FastAPI and Streamlit concurrently
CMD ["sh", "-c", "uvicorn main_pine:app --host 0.0.0.0 --port 8000 & streamlit run streamlit.py --server.port 8501 --server.address 0.0.0.0"]
