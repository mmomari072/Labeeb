"""Command-line entry points for configuration-first campaign workflows."""

import argparse
from pathlib import Path
from typing import List, Optional

from .campaign import Campaign, CampaignError, load_manifest
from .results import CampaignStateStore


def _run_campaign(path: str, state_path: Optional[str]) -> int:
    campaign = Campaign.from_manifest(path, state_path=state_path)
    results = campaign.run()
    if any(result.status != "SUCCESS" for result in results):
        raise CampaignError("One or more campaign cases failed; inspect the state store")
    print(f"Campaign '{campaign.manifest.name}' completed")
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
