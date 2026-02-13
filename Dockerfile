# Python ka base image
FROM python:3.10-slim

# Working directory set karo
WORKDIR /app

# FFmpeg aur zaroori tools install karo
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    apt-get clean

# Requirements copy karo aur install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki saara code copy karo
COPY . .

# Bot start karo
CMD ["python", "main.py"]

