# x402 Conformance Validator

Suite de herramientas para auditar endpoints contra el estándar **x402 strict-v2**.

## Componentes

| Módulo | Archivo | Propósito |
|---|---|---|
| **Engine** | `x402_conformance_engine.py` | Auditoría base: manifest discovery, CAIP-2 compliance, JSON resilience, bazaar checker |
| **Batch** | `batch_validator.py` | Validación por lote desde CSV con concurrencia controlada |
| **Bot** | `x402_discord_bot.py` | Bot de Discord con comandos `/x402` y `/x402ai` |
| **Proxy** | `x402_proxy_server.py` | Proxy inverso que envuelve respuestas 402 no-dict para evitar crashes en Bazaar |
| **Bazaar Checker** | (en el engine) | Verifica que `extensions.bazaar` esté completo y tenga `method: POST`, `serviceName`, `tags` |

## Tests

```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio

# Todos los tests
python -m pytest

# Por componente
python -m pytest test_x402_conformance_engine.py -v   # Engine + Bazaar
python -m pytest test_batch_validator.py -v            # Batch
python -m pytest test_x402_discord_bot.py -v           # Bot
python -m pytest test_x402_proxy_server.py -v          # Proxy
python -m pytest test_bazaar_checker.py -v             # Bazaar Checker
```

## GitHub Action — copiar en 2 minutos

1. En tu repo, crea `.github/workflows/x402-validator.yml`
2. Copia esto:

```yaml
name: x402 Validator
on: [push]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      - name: Run tests
        run: python -m pytest -v
```

3. Pushea el archivo. El action corre automáticamente en cada push.

Si algún test falla (headers rotos, extensión Bazaar faltante, CAIP-2 inválido), el build falla y te dice exactamente qué arreglar.

## Uso local

```bash
# Auditar un endpoint
python x402_conformance_engine.py https://api.example.com

# Batch desde CSV
python batch_validator.py endpoints.csv --concurrency 25

# Proxy
python x402_proxy_server.py

# Bot (necesita token Discord)
DISCORD_TOKEN=... python x402_discord_bot.py
```

## Fixtures

Los archivos de prueba están en `tests/fixtures/`:

- `viridis_402_exchange_sanitized.json` — Intercambio HTTP real capturado en Viridis (sanitizado)
- `bazaar_missing_block.json` — Respuesta 402 sin `extensions.bazaar`
- `bazaar_missing_fields.json` — Respuesta 402 con `extensions.bazaar` incompleto
