"""
Simple Sensitivity Analysis with Feedback Loops

Provides a flexible approach to:
1. Create sensitivity analysis database (OAT, FOAT, LHS, etc.)
2. Execute all designs with Case runner
3. Collect results in pool
4. Use post-execution hooks to modify database based on results
5. Optionally iterate with updated parameters

This is simpler and more flexible than the three-phase adaptive workflow.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .database import Database
from .exceptions import DatabaseError

logger = logging.getLogger(__name__)


class SensitivityAnalysisLoop:
    """
    Simple sensitivity analysis with feedback loops.

    Allows you to:
    1. Create initial sensitivity design (database)
    2. Run all cases
    3. Collect results
    4. Use post-hooks to update database based on results
    5. Re-run with updated parameters
    """

    def __init__(
        self,
        case_runner: Any,
        initial_database: Database,
        max_iterations: int = 1,
    ):
        """
        Initialize sensitivity analysis loop.

        Args:
            case_runner: Case or Campaign runner
            initial_database: Initial design matrix (database with design points)
            max_iterations: Max number of loop iterations
        """
        self.case_runner = case_runner
        self.initial_database = initial_database
        self.max_iterations = max_iterations
        self.results_history = []  # List of (iteration, results_df)
        self.database_history = []  # List of (iteration, database_state)

    def run(
        self,
        update_function: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        convergence_function: Optional[Callable[[List[Dict[str, Any]]], bool]] = None,
    ) -> List[pd.DataFrame]:
        """
        Run sensitivity analysis loop with optional parameter updates.

        Args:
            update_function: Function to modify database after each iteration.
                Signature: update_function(state) -> updates_dict
                State dict contains: {"iteration", "results", "database", "all_results"}
                Returns: Dict mapping parameter names to new values

            convergence_function: Optional function to check convergence.
                Signature: convergence_function(all_results_so_far) -> bool
                Returns: True if converged, False to continue

        Returns:
            List of result DataFrames from each iteration
        """
        current_db = self.initial_database

        for iteration in range(self.max_iterations):
            logger.info(f"\n{'='*70}")
            logger.info(f"ITERATION {iteration + 1}/{self.max_iterations}")
            logger.info(f"{'='*70}")

            # Run cases with current database
            logger.info(f"Running {len(current_db)} design points...")
            self.case_runner.database = current_db

            try:
                self.case_runner.launch(parallel=False)
            except Exception as e:
                logger.warning(f"Case execution completed with status: {e}")

            # Collect results
            results_df = current_db.to_dataframe()
            self.results_history.append((iteration, results_df))
            self.database_history.append((iteration, current_db.to_dataframe()))

            logger.info(f"\nIteration {iteration + 1} Results:")
            logger.info(f"  Design points executed: {len(results_df)}")
            logger.info(f"  Columns: {list(results_df.columns)}")

            # Check convergence
            if convergence_function:
                all_results = [r[1] for r in self.results_history]
                converged = convergence_function(all_results)

                if converged:
                    logger.info(f"\n✓ Converged at iteration {iteration + 1}")
                    break

            # Update database for next iteration
            if iteration < self.max_iterations - 1 and update_function:
                logger.info(f"\nUpdating database for iteration {iteration + 2}...")

                state = {
                    "iteration": iteration,
                    "results": results_df,
                    "database": current_db,
                    "all_results": [r[1] for r in self.results_history],
                }

                updates = update_function(state)

                if updates:
                    # Create new database with updated parameters
                    new_db = current_db.to_dataframe()
                    for param_name, value in updates.items():
                        if param_name in new_db.columns:
                            new_db[param_name] = value
                            logger.info(f"  Updated {param_name} → {value}")

                    current_db = Database().from_dataframe(new_db)
                else:
                    logger.info("  No updates requested")

        logger.info(f"\n{'='*70}")
        logger.info(f"SENSITIVITY ANALYSIS COMPLETE")
        logger.info(f"  Total iterations: {len(self.results_history)}")
        logger.info(f"  Total design points: {sum(len(r[1]) for r in self.results_history)}")
        logger.info(f"{'='*70}")

        return [r[1] for r in self.results_history]

    def get_combined_results(self) -> pd.DataFrame:
        """Get all results from all iterations combined."""
        if not self.results_history:
            raise DatabaseError("No results available - run workflow first")

        dfs = []
        for iteration, results_df in self.results_history:
            results_df = results_df.copy()
            results_df.insert(0, "iteration", iteration)
            dfs.append(results_df)

        return pd.concat(dfs, ignore_index=True)

    def get_iteration_results(self, iteration: int) -> pd.DataFrame:
        """Get results from specific iteration."""
        for it, results_df in self.results_history:
            if it == iteration:
                return results_df
        raise DatabaseError(f"No results for iteration {iteration}")

    def export_all_results(self, filepath: str) -> None:
        """Export all results from all iterations."""
        combined = self.get_combined_results()
        combined.to_csv(filepath, index=False)
        logger.info(f"Exported all results to {filepath}")

    def summary(self) -> Dict[str, Any]:
        """Get summary statistics across all iterations."""
        if not self.results_history:
            return {}

        summary = {
            "total_iterations": len(self.results_history),
            "total_design_points": sum(len(r[1]) for r in self.results_history),
            "iterations": {},
        }

        for iteration, results_df in self.results_history:
            summary["iterations"][iteration] = {
                "design_points": len(results_df),
                "columns": list(results_df.columns),
            }

        return summary


def simple_sensitivity_with_feedback(
    case_runner: Any,
    initial_database: Database,
    update_function: Callable[[Dict[str, Any]], Dict[str, Any]],
    convergence_function: Optional[Callable[[List[pd.DataFrame]], bool]] = None,
    max_iterations: int = 3,
) -> List[pd.DataFrame]:
    """
    Convenience function for simple sensitivity analysis with feedback loops.

    Args:
        case_runner: Case or Campaign runner
        initial_database: Initial design matrix
        update_function: Function to update parameters based on results
        convergence_function: Optional convergence check
        max_iterations: Maximum iterations

    Returns:
        List of result DataFrames from each iteration

    Example:
        def my_update(state):
            results = state["results"]
            best_idx = results["KEFF"].idxmax()
            best_row = results.loc[best_idx]

            return {
                "RHO": best_row["RHO"],
                "WF": best_row["WF"],
            }

        results = simple_sensitivity_with_feedback(
            case_runner=case_runner,
            initial_database=design_db,
            update_function=my_update,
            max_iterations=3,
        )
    """
    loop = SensitivityAnalysisLoop(
        case_runner=case_runner,
        initial_database=initial_database,
        max_iterations=max_iterations,
    )

    return loop.run(
        update_function=update_function,
        convergence_function=convergence_function,
    )
