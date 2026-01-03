# Justfile for LLM Social Network Simulator

# Default recipe
default: test

# Install dependencies
install:
    pip install -e ".[dev]"

# Initialize the database
init:
    python -m src.run_sim init-db --force

# Run simulation with defaults
run: init
    python -m src.run_sim simulate --ticks 20 --agents 10 --k 10 --ranking hot

# Run simulation with custom parameters
simulate ticks="10" agents="5" k="10" ranking="hot" seed="42":
    python -m src.run_sim simulate --ticks {{ticks}} --agents {{agents}} --k {{k}} --ranking {{ranking}} --seed {{seed}}

# Replay events to rebuild projections
replay:
    python -m src.run_sim replay

# Show KPIs
kpis:
    python -m src.run_sim kpis

# Show KPIs as JSON
kpis-json:
    python -m src.run_sim kpis --json-output

# Show recent events
events limit="20":
    python -m src.run_sim events --limit {{limit}}

# Run all tests
test:
    pytest -v

# Run tests with coverage
test-cov:
    pytest --cov=src --cov-report=term-missing

# Run a specific test file
test-file file:
    pytest -v {{file}}

# Lint code
lint:
    ruff check src tests

# Format code
fmt:
    ruff format src tests

# Clean database and cache files
clean:
    rm -f sim.db sim.db-wal sim.db-shm
    rm -rf __pycache__ .pytest_cache .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Full reset: clean and reinitialize
reset: clean init
