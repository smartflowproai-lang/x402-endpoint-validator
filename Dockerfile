FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY x402_conformance_engine.py .
COPY batch_validator.py .

CMD ["python", "batch_validator.py", "--help"]
