# equity-analyst

An equity research tool.

> Early scaffold. Feature set is being defined — see [Roadmap](#roadmap).

## Overview

A Python tool for equity research and analysis. More detail to come as
features are specified.

## Requirements

- Python 3.11+

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# Install (editable) with dev extras
pip install -e ".[dev]"
```

## Usage

```bash
python -m equity_analyst --help
```

## Development

```bash
pytest          # run tests
ruff check .    # lint
ruff format .   # format
```

## Roadmap

- [ ] Define core research features (details forthcoming)
- [ ] Data source integration
- [ ] Analysis / screening logic
- [ ] Output / reporting

## License

MIT — see [LICENSE](LICENSE).
