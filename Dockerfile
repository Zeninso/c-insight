# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Install system dependencies including GCC
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port
EXPOSE 8000

# Create a startup script
RUN echo '#!/bin/bash\n\
echo "Waiting for database..."\n\
sleep 10\n\
echo "Starting application..."\n\
if [ -z "$PORT" ]; then\n\
    PORT=5000\n\
fi\n\
echo "Using port: $PORT"\n\
exec gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 app:application' > /app/start.sh && \
chmod +x /app/start.sh

# Run the startup script
CMD ["/app/start.sh"]
