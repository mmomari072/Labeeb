"""Command-line entry points for configuration-first campaign workflows."""

import argparse
import os
from pathlib import Path
from typing import List, Optional

from .campaign import CampaignError, load_manifest
from .case import Case
from .database import Database
from .results import CampaignStateStore, CaseResult
from .utils.file_io import File


def _run_campaign(path: str, state_path: Optional[str]) -> int:
    manifest = load_manifest(path)
    lengths = {len(values) for values in manifest.parameters.values()}
    if len(lengths) != 1:
        raise CampaignError("CLI run requires parameter lists with equal lengths")

    case = Case(name=manifest.name, output_files={})
    case.database = Database(data=manifest.parameters)
    case.FlagsMap = {f"#{name}#": name for name in manifest.parameters}
    for template in manifest.templates:
        case.add_file(File(file_path=template))
    execution = manifest.execution
    case.main_dir = os.getcwd()
    case.run_case_main_dir = execution.get("run_dir", f"{manifest.name}_runs")
    case.run_type = "new"
    case.exe_cmd = list(manifest.commands)
    if "timeout" in execution:
        case.timeout = execution["timeout"]
    case.launch(
        parallel=bool(execution.get("parallel", False)),
        n_workers=execution.get("n_workers"),
    )

    if state_path:
        with CampaignStateStore(state_path) as state:
            for case_id in range(len(case.database)):
                state.save(
                    result=CaseResult(case_id, case.database.get_row(case_id), "SUCCESS", 0, None),
                    input_hash=manifest.provenance()["manifest_sha256"],
                )
    print(f"Campaign '{manifest.name}' completed")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="labeeb")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("manifest")
    run = subparsers.add_parser("run")
    run.add_argument("manifest")
    run.add_argument("--state")
    status = subparsers.add_parser("status")
    status.add_argument("state")
    resume = subparsers.add_parser("resume")
    resume.add_argument("state")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            print(f"Manifest '{manifest.name}' is valid")
            return 0
        if args.command == "run":
            return _run_campaign(args.manifest, args.state)
        with CampaignStateStore(Path(args.state)) as state:
            if args.command == "status":
                print(state.summary())
            else:
                print({"pending": state.pending(state.case_ids())})
        return 0
    except Exception as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
