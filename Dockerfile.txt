# Use official lightweight Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/user

# Create a non-root user for security and Hugging Face compatibility
RUN useradd -m -u 1000 user
WORKDIR $HOME/app

# Install system dependencies (Adding aria2 here for superfast speed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    build-essential \
    aria2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python packages
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code with correct permissions
COPY --chown=user:user . .

# Ensure the user has permissions to write to home directory
RUN chown -R user:user /home/user

# Switch to the non-root user
USER user

# Expose port 7860
EXPOSE 7860

# Start the application
CMD ["python", "app.py"]
