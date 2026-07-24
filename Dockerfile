FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY x402_conformance_engine.py .

CMD ["python", "x402_conformance_engine.py", "--help"]
