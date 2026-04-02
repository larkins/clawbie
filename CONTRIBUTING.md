# Contributing to Clawbie

Contributions are welcome! Please keep a few things in mind:

## Development Setup

```bash
git clone git@github.com:larkins/clawbie.git
cd clawbie
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"  # if dev dependencies exist
cp .env.example .env
# configure .env with your test database
psql "$DATABASE_URL" -f migrations/CLAWBIE_SCHEMA.sql
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Style

- Python: follow [PEP 8](https://pep8.org/)
- Max line length: 100 characters
- Docstrings for all public functions and classes
- Type hints where practical

## Pull Request Guidelines

1. **One feature or fix per PR** — keep changes focused
2. **Test your changes** — add tests for new functionality
3. **Don't commit secrets** — never hardcode API keys, passwords, or credentials
4. **Update docs** — if you change functionality, update relevant documentation
5. **Keep `.env` out** — use `.env.example` for template variables

## Secrets Policy

- All secrets go in `.env` (never committed)
- Non-secret defaults go in `config.yaml` or as module constants
- Environment variable names are acceptable in code (e.g. `os.environ.get("DATABASE_URL")`)
- Service files (systemd) should reference env vars, not hardcode credentials

## Reporting Issues

Please include:
- Python version and OS
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output (no secrets)
