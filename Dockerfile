# Use lightweight Python image
FROM python:3.12-slim

# Install system dependencies for MySQL
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for Docker caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source code
COPY . .

# Expose port (Railway will set $PORT, but we expose 5000 for local)
EXPOSE 5000

# Start Gunicorn with WSGI entrypoint
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "wsgi:application"]
