# Build from this directory:
#   docker build -t shadow-it .
FROM python:3.11-slim

WORKDIR /srv

# Dependencies first, so a code change does not re-resolve the whole tree.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app

# Do not run the API as root; nothing here needs it.
RUN useradd --system --create-home --uid 10001 shadowit
USER shadowit

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

# One worker: the scheduler loop must not run once per process. Scale out with
# replicas that have SCAN_INTERVAL_HOURS=0 and a single scheduler instance.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
