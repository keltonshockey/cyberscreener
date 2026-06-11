# CyberScreener — developer entry points.
#
# `make test` runs the full offline backend suite (<10s, no network, no live
# DB). It auto-detects the venv: api/venv (MacBook), ./venv (droplet layout),
# else falls back to python3 (mill).
#
# `make install-hooks` points git at scripts/git-hooks so the suite runs as a
# pre-push gate on this clone (opt-in, per clone).

.PHONY: test golden install-hooks

test:
	@cd api && \
	if [ -x venv/bin/python ]; then PY=venv/bin/python; \
	elif [ -x ../venv/bin/python ]; then PY=../venv/bin/python; \
	else PY=python3; fi && \
	$$PY -m pytest tests/ -q

golden:
	@cd api && \
	if [ -x venv/bin/python ]; then PY=venv/bin/python; \
	elif [ -x ../venv/bin/python ]; then PY=../venv/bin/python; \
	else PY=python3; fi && \
	UPDATE_GOLDEN=1 $$PY -m pytest tests/test_scoring_golden.py -q && \
	echo "scoring_golden.json regenerated — review the diff before committing"

install-hooks:
	git config core.hooksPath scripts/git-hooks
	chmod +x scripts/git-hooks/pre-push
	@echo "pre-push hook installed (git config core.hooksPath scripts/git-hooks)"
