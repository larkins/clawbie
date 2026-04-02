# Security Policy

## Reporting a Vulnerability

If you find a security vulnerability in Clawbie, please report it by sending an email to the maintainer (see GitHub profile) rather than filing a public issue.

## Security Best Practices

### Secrets Management

- **Never commit `.env`** or any file containing real API keys, passwords, or tokens
- Use environment variables or a secrets manager in production
- The `.env.example` file shows the required variables — copy it to `.env` and fill in real values

### Database

- Use strong PostgreSQL passwords (generated with `openssl rand -base64 14` or similar)
- Bind PostgreSQL to `127.0.0.1` or a specific local interface — never `0.0.0.0`
- Use TLS for database connections in production

### Network Binding

- All services should bind to `127.0.0.1` (localhost) or a specific LAN IP
- Never bind to `0.0.0.0` unless a service explicitly requires external access

### API Keys

- MiniMax API key: keep in `MINIMAX_API_KEY` env var, never hardcode
- Ethereum private keys: never store in source code or config files

## Dependency Security

```bash
# Keep dependencies up to date
pip list --outdated
pip install -U <package>

# Audit for known vulnerabilities
pip install safety
safety check
```
