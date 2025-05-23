# Alternative: Use alpine-based image which uses a different implementation of libraries
FROM python:3.11-alpine

# Set working directory
WORKDIR /app

# Copy requirements file first
COPY requirements.txt .

# Install build dependencies for psycopg2 (Alpine uses different packages)
RUN apk add --no-cache \
    postgresql-dev \
    gcc \
    python3-dev \
    musl-dev \
    libffi-dev

# Upgrade pip and setuptools
RUN pip install --upgrade pip && \
    pip install --no-cache-dir setuptools>=70.0.0

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY db_utils.py .
COPY intern_bot.py .
COPY webserver.py .
COPY .env .
COPY interns_new.csv .

# Expose port for Flask web server
EXPOSE 3001
ENV PORT=3001

# Command to run the application
CMD ["python", "intern_bot.py"]