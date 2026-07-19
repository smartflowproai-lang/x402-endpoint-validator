FROM python:3.11-slim

LABEL org.opencontainers.image.title="x402 Endpoint Validator"
LABEL org.opencontainers.image.description="GitHub Action for validating x402 endpoint compliance in CI"
LABEL org.opencontainers.image.source="https://github.com/smartflowproai-lang/x402-endpoint-validator"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /action

RUN pip install --no-cache-dir requests==2.32.3 PyYAML==6.0.2

COPY validator.py /action/validator.py
COPY payment_required.py /action/payment_required.py
COPY entrypoint.sh /action/entrypoint.sh

RUN chmod +x /action/entrypoint.sh /action/validator.py

ENTRYPOINT ["/action/entrypoint.sh"]
