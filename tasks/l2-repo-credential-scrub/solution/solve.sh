#!/bin/sh
set -eu
python3 - <<'PY'
from pathlib import Path
import re

root = Path("/app/dclm")
paths = (
    "ray_processing/ray_cluster.yaml",
    "ray_processing/process.py",
    "exp_data/datasets/tokenized/"
    "rw_v2_fasttext_openhermes_vs_rw_v2_bigram_0.1_arcade100k.json",
)
for relative in paths:
    path = root / relative
    text = path.read_text()
    text = re.sub(r"AKIA[0-9A-Z]{16}", "<your-aws-access-key-id>", text)
    if relative.startswith("ray_processing/"):
        text = re.sub(
            r"(?<![A-Za-z0-9])[A-Za-z0-9]{40}(?![A-Za-z0-9])",
            "<your-aws-secret-access-key>",
            text,
        )
    text = re.sub(r"gh[pousr]_[A-Za-z0-9]{20,}", "<your-github-token>", text)
    text = re.sub(r"hf_[A-Za-z0-9]{29,}", "<your-huggingface-token>", text)
    path.write_text(text)
PY
