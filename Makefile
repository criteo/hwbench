all:

.PHONY: update_deps clean check format

UPDATE_DEPS_ENV = .env-deps
LINT_ENV = .env-lint

SOURCES = ./hwbench setup.py

update_deps:
	python3 -m venv $(UPDATE_DEPS_ENV)
	./$(UPDATE_DEPS_ENV)/bin/pip install --upgrade --quiet pip-tools
	./$(UPDATE_DEPS_ENV)/bin/pip-compile --rebuild --generate-hashes --resolver=backtracking --allow-unsafe --no-emit-index-url --no-emit-trusted-host --upgrade --quiet --output-file=requirements/test.txt requirements/test.in

clean:
	rm -fr $(UPDATE_DEPS_ENV) $(LINT_ENV)

$(LINT_ENV):
	python3 -m venv $(LINT_ENV)
	./$(LINT_ENV)/bin/pip install -r requirements/test.txt

check: $(LINT_ENV)
	env PYTHON=python3 ./$(LINT_ENV)/bin/tox

bundle: $(LINT_ENV)
	env PYTHON=python3 ./$(LINT_ENV)/bin/tox -e bundle

format: $(LINT_ENV)
	./$(LINT_ENV)/bin/black $(SOURCES)
