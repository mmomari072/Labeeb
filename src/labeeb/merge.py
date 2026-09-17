"""Utilities for merging output databases and results across campaigns."""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import pandas as pd


def merge_case_results(
    results_dfs: List[pd.DataFrame],
    campaign_ids: Optional[List[str]] = None,
    reset_index: bool = True,
) -> pd.DataFrame:
    """
    Merge case results from multiple campaigns into a single DataFrame.

    Args:
        results_dfs: List of DataFrames exported via export_case_results()
        campaign_ids: Optional list of campaign identifiers (same length as results_dfs)
        reset_index: If True, reset index after concatenation

    Returns:
        Merged DataFrame with all cases from all campaigns
    """
    if not results_dfs:
        return pd.DataFrame()

    merged = pd.concat(results_dfs, ignore_index=reset_index)

    if campaign_ids:
        if len(campaign_ids) != len(results_dfs):
            raise ValueError(
                f"campaign_ids length ({len(campaign_ids)}) must match "
                f"results_dfs length ({len(results_dfs)})"
            )
        campaign_col = []
        for i, cid in enumerate(campaign_ids):
            campaign_col.extend([cid] * len(results_dfs[i]))
        merged.insert(0, "campaign_id", campaign_col)

    return merged


def merge_case_info_json(
    case_directories: Iterable[Union[str, Path]],
) -> pd.DataFrame:
    """
    Merge case_info.json files from multiple case directories.

    Args:
        case_directories: Paths to case directories containing case_info.json

    Returns:
        DataFrame with merged case metadata and execution details
    """
    all_cases = []

    for case_dir in case_directories:
        case_path = Path(case_dir)
        case_info_path = case_path / "case_info.json"

        if not case_info_path.exists():
            continue

        try:
            with open(case_info_path, "r", encoding="utf-8") as f:
                case_info = json.load(f)

            # Extract command summary
            commands = case_info.get("execution", {}).get("commands_executed", [])
            total_duration = sum(
                cmd.get("duration_seconds", 0) for cmd in commands
            )

            record = {
                "case_id": case_info.get("case_id"),
                "case_name": case_info.get("case_name"),
                "status": case_info.get("execution", {}).get("status"),
                "num_commands": len(commands),
                "total_duration_seconds": total_duration,
                "start_time": case_info.get("execution", {}).get("start_time"),
                "end_time": case_info.get("execution", {}).get("end_time"),
                "case_directory": str(case_path),
            }

            # Add parameters as separate columns (flattened)
            db_attrs = case_info.get("database_attributes", {})
            if db_attrs:
                for key, value in db_attrs.items():
                    record[f"param_{key}"] = value

            all_cases.append(record)

        except Exception as e:
            print(f"Warning: Failed to read {case_info_path}: {e}")
            continue

    return pd.DataFrame(all_cases)


def merge_outputs_with_parameters(
    campaign: "Campaign",  # noqa: F821
    output_format: str = "flat",
) -> pd.DataFrame:
    """
    Merge case outputs with input parameters into a single DataFrame.

    Args:
        campaign: Executed Campaign instance
        output_format: "flat" for individual rows, "nested" for dict columns

    Returns:
        DataFrame combining parameters, outputs, and execution metadata
    """
    output_data = []

    for case in campaign.cases:
        if case.case_id >= len(campaign.database):
            continue

        row = campaign.database.get_row(case.case_id)

        # Start with parameters
        row_dict = dict(row) if hasattr(row, "items") else row.to_dict()
        record = {
            "case_id": case.case_id,
            **row_dict,
        }

        # Add execution metadata
        if case.execution_history:
            last_exec = case.execution_history[-1]
            record["status"] = last_exec.get("status", "UNKNOWN")
            record["exit_code"] = last_exec.get("exit_code")
            record["duration_seconds"] = sum(
                cmd.get("duration_seconds", 0) for cmd in case.execution_history
            )
        else:
            record["status"] = "UNKNOWN"
            record["exit_code"] = None
            record["duration_seconds"] = 0

        # Add outputs
        if output_format == "flat":
            for metric_name, values in case.outputs.items():
                if values:
                    record[f"output_{metric_name}"] = values[0] if len(values) == 1 else values
                    if isinstance(values[0], (int, float)):
                        record[f"output_{metric_name}_mean"] = sum(values) / len(values)
        else:  # nested
            record["outputs"] = case.outputs

        output_data.append(record)

    return pd.DataFrame(output_data)


