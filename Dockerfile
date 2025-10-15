FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make startup script executable
COPY startup.sh .
RUN chmod +x startup.sh

# Expose port
ENV PORT=8080
EXPOSE 8080

# Run startup script
CMD ["./startup.sh"]
