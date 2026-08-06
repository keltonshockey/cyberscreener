# CyberScreener — developer entry points.
#
# `make test` runs the full offline backend suite (<10s, no network, no live
# DB). It auto-detects the venv: api/venv (MacBook), ./venv (droplet layout),
# else falls back to python3 (mill).
#
# The venv it finds must have api/requirements-dev.txt installed, not just
# api/requirements.txt: pytest and pytest-asyncio live there, and pytest.ini
# sets asyncio_mode = auto, so the async tests error without them.
#
# `make install-hooks` points git at scripts/git-hooks so the suite runs as a
# pre-push gate on this clone (opt-in, per clone).

#
# `make ark-verify ARK=<path to ark-cs-*.db.gz>` restores an ark snapshot into a
# temp dir and prints integrity_check plus the five reference counts, for
# eyeball comparison against the R0 completion record (RUNBOOK_R0_DATA_ARK.md).
# Pure local convenience: no network, and it never touches the live DB.

.PHONY: test golden install-hooks ark-verify

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

ark-verify:
	@if [ -z "$(ARK)" ]; then \
	  echo "usage: make ark-verify ARK=/path/to/ark-cs-YYYYMMDD.db.gz"; exit 2; fi
	@if [ ! -f "$(ARK)" ]; then echo "ark-verify: no such file: $(ARK)"; exit 2; fi
	@command -v sqlite3 >/dev/null || { echo "ark-verify: sqlite3 not on PATH"; exit 2; }
	@TMP=$$(mktemp -d) && trap 'rm -rf "$$TMP"' EXIT && \
	echo "ark file    : $(ARK)" && \
	echo "gz bytes    : $$(wc -c < "$(ARK)" | tr -d ' ')" && \
	echo "gz sha256   : $$(shasum -a 256 "$(ARK)" | awk '{print $$1}')" && \
	gzip -t "$(ARK)" && echo "gzip -t     : OK" && \
	gunzip -c "$(ARK)" > "$$TMP/ark.db" && \
	echo "restored    : $$(wc -c < "$$TMP/ark.db" | tr -d ' ') bytes" && \
	echo "integrity   : $$(sqlite3 "$$TMP/ark.db" 'PRAGMA integrity_check;')" && \
	echo "--- reference counts ---" && \
	sqlite3 "$$TMP/ark.db" \
	  "SELECT 'scores        ' || (SELECT COUNT(*) FROM scores) \
	   UNION ALL SELECT 'signals       ' || (SELECT COUNT(*) FROM signals) \
	   UNION ALL SELECT 'options_plays ' || (SELECT COUNT(*) FROM options_plays) \
	   UNION ALL SELECT 'prices        ' || (SELECT COUNT(*) FROM prices) \
	   UNION ALL SELECT 'max scan_id   ' || (SELECT MAX(scan_id) FROM scores);" && \
	echo "--- R0 record (2026-08-04, ark-cs-20260804) ---" && \
	echo "scores 322009 / signals 3157349 / options_plays 608 / prices 47540 / max scan_id 2501" && \
	echo "(counts should MATCH or EXCEED the record; a lower count means data loss)"
