"""The WB-04 entry point: explicit paths, one image/limit config, no model calls."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from workflow_bench.contracts import E1Config
from workflow_bench.data import DataError, read_json, resource_schema, validate_json
from workflow_bench.experiment import run_manual


def load_config(path: Path, *, output: Path) -> E1Config:
    data = read_json(path, "e1_config")
    validate_json(data, resource_schema("e1.schema.json"), "e1_config")
    if len({data["tools_port"], data["control_port"], data["broker_port"]}) != 3:
        raise DataError("invalid_ports", "e1_config")
    return E1Config(output_root=output, **data)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config.resolve(), output=args.output.resolve())
        result = asyncio.run(
            run_manual(args.task.resolve(), tuple(args.case), config=config)
        )
    except Exception as error:
        logging.getLogger(__name__).error(
            "phase=manual result=failed error=%s output=%s",
            type(error).__name__,
            args.output,
        )
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "report": str(config.output_root / "report.json"),
                "harbor_exception": result["harbor_exception"],
            }
        )
    )
    if not result["evaluation"]["cases"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
