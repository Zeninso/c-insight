FROM python:3.12-slim

# Install system dependencies including MySQL client
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use this CMD in your Dockerfile
CMD gunicorn --bind 0.0.0.0:5000 app:application