set positional-arguments

default:
    @just --list

# Install Python dependencies
requirements:
    uv sync --group dev

# Run tests, then report the files with untested lines or branches
test *ARGS:
    uv run pytest tests -n auto --cov --cov-report=term-missing "$@"

# Run the memory test: assemble, build and replay --compare on 200k and 2M narrow rows and 300k wide ones under a 512 MiB limit (Linux only)
test-memory:
    uv run pytest tests/test_memory.py -m memory

# Run tests and write a browsable coverage report to htmlcov/
coverage:
    uv run pytest tests -n auto --cov --cov-report=html
    @echo "open htmlcov/index.html"

# Check formatting and lint (use `just format` to fix)
lint:
    uv run ruff format --check
    uv run ruff check
    uv run ty check
    uv run rumdl check .
    uv run zizmor --persona=pedantic --offline .github

# Run every check CI runs
checks: lint test

# Format source code and Markdown
format:
    uv run ruff check --fix
    uv run ruff format
    uv run rumdl check --fix .

# Regenerate the generated tables in docs/findings.md and docs/commands.md
docs:
    uv run python -m tests.make_docs

# Delete all compiled Python files
clean:
    find . -type f -name "*.py[co]" -delete
    find . -type d -name "__pycache__" -delete
