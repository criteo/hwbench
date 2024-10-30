all:

.PHONY: update_deps update_lock sync_deps clean check check_ci bundle format

SOURCES = hwbench csv graph

update_deps:
	uv sync -U

update_lock:
	uv lock

sync_deps:
	uv sync --all-extras --dev

clean:
	uv venv

check:
	@uv lock --locked || echo "Your lock file should change because you probably added a dependency or bump the minimal Python version. Please run `uv lock`"
	uv tool run ruff format --diff $(SOURCES)
	uv tool run ruff check $(SOURCES)
	uv run mypy $(SOURCES)
	uv run pytest $(SOURCES)

check_ci:
	@uv lock --locked || echo "Your lock file should change because you probably added a dependency or bump the minimal Python version, but this is not allowed in the CI. Please run `uv lock`"
	uv tool run ruff format --diff $(SOURCES)
	uv tool run ruff check --output-format=github $(SOURCES)
	uv run mypy $(SOURCES)
	uv run pytest $(SOURCES)

bundle:
	uv build

format:
	uv tool run ruff format $(SOURCES)
