#!/usr/bin/env bash
# Download the three public datasets into data/raw/.
# No Kaggle API key is required. If every URL fails, the script prints the
# manual step and exits non-zero. Re-run with FORCE=1 to ignore existing files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AZURE_DIR="data/raw/azure"
AI4I_DIR="data/raw/ai4i"
CMAPSS_DIR="data/raw/cmapss"
mkdir -p "$AZURE_DIR" "$AI4I_DIR" "$CMAPSS_DIR"

FORCE="${FORCE:-0}"

fetch() {
  local dest="$1"
  shift
  local url
  for url in "$@"; do
    echo "  trying ${url}"
    if curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -o "${dest}.partial" "$url"; then
      mv "${dest}.partial" "$dest"
      echo "  saved ${dest} ($(wc -c < "$dest") bytes)"
      return 0
    fi
    rm -f "${dest}.partial"
    echo "  failed"
  done
  return 1
}

azure_ready() {
  [[ "$FORCE" != "1" ]] \
    && [[ -s "$AZURE_DIR/PdM_telemetry.csv" ]] \
    && [[ -s "$AZURE_DIR/PdM_errors.csv" ]] \
    && [[ -s "$AZURE_DIR/PdM_maint.csv" ]] \
    && [[ -s "$AZURE_DIR/PdM_failures.csv" ]] \
    && [[ -s "$AZURE_DIR/PdM_machines.csv" ]]
}

echo "== Azure predictive maintenance (5 CSVs) =="
if azure_ready; then
  echo "  already present (set FORCE=1 to re-download)"
else
  BLOB="https://azuremlsampleexperiments.blob.core.windows.net/datasets"
  GH="https://raw.githubusercontent.com/microsoft/sqlworkshops/master/SQLServerAndAzureMachineLearning/ML%20Services%20for%20SQL%20Server/data"
  MIRROR="https://raw.githubusercontent.com/ashishpatel26/Predictive_Maintenance_using_Machine-Learning_Microsoft_Casestudy/master/data"
  ok=1
  for f in PdM_telemetry.csv PdM_errors.csv PdM_maint.csv PdM_failures.csv PdM_machines.csv; do
    echo "GET ${f}"
    if ! fetch "$AZURE_DIR/$f" "$BLOB/$f" "$GH/$f" "$MIRROR/$f"; then
      ok=0
      echo "ERROR: could not download ${f}" >&2
    fi
  done
  if [[ "$ok" != "1" ]]; then
    cat >&2 <<'EOF'

MANUAL STEP: place these five files in data/raw/azure/ and rerun.
  PdM_telemetry.csv
  PdM_errors.csv
  PdM_maint.csv
  PdM_failures.csv
  PdM_machines.csv

Sources, in the order the script already tried:
  1. Azure blob (from the build plan):
     https://azuremlsampleexperiments.blob.core.windows.net/datasets/PdM_telemetry.csv
     Swap the file name for the other four CSVs.
  2. Microsoft mirror (MIT-licensed sqlworkshops repo):
     https://github.com/microsoft/sqlworkshops/tree/master/SQLServerAndAzureMachineLearning/ML%20Services%20for%20SQL%20Server/data
  3. Kaggle, which needs an account and is not required if the CSVs are already on disk:
     https://www.kaggle.com/datasets/arnabbiswas1/microsoft-azure-predictive-maintenance

The rest of the pipeline only reads data/raw/. It does not call the Kaggle API.
EOF
    exit 1
  fi
fi

echo "== AI4I 2020 =="
AI4I_PATH="$AI4I_DIR/ai4i2020.csv"
if [[ "$FORCE" != "1" && -s "$AI4I_PATH" ]]; then
  echo "  already present"
else
  if ! fetch "$AI4I_PATH" \
      "https://archive.ics.uci.edu/ml/machine-learning-databases/00601/ai4i2020.csv" \
      "https://archive.ics.uci.edu/static/public/601/ai4i2020.csv"; then
    cat >&2 <<'EOF'

MANUAL STEP: download the AI4I 2020 CSV and save it as data/raw/ai4i/ai4i2020.csv
  https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset
  Direct file: https://archive.ics.uci.edu/ml/machine-learning-databases/00601/ai4i2020.csv
EOF
    exit 1
  fi
fi

echo "== NASA C-MAPSS =="
if [[ "$FORCE" != "1" && -s "$CMAPSS_DIR/train_FD001.txt" && -s "$CMAPSS_DIR/test_FD001.txt" && -s "$CMAPSS_DIR/RUL_FD001.txt" ]]; then
  echo "  FD001 files already present"
else
  ZIP="$CMAPSS_DIR/CMAPSSData.zip"
  if ! fetch "$ZIP" \
      "https://data.nasa.gov/docs/legacy/CMAPSSData.zip" \
      "https://phm-datasets.s3.amazonaws.com/NASA/6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip"; then
    cat >&2 <<'EOF'

MANUAL STEP: download CMAPSSData.zip, unzip it, and place these files in data/raw/cmapss/
  train_FD001.txt
  test_FD001.txt
  RUL_FD001.txt
Sources:
  https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data
  https://data.nasa.gov/docs/legacy/CMAPSSData.zip
  https://phm-datasets.s3.amazonaws.com/NASA/6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip
  The S3 object is a zip that contains CMAPSSData.zip. Unzip twice.
EOF
    exit 1
  fi
  tmp="$(mktemp -d)"
  unzip -qo "$ZIP" -d "$tmp"
  inner="$(find "$tmp" -name 'CMAPSSData.zip' | head -n 1 || true)"
  if [[ -n "$inner" ]]; then
    unzip -qo "$inner" -d "$CMAPSS_DIR"
  fi
  find "$tmp" -name 'train_FD001.txt' -o -name 'test_FD001.txt' -o -name 'RUL_FD001.txt' \
    | while read -r f; do cp "$f" "$CMAPSS_DIR/"; done
  # Some zips unpack the text files at the top level.
  find "$tmp" -name 'train_FD001.txt' -exec cp {} "$CMAPSS_DIR/" \;
  rm -rf "$tmp"
  if [[ ! -s "$CMAPSS_DIR/train_FD001.txt" || ! -s "$CMAPSS_DIR/test_FD001.txt" || ! -s "$CMAPSS_DIR/RUL_FD001.txt" ]]; then
    echo "ERROR: the C-MAPSS zip did not contain FD001 train, test, and RUL files." >&2
    exit 1
  fi
  echo "  FD001 files ready in ${CMAPSS_DIR}"
fi

echo "Download finished."
