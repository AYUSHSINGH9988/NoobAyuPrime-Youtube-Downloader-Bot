# Python Base Image
FROM python:3.10-slim

# Working Directory
WORKDIR /app

# Install Curl, FFmpeg, Git AND Latest Node.js (Critical for n-challenge)
RUN apt-get update && \
    apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs ffmpeg git && \
    apt-get clean

# Requirements copy karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Code
COPY . .

# Run Bot
CMD ["python", "main.py"]
