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
```

3. Commit: "Use startup script with debugging"

---

### **Step 3: Wait and check logs**

After Railway redeploys (2-3 minutes), check the Deploy Logs. You should now see:
```
=== Starting Hiya Scraper API ===
Python version: 3.10.x
Current directory: /app
Files in directory:
...
Testing imports...
