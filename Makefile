PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
PORT ?= 8741

.PHONY: install download pipeline train test lint dashboard check notebook diagrams all

install:
	$(PYTHON) -m pip install -r requirements.txt

download:
	bash scripts/download_data.sh

pipeline:
	$(PYTHON) -m pipeline.run

train:
	$(PYTHON) -m models.train

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

dashboard:
	$(PYTHON) -m streamlit run app/Home.py --server.port $(PORT) --server.address 0.0.0.0 --server.headless true

check:
	$(PYTHON) -c "import xgboost, streamlit, duckdb, sklearn, pandas, plotly"

diagrams:
	$(PYTHON) scripts/render_diagrams.py

notebook:
	$(PYTHON) -m jupyter nbconvert --to notebook --execute --inplace notebooks/01_explore.ipynb

all: download pipeline train test
