FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY worker/worker_app ./worker_app

CMD ["python", "-m", "worker_app.worker"]
