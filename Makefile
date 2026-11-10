SCENARIO ?= scenarios/public_01_dev.yaml
NAME ?= $(basename $(notdir $(SCENARIO)))

baseline:
	python -m sim baseline --scenario $(SCENARIO) --run-dir runs/base_$(NAME)
serve:
	python -m sim serve --scenario $(SCENARIO) --run-dir runs/mine_$(NAME) --force
grade:
	mkdir -p reports && python -m sim grade --run runs/mine_$(NAME) --baseline runs/base_$(NAME) --out reports/$(NAME).md
test:
	python -m pytest -q tests
scenario:                    # baseline + serve + controller + grade, e.g. make scenario SCENARIO=scenarios/public_02_incidents.yaml
	python scripts/run_scenario.py $(SCENARIO)
crash-test:
	python scripts/crash_test.py
load-test:
	python scripts/load_test.py
multi-run:                   # result ranges over 3 worlds, e.g. make multi-run SCENARIO=scenarios/public_02_incidents.yaml
	python scripts/multi_run.py $(SCENARIO)
detector-fp:
	python scripts/detector_holdout.py state/public_01_dev.db state/public_02_incidents.db
