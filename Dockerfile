# Use an official Python image since yt-dlp requires Python
FROM python:3.10-slim

# Install yt-dlp
RUN pip install yt-dlp

# Set the working directory
WORKDIR /app

# Copy the script and make it executable
COPY download_subs.sh /app/download_subs.sh
RUN chmod +x /app/download_subs.sh

# Set the entrypoint to the download_subs.sh script
ENTRYPOINT ["/app/download_subs.sh"]
