"""Explicit manual controls and budget preflight, without model execution."""

import argparse
import asyncio
import json
import logging
import math
import signal
from functools import partial
from pathlib import Path

from workflow_bench.contracts import E1Config, JsonValue
from workflow_bench.data import DataError, read_json, resource_schema, validate_json
from workflow_bench.execution import ArtifactError
from workflow_bench.experiment import ControlledSubmission, run_manual, run_measurement


def load_config(path: Path, *, output: Path) -> E1Config:
    data = read_json(path, "e1_config")
    validate_json(data, resource_schema("e1.schema.json"), "e1_config")
    if len({data["tools_port"], data["control_port"], data["broker_port"]}) != 3:
        raise DataError("invalid_ports", "e1_config")
    return E1Config(output_root=output, **data)


def model_preflight(
    budget: dict[str, JsonValue],
    *,
    runtime: dict[str, JsonValue],
    authorized: bool,
    usage: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Validate a finite plan without accessing credentials or running a model."""
    validate_json(budget, resource_schema("model-budget.schema.json"), "model_budget")
    validate_json(runtime, resource_schema("e1.schema.json"), "e1_config")
    if (
        len({runtime["tools_port"], runtime["control_port"], runtime["broker_port"]})
        != 3
    ):
        raise DataError("invalid_ports", "e1_config")
    for phase in ("attempt", "total"):
        if any(not math.isfinite(value) for value in budget[phase].values()):
            raise DataError("nonfinite_budget", "model_budget")
    if (
        not math.isfinite(budget["credential_cap_usd"])
        or budget["credential_cap_usd"] > budget["total"]["usd"]
        or any(budget["attempt"][key] > limit for key, limit in budget["total"].items())
        or runtime["total_timeout_sec"] > budget["total"]["seconds"]
    ):
        raise DataError("inconsistent_budget", "model_budget")
    if not budget["finalized"]:
        raise DataError("unapproved_budget", "model_budget")
    if not authorized:
        raise DataError("model_not_authorized", "model_budget")
    usage = usage if usage is not None else dict.fromkeys(budget["total"], 0)
    if set(usage) != set(budget["total"]) or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in usage.values()
    ):
        raise DataError("unknown_usage", "model_budget")
    remaining = {key: limit - usage[key] for key, limit in budget["total"].items()}
    if any(value <= 0 for value in remaining.values()):
        raise DataError("budget_exhausted", "model_budget")
    return {
        "remaining": remaining,
        "execution_enabled": False,
        "enforcement_verified": False,
        "max_attempts": 2,
        "model": budget["model"],
        "harness": budget["harness"],
    }


def main() -> None:
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.basicConfig(level=logging.INFO, handlers=[console])
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append")
    parser.add_argument("--controlled-submission", type=Path, action="append")
    parser.add_argument("--model-preflight", action="store_true")
    parser.add_argument("--codex", action="store_true")
    parser.add_argument("--codex-auth", type=Path)
    parser.add_argument("--authorize-model", action="store_true")
    args = parser.parse_args()
    try:
        if args.model_preflight:
            document = read_json(args.config.resolve(), "model_config")
            if not isinstance(document, dict) or set(document) != {"budget", "runtime"}:
                raise DataError("invalid_schema", "model_config")
            plan = model_preflight(
                document["budget"], runtime=document["runtime"], authorized=False
            )
            print(json.dumps(plan))
            return
        composer = None
        if args.codex:
            from workflow_bench.composer import codex_preflight, submit_codex

            document = read_json(args.config.resolve(), "codex_config")
            if not isinstance(document, dict) or set(document) not in (
                {"runtime", "composer"},
                {"runtime", "composer", "budget"},
            ):
                raise DataError("invalid_schema", "codex_config")
            codex_preflight(
                document["composer"],
                budget=document.get("budget"),
                runtime=document["runtime"],
                authorized=args.authorize_model,
                auth_path=args.codex_auth.resolve() if args.codex_auth else None,
            )
            if (
                args.task is None
                or args.output is None
                or args.case
                or args.controlled_submission
            ):
                parser.error(
                    "--codex requires --task and --output, without controlled submissions or --case"
                )
            runtime = document["runtime"]
            validate_json(runtime, resource_schema("e1.schema.json"), "e1_config")
            if (
                len(
                    {
                        runtime["tools_port"],
                        runtime["control_port"],
                        runtime["broker_port"],
                    }
                )
                != 3
            ):
                raise DataError("invalid_ports", "e1_config")
            config = E1Config(output_root=args.output.resolve(), **runtime)
            composer = partial(
                submit_codex,
                composer=document["composer"],
                budget=document.get("budget"),
                authorized=args.authorize_model,
                auth_path=args.codex_auth.resolve() if args.codex_auth else None,
            )
        elif (
            args.task is None
            or args.output is None
            or (not args.case and not args.controlled_submission)
        ):
            parser.error(
                "manual runs require --task, --output and --case or --controlled-submission"
            )
        if args.controlled_submission and (
            args.case or len(args.controlled_submission) > 2
        ):
            parser.error(
                "controlled measurement accepts up to two submissions and selects full sets"
            )
        if not args.codex:
            config = load_config(args.config.resolve(), output=args.output.resolve())

        async def execute():
            cancel = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, cancel.set)
            try:
                if composer is not None:
                    return await run_measurement(
                        args.task.resolve(),
                        config=config,
                        cancel=cancel,
                        submit=composer,
                    )
                if args.controlled_submission:
                    return await run_measurement(
                        args.task.resolve(),
                        tuple(
                            ControlledSubmission(path.absolute())
                            for path in args.controlled_submission
                        ),
                        config=config,
                        cancel=cancel,
                    )
                return await run_manual(
                    args.task.resolve(), tuple(args.case), config=config, cancel=cancel
                )
            finally:
                for signum in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(signum)

        result = asyncio.run(execute())
        if (
            not args.codex
            and not args.controlled_submission
            and not result["evaluation"]["cases"]
        ):
            raise DataError("missing_evaluation", "evaluation")
    except Exception as error:
        code = (
            error.code
            if isinstance(error, (DataError, ArtifactError))
            else "unexpected_error"
        )
        material = error.relative_path if isinstance(error, DataError) else None
        log_ref = next(
            (
                ref
                for ref in ("harbor", "profile-export/harbor")
                if args.output is not None and (args.output / ref).is_dir()
            ),
            None,
        )
        logging.getLogger(__name__).error(
            "phase=manual result=failed error=%s code=%s material=%s log_ref=%s",
            type(error).__name__,
            code,
            material,
            log_ref,
        )
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "report": str(config.output_root / "report.json"),
                "harbor_exception": result.get("harbor_exception"),
                "score": result.get("score"),
            }
        )
    )


if __name__ == "__main__":
    main()
