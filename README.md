# x402-validator

Audita, monitorea y protege endpoints contra el estándar **x402 strict-v2**. Incluye un motor de chequeos (manifest discovery, CAIP-2, JSON resilience, Bazaar), CLI para auditorías masivas, servidor MCP para integración con agents/IDEs, dashboard web con históricos y proxy inverso que empaqueta validación en cada request.

```bash
pip install x402-validator
# o: pip install "x402-validator[all]"  # dashboard + proxy
```

## 4 ejemplos de uso

### CLI — auditar 100 endpoints desde un archivo

```bash
x402-validate endpoints.txt --output html --parallel 20
```

### MCP — conectar desde Claude / Cursor / cualquier cliente MCP

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | x402-mcp
```

### Dashboard — ver históricos y tendencias

```bash
python main.py dashboard
# Abrir http://localhost:5000
```

### Proxy — validar en cada request

```bash
python main.py proxy
curl http://localhost:8080/forward/https://api.example.com/data
# Headers: X-Validation-Status, X-Validation-Report
```

## Tests

```bash
pip install -e ".[all]" pytest pytest-asyncio
python -m pytest test_*.py -v
```

---

## Real-World Validation

We validate the x402-validator against production endpoints:

- **Observer Marketplace** (Base mainnet)
  - 2 products, real USDC payments
  - 7/10 checks pass
  - See: [Validation Report](docs/VALIDATION_OBSERVER.md)

This ensures the validator works against real,
complex x402 implementations in production.

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- [x] CLI con salida csv/json/html
- [x] MCP server (JSON-RPC 2.0 sobre stdio)
- [x] Dashboard web con históricos
- [x] Proxy middleware validante
- [x] Docker compose + CI
- [ ] Publicación en PyPI
- [ ] Plugin para GitHub Actions
- [ ] Modo watch / daemon
- [ ] Webhooks (Slack, email)

---

Parte del ecosistema [x402-endpoint-validator](https://github.com/smartflowproai-lang/x402-endpoint-validator).