def aggregate_by_parameters(
    df: pd.DataFrame,
    group_by: List[str],
    agg_columns: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Aggregate results by parameter values.

    Args:
        df: DataFrame with results
        group_by: Column names to group by (parameter names)
        agg_columns: Dict of {column_name: aggregation_function}
                    Examples: {'duration_seconds': 'mean', 'case_id': 'count'}

    Returns:
        Aggregated DataFrame
    """
    if agg_columns is None:
        agg_columns = {
            "case_id": "count",
            "status": lambda x: (x == "SUCCESS").sum(),
            "duration_seconds": "mean",
        }

    # Filter to only existing columns
    valid_group_by = [col for col in group_by if col in df.columns]
    valid_agg_cols = {
        col: func for col, func in agg_columns.items() if col in df.columns
    }

    if not valid_group_by:
        raise ValueError(f"None of the group_by columns exist in DataFrame: {group_by}")

    if not valid_agg_cols:
        raise ValueError(
            f"None of the agg_columns exist in DataFrame: {list(agg_columns.keys())}"
        )

    return df.groupby(valid_group_by).agg(valid_agg_cols).reset_index()


def validate_merge(
    merged_df: pd.DataFrame,
    case_id_column: str = "case_id",
    required_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Validate merged DataFrame for consistency.

    Args:
        merged_df: Merged DataFrame to validate
        case_id_column: Name of case ID column
        required_columns: List of columns that must exist

    Returns:
        Dict with validation results and any warnings/errors
    """
    results = {
        "valid": True,
        "warnings": [],
        "errors": [],
        "stats": {
            "total_rows": len(merged_df),
            "unique_cases": merged_df[case_id_column].nunique() if case_id_column in merged_df.columns else 0,
            "duplicates": merged_df.duplicated(subset=[case_id_column]).sum() if case_id_column in merged_df.columns else 0,
        },
    }

    # Check for duplicates
    if results["stats"]["duplicates"] > 0:
        results["valid"] = False
        results["errors"].append(
            f"Found {results['stats']['duplicates']} duplicate case_ids"
        )

    # Check for missing values
    missing_cols = merged_df.columns[merged_df.isna().any()]
    if len(missing_cols) > 0:
        results["warnings"].append(
            f"Missing values in columns: {list(missing_cols)}"
        )

    # Check required columns
    if required_columns:
        missing_required = [col for col in required_columns if col not in merged_df.columns]
        if missing_required:
            results["valid"] = False
            results["errors"].append(
                f"Missing required columns: {missing_required}"
            )

    # Check data types
    if case_id_column in merged_df.columns:
        if not pd.api.types.is_integer_dtype(merged_df[case_id_column]):
            results["warnings"].append(
                f"{case_id_column} is not integer type"
            )

    return results


def export_merge_report(
    merged_df: pd.DataFrame,
    output_path: Union[str, Path],
    format: str = "csv",
) -> Path:
    """
    Export merged DataFrame in specified format.

    Args:
        merged_df: Merged DataFrame
        output_path: Output file path
        format: Export format ('csv', 'parquet', 'json', 'xlsx')

    Returns:
        Path to exported file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if format == "csv":
        merged_df.to_csv(output_path, index=False)
    elif format == "parquet":
        merged_df.to_parquet(output_path, index=False)
    elif format == "json":
        merged_df.to_json(output_path, orient="records", indent=2)
    elif format == "xlsx":
        merged_df.to_excel(output_path, index=False, sheet_name="Results")
    else:
        raise ValueError(
            f"Unsupported format: {format}. "
            f"Supported: csv, parquet, json, xlsx"
        )

    return output_path
