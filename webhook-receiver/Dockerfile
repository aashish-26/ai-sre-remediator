FROM python:3.11-slim

# Install runtime deps
RUN pip install --no-cache-dir flask kubernetes requests

# Copy the receiver code into the image
WORKDIR /opt/app
COPY scripts/alertmanager_webhook_receiver.py /opt/app/alertmanager_webhook_receiver.py

EXPOSE 5000

CMD ["python", "/opt/app/alertmanager_webhook_receiver.py"]
