"""Prepare a pinned, unmodified Sapiens image without local state or submodules."""

import argparse
import io
import json
import logging
import shutil
import subprocess
import tarfile
from pathlib import Path
from uuid import uuid4

from build import build_image

from workflow_bench.composer import codex_preflight
from workflow_bench.data import DataError, read_json
from workflow_bench_integrations.sapiens import SAPIENS_REVISION


def build(source: Path, config_path: Path, output: Path) -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()
    if revision != SAPIENS_REVISION:
        raise ValueError("sapiens_revision_mismatch")
    document = read_json(config_path, "composer_config")
    if not isinstance(document, dict) or set(document) != {"runtime", "composer"}:
        raise DataError("invalid_schema", "composer_config")
    codex_preflight(
        document["composer"], budget=None, runtime=document["runtime"], authorized=False
    )
    output.parent.mkdir(parents=True, exist_ok=False)
    context = output.parent / "image-context"
    context.mkdir()
    tag = "wb-sapiens:" + revision[:12] + "-" + uuid4().hex[:12]
    base_tag = tag + "-base"
    try:
        # Only committed public runtime files; no .git, private data or desktop submodules.
        archive = subprocess.check_output(
            [
                "git",
                "-C",
                str(source),
                "archive",
                revision,
                "sapiens",
                "prompts",
                "web",
                "license",
                "sapiens4",
            ],
            timeout=10,
        )
        with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
            source_tar.extractall(context / "sapiens4", filter="data")
        (context / "sapiens4/REVISION").write_text(revision + "\n")
        subprocess.run(
            ["docker", "tag", document["composer"]["image"], base_tag],
            check=True,
            timeout=10,
        )
        (context / "Dockerfile").write_text(
            f"FROM {base_tag} AS sapiens\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends procps=2:4.0.4-9 && rm -rf /var/lib/apt/lists/*\n"
            "COPY sapiens4 /opt/sapiens\n"
            "RUN python -c \"import site; from pathlib import Path; Path(site.getsitepackages()[0], 'sapiens.pth').write_text('/opt/sapiens')\"\n"
        )
        build_image(
            context, target="sapiens", tag=tag, log=output.parent / "image-build.log"
        )
        document["composer"]["image"] = subprocess.check_output(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
            text=True,
            timeout=10,
        ).strip()
        with output.open("x") as stream:
            json.dump(document, stream, indent=2)
        output.chmod(0o600)
    finally:
        shutil.rmtree(context)
        subprocess.run(
            ["docker", "image", "rm", base_tag], capture_output=True, timeout=10
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--codex-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source.resolve(), args.codex_config.resolve(), args.output.resolve())
