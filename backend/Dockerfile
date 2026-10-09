FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 torch \
    && pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY assets assets
RUN mkdir -p temp output data

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
