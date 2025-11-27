# NOTE: corrected - ENTRYPOINT now points to the actual operator script under ai_operator/
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies (gcc, build-essential, libssl-dev) and curl for HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       build-essential \
       libssl-dev \
       ca-certificates \
       curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project into image
COPY . /app

# Upgrade pip and install Python dependencies if requirements.txt exists
RUN python -m pip install --upgrade pip setuptools wheel \
    && if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt; fi

# Create a non-root user and give ownership of /app
RUN groupadd -r app \
    && useradd -r -g app -d /app -s /sbin/nologin app \
    && chown -R app:app /app

# Run the operator's main script under ai_operator/ (adjust if your real entrypoint differs)
# prefer module-style execution (requires ai_operator/__init__.py)
ENTRYPOINT ["python","-m","kopf","run","/app/ai_operator/operator_main.py","--standalone","--verbose"]    

# ensure a passwd entry exists for the non-root user (uid 1000)
RUN echo "app:x:1000:1000:ai-operator user:/app:/sbin/nologin" >> /etc/passwd

# Expose necessary ports
EXPOSE 9100 5001

# Use unbuffered stdout/stderr
ENV PYTHONUNBUFFERED=1

# Run as non-root user
USER app

# Healthcheck hitting metrics endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:9100/metrics || exit 1
