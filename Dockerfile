# Python Base Image
FROM python:3.10-slim

# Working Directory
WORKDIR /app

# Install System Dependencies
# 1. curl/gnupg: Node setup ke liye
# 2. build-essential: tgcrypto compile karne ke liye (Speed badhayega)
# 3. ffmpeg: Video merging ke liye
# 4. aria2: Fast downloading ke liye (Leech Logic)
RUN apt-get update && \
    apt-get install -y curl gnupg build-essential && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs ffmpeg git aria2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Requirements copy
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Code
COPY . .

# Run Bot
CMD ["python", "main.py"]
