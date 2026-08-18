# Build from the repository root:
#   docker build -t security-alerts -f security_alert_system/Dockerfile .
FROM python:3.11-slim

# ffmpeg is only needed if you switch CAMERA_CONNECTOR to "ffmpeg" and have
# given the container a route to your cameras (VPN/tunnel). Uncomment then.
# RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
#     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY security_alert_system/requirements.txt security_alert_system/requirements.txt
RUN pip install --no-cache-dir -r security_alert_system/requirements.txt

COPY security_alert_system/ security_alert_system/

# Mount a volume here so dedupe state survives a redeploy.
RUN mkdir -p /app/security_alert_system/state
VOLUME ["/app/security_alert_system/state"]

ENV PYTHONUNBUFFERED=1

# The dashboard binds to 127.0.0.1 by default, so it is reachable from inside
# the container only. Publish the port (and set DASHBOARD_TOKEN) if you want it
# reachable from outside.
EXPOSE 8080

CMD ["python", "-m", "security_alert_system.main"]
