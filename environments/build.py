"""Build the small shared simulator/verifier image from a public allowlist."""

import argparse
import json
import logging
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "python@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a"
N8N = (
    "n8nio/n8n@sha256:6f532d3b819cfe66c6a13c5375228f312c53df1abaa11a377eb8c3d3f105c363"
)
RUNNER = "ghcr.io/n8n-io/runners@sha256:32619142405e7f4a02eedffe8584214c7e0b9b09d3753094e4212aee5f4d0045"


def build_image(context: Path, *, target: str, tag: str, log: Path) -> None:
    started = time.monotonic()
    with log.open("w") as stream:
        process = subprocess.Popen(
            ["docker", "build", "--target", target, "-t", tag, str(context)],
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            while True:
                try:
                    status = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    logging.info(
                        "phase=image-setup elapsed=%.0fs log=%s",
                        time.monotonic() - started,
                        log,
                    )
                    if time.monotonic() - started >= 360:
                        raise TimeoutError("image_setup_timeout") from None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    if status:
        raise RuntimeError(f"image_setup_failed log={log}")


def build(output: Path, *, simapp: Path, codex_version: str | None = None) -> None:
    if codex_version is not None and not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", codex_version
    ):
        raise ValueError("invalid_codex_version")
    output.parent.mkdir(parents=True, exist_ok=True)
    context = output.parent / "image-context"
    context.mkdir(mode=0o700)
    try:
        code = context / "workflow_bench"
        code.mkdir()
        for name in (
            "__init__.py",
            "contracts.py",
            "data.py",
            "evaluation.py",
            "mcp.py",
        ):
            shutil.copyfile(ROOT / "src/workflow_bench" / name, code / name)
        shutil.copytree(ROOT / "src/workflow_bench/resources", code / "resources")
        shutil.copytree(
            simapp,
            context / "simapp",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        app_contract = json.loads((simapp / "tools.json").read_bytes())
        app_tag = app_contract["app_image"]
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        packages = {package["name"]: package for package in lock["package"]}
        needed, pending = set(), ["aiohttp", "jsonschema", "referencing"]
        while pending:
            name = pending.pop()
            if name not in needed:
                needed.add(name)
                pending.extend(
                    d["name"] for d in packages[name].get("dependencies", [])
                )
        requirements = []
        for name in sorted(needed):
            package = packages[name]
            hashes = {item["hash"] for item in package.get("wheels", [])}
            if package.get("sdist"):
                hashes.add(package["sdist"]["hash"])
            requirements.append(
                f"{name}=={package['version']} "
                + " ".join("--hash=" + value for value in sorted(hashes))
            )
        (context / "requirements.txt").write_text("\n".join(requirements) + "\n")
        # Native MCP children filter PYTHONPATH; package discovery must survive that.
        (context / "Dockerfile").write_text(f"""FROM {BASE} AS app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY workflow_bench /app/workflow_bench
COPY simapp /app/simapp
RUN mkdir /bench && ln -s /tests/bench-input /bench/input && ln -s /app/simapp/tools.json /bench/tools.json && ln -s /app/simapp/app.py /bench/simulator.py
COPY simapp/state.schema.json /bench/state.schema.json
RUN python -c "import site; from pathlib import Path; Path(site.getsitepackages()[0], 'workflow_bench.pth').write_text('/app')"
CMD ["tail", "-f", "/dev/null"]
""")
        if codex_version is not None:
            with (context / "Dockerfile").open("a") as dockerfile:
                dockerfile.write(
                    f"\nFROM app AS composer\nRUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && npm install -g @openai/codex@{codex_version} && rm -rf /var/lib/apt/lists/* /root/.npm\nRUN codex --version\n"
                )
        build_image(
            context,
            target="app",
            tag=app_tag,
            log=output.parent / "image-build.log",
        )
        image = subprocess.check_output(
            ["docker", "image", "inspect", app_tag, "--format", "{{.Id}}"],
            text=True,
            timeout=10,
        ).strip()
        config = {
            "app_image": image,
            "n8n_image": N8N,
            "runner_image": RUNNER,
            "setup_timeout_sec": 90,
            "submission_timeout_sec": 20,
            "execute_timeout_sec": 45,
            "tool_timeout_sec": 5,
            "control_timeout_sec": 10,
            "drain_timeout_sec": 10,
            "verifier_timeout_sec": 30,
            "cleanup_timeout_sec": 25,
            "total_timeout_sec": 360,
            "cpus": 1,
            "memory_mb": 1024,
            "max_calls": 8,
            "tools_port": 8080,
            "control_port": 8081,
            "broker_port": 5679,
        }
        with output.open("x") as stream:
            json.dump(config, stream, indent=2)
        output.chmod(0o600)
        if codex_version is not None:
            tag = "wb-codex:" + codex_version
            build_image(
                context,
                target="composer",
                tag=tag,
                log=output.parent / "codex-image-build.log",
            )
            composer_image = subprocess.check_output(
                ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                text=True,
                timeout=10,
            ).strip()
            with (output.parent / "codex-config.json").open("x") as stream:
                json.dump(
                    {
                        "runtime": config,
                        "composer": {
                            "mode": "model-free",
                            "image": composer_image,
                            "cli_version": codex_version,
                            "model": "synthetic",
                            "reasoning_effort": "low",
                            "exploration_max_calls": config["max_calls"],
                        },
                    },
                    stream,
                    indent=2,
                )
            (output.parent / "codex-config.json").chmod(0o600)
        logging.info("phase=image-setup result=completed config=%s", output)
    finally:
        shutil.rmtree(context)
        logging.info("phase=image-cleanup result=completed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simapp", type=Path, required=True)
    parser.add_argument("--codex-version")
    args = parser.parse_args()
    build(
        args.output.resolve(),
        simapp=args.simapp.resolve(),
        codex_version=args.codex_version,
    )
