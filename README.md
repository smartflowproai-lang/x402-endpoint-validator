# x402-validator

Audit, monitor, and protect endpoints against the **x402 strict-v2** standard.
Includes a conformance engine (manifest discovery, CAIP-2, JSON resilience, Bazaar),
CLI for batch audits, and an MCP server for agent/IDE integration.

```bash
pip install x402-validator
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

## Extended tools

Dashboard, API server, Stripe monetization, and proxy middleware:
[github.com/MSSATANASS/x402-validator-tools](https://github.com/MSSATANASS/x402-validator-tools)

## Documentation

Full documentation in the [`docs/`](docs/) directory.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
