# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY mymdb/ /app/mymdb/

EXPOSE 8000

# Run from the inner Django project dir so 'mymdb.asgi' imports cleanly
WORKDIR /app/mymdb

# Default command: Daphne ASGI server
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "mymdb.asgi:application"]