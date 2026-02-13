# Python Base
FROM python:3.10-slim

# Working Directory
WORKDIR /app

# Install Node.js (Latest), FFmpeg & Git
RUN apt-get update && \
    apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs ffmpeg git && \
    apt-get clean

# Verify Node.js Install (Log mein dikhega)
RUN node -v && npm -v

# Install Python Requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Code
COPY . .

# Run Bot
CMD ["python", "main.py"]
