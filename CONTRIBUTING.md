# Contributing

Thanks for your interest! This is a starter template, so the goal is to keep it
**small, clear, and correct** — easy for someone to read top-to-bottom and adapt.
Features that belong in *your* fork (extra chains, auth tiers, databases) are
usually better as documentation than as code here.

## Getting set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[client,dev]"
```

## Before opening a PR

Run the same checks CI runs:

```bash
ruff check .       # lint
mypy app           # type-check
pytest -q          # tests
```

Please:

- Keep full type hints and docstrings on new functions (it's the house style).
- Add a test for new behaviour. Tests must stay **network-free** — the live
  payment path is exercised by `scripts/pay_example.py`, not the unit suite.
- Never commit secrets, private keys, or real wallet addresses.
- Keep the README in sync if you change behaviour.

## Reporting bugs

Open an issue with steps to reproduce. For **security** issues, follow
[SECURITY.md](SECURITY.md) instead of filing a public issue.
