FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
ENV PORT=8080
EXPOSE 8080

# Use gunicorn for production with longer timeout
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --threads 2 --log-level debug api:app
