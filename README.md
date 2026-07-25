# x402-validator

Audit, monitor, and protect endpoints against the **x402 strict-v2** standard.
Includes a conformance engine (manifest discovery, CAIP-2, JSON resilience, Bazaar),
CLI for batch audits, MCP server for agent/IDE integration, and a web dashboard.

```bash
pip install x402-validator
# or: pip install "x402-validator[all]"  # dashboard + proxy extras
```

## Quick examples

**CLI** — validate a single endpoint:
```bash
x402-validate https://observer.137-184-67-179.sslip.io
```

**Batch audit** — validate many endpoints, output HTML report:
```bash
x402-validate endpoints.txt --output html --parallel 20
```

**MCP server** — connect from Claude / Cursor / any MCP client:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | x402-mcp
```

**Dashboard** — view history and trends:
```bash
docker-compose up
# Open http://localhost:5000
```

## Documentation

Full documentation in the [`docs/`](docs/) directory.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
