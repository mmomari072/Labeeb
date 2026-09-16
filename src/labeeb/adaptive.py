"""
Adaptive Sensitivity Analysis Workflow

Three-phase adaptive workflow for parameter optimization and sensitivity analysis:
1. SCREENING: OAT/FOAT design to identify sensitive parameters (Morris analysis)
2. TARGETING: Feedback-driven refinement toward target values using sensitivities
3. REFINEMENT: Adaptive sampling to converge on optimal region
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from enum import Enum

import numpy as np
import pandas as pd

from .analysis import correlation_analysis, morris_screening
from .database import Database, Attribute
from .exceptions import DatabaseError

logger = logging.getLogger(__name__)


class Phase(Enum):
    """Workflow phase identifier."""
    SCREENING = "screening"
    TARGETING = "targeting"
    REFINEMENT = "refinement"


@dataclass
class DesignPoint:
    """Single design point with execution results."""
    parameters: Dict[str, float]  # Input parameters
    outputs: Dict[str, float]     # Simulation outputs (KEFF, power, etc.)
    iteration: int
    phase: Phase
    case_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResultsPool:
    """Collects and analyzes design points across all phases."""

    def __init__(self, target_output: Optional[str] = None):
        """
        Initialize results pool.

        Args:
            target_output: Output key to focus sensitivity analysis on (e.g., 'KEFF')
        """
        self.points: List[DesignPoint] = []
        self.target_output = target_output or "KEFF"

    def add(self, point: DesignPoint) -> None:
        """Add a design point to the pool."""
        self.points.append(point)
        logger.debug(f"Added design point: phase={point.phase.value}, iter={point.iteration}")

    def extend(self, points: List[DesignPoint]) -> None:
        """Add multiple design points."""
        for point in points:
            self.add(point)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert pool to DataFrame for analysis."""
        if not self.points:
            raise DatabaseError("Results pool is empty")

        records = []
        for point in self.points:
            row = {
                "phase": point.phase.value,
                "iteration": point.iteration,
                "case_id": point.case_id,
            }
            row.update(point.parameters)
            row.update(point.outputs)
            row.update(point.metadata)
            records.append(row)

        return pd.DataFrame(records)

    def estimate_sensitivities(self, phase: Optional[Phase] = None) -> pd.DataFrame:
        """
        Estimate parameter sensitivities using correlation analysis.

        Args:
            phase: Filter to specific phase (default: all phases)

        Returns:
            DataFrame with Pearson and Spearman correlations for each parameter
        """
        if not self.points:
            raise DatabaseError("Cannot estimate sensitivities: pool is empty")

        df = self.to_dataframe()
        if phase:
            df = df[df["phase"] == phase.value]

        # Identify parameters (exclude metadata columns)
        metadata_cols = {"phase", "iteration", "case_id"}
        output_cols = set(self.points[0].outputs.keys())
        param_cols = [col for col in df.columns if col not in metadata_cols and col not in output_cols]

        inputs = df[param_cols]
        output = df[self.target_output]

        return correlation_analysis(inputs, output)

    def estimate_morris_effects(self, phase: Optional[Phase] = None) -> pd.DataFrame:
        """
        Estimate Morris elementary effects for OAT design.

        Args:
            phase: Filter to specific phase (default: screening phase)

        Returns:
            DataFrame with mean effect, mean absolute effect, and std effect
        """
        if not self.points:
            raise DatabaseError("Cannot estimate Morris effects: pool is empty")

        phase = phase or Phase.SCREENING
        df = self.to_dataframe()
        df = df[df["phase"] == phase.value]

        if len(df) < 2:
            raise DatabaseError(f"Need at least 2 points for Morris analysis, got {len(df)}")

        # Extract parameter samples in order
        metadata_cols = {"phase", "iteration", "case_id"}
        output_cols = set(self.points[0].outputs.keys())
        param_cols = [col for col in df.columns if col not in metadata_cols and col not in output_cols]

        samples = df[param_cols].values
        output = df[self.target_output].values

        return morris_screening(samples, output)

    def export_to_csv(self, filepath: str) -> None:
        """Export results pool to CSV file."""
        df = self.to_dataframe()
        df.to_csv(filepath, index=False)
        logger.info(f"Exported {len(df)} design points to {filepath}")

    def get_phase_points(self, phase: Phase) -> List[DesignPoint]:
        """Get all points from a specific phase."""
        return [p for p in self.points if p.phase == phase]


class AdaptiveSensitivityAnalysis:
    """
    Master coordinator for three-phase adaptive sensitivity workflow.

    Phases:
    1. SCREENING: OAT design for sensitivity ranking
    2. TARGETING: Feedback-driven refinement using sensitivities
    3. REFINEMENT: Adaptive sampling to converge on optimum
    """

    def __init__(
        self,
        case_runner: Any,  # Case or Campaign runner
        base_database: Database,
        target_output: str = "KEFF",
        target_value: float = 1.0,
        tolerance: float = 1e-4,
    ):
        """
        Initialize adaptive workflow.

        Args:
            case_runner: Labeeb Case or Campaign runner
            base_database: Initial database (used as template)
            target_output: Output to track (e.g., 'KEFF')
            target_value: Target value for convergence
            tolerance: Convergence tolerance
        """
        self.case_runner = case_runner
        self.base_db = base_database
        self.target_output = target_output
        self.target_value = target_value
        self.tolerance = tolerance
        self.pool = ResultsPool(target_output=target_output)
        self.sensitivities = None

    def phase1_screening(
        self,
        parameter_ranges: Dict[str, Sequence[float]],
        seed: int = 42,
    ) -> pd.DataFrame:
        """
        PHASE 1: Sensitivity screening using OAT design.

        Args:
            parameter_ranges: Dict mapping parameter names to value sequences
                Example: {"RHO": [18.0, 19.0, 20.0], "WF": [0.015, 0.020, 0.025]}
            seed: Random seed for reproducibility

        Returns:
            DataFrame with Morris sensitivities
        """
        logger.info("=== Phase 1: Sensitivity Screening (OAT Design) ===")

        from .sampler import OATConstructor

        # Build OAT design
        oat = OATConstructor()
        oat.add_case(parameter_ranges)
        oat_dict = oat.construct()

        # Execute each design point
        n_points = len(oat_dict[list(oat_dict.keys())[0]])
        for point_idx in range(n_points):
            params = {key: oat_dict[key][point_idx] for key in parameter_ranges.keys()}

            # Run simulation
            try:
                result = self.case_runner.run_case(params)
                outputs = result.outputs if hasattr(result, 'outputs') else {}
            except Exception as e:
                logger.error(f"Failed to run point {point_idx}: {e}")
                outputs = {self.target_output: float('nan')}

            # Record in pool
            point = DesignPoint(
                parameters=params,
                outputs=outputs,
                iteration=point_idx,
                phase=Phase.SCREENING,
                case_id=point_idx,
                metadata={"point_type": "oat"}
            )
            self.pool.add(point)
            logger.info(f"  Point {point_idx+1}/{n_points}: {self.target_output}={outputs.get(self.target_output, 'N/A')}")

        # Estimate sensitivities
        self.sensitivities = self.pool.estimate_morris_effects(phase=Phase.SCREENING)
        logger.info("\nParameter Sensitivities (Morris Analysis):")
        logger.info(self.sensitivities)

        return self.sensitivities

    def phase2_targeting(
        self,
        initial_params: Dict[str, float],
        feedback_fn: Optional[Callable[[Dict[str, Any]], Dict[str, float]]] = None,
        max_iterations: int = 10,
        damping_factor: float = 0.5,
    ) -> Dict[str, float]:
        """
        PHASE 2: Feedback-driven refinement toward target.

        Uses sensitivities from Phase 1 to guide parameter adjustments.

        Args:
            initial_params: Starting parameter values
            feedback_fn: Custom feedback function. If None, uses sensitivity-scaled proportional control.
                Signature: feedback_fn(state: Dict) -> Dict[str, float] with adjustments
            max_iterations: Maximum refinement iterations
            damping_factor: Damping for parameter updates (0, 1]

        Returns:
            Dictionary with converged parameter values
        """
        logger.info(f"\n=== Phase 2: Targeting (max_iter={max_iterations}) ===")

        current_params = initial_params.copy()
        converged = False
        iteration = 0

        for iteration in range(max_iterations):
            # Run simulation
            try:
                result = self.case_runner.run_case(current_params)
                outputs = result.outputs if hasattr(result, 'outputs') else {}
            except Exception as e:
                logger.error(f"Failed at iteration {iteration}: {e}")
                break

            current_output = outputs.get(self.target_output, float('nan'))
            error = self.target_value - current_output

            logger.info(f"  Iter {iteration+1}: {self.target_output}={current_output:.6f}, error={error:+.6f}")

            # Check convergence
            if abs(error) <= self.tolerance:
                converged = True
                logger.info(f"  ✓ Converged at iteration {iteration+1}")
                break

            # Update parameters
            if feedback_fn:
                state = {
                    "parameters": current_params,
                    "outputs": outputs,
                    "error": error,
                    "sensitivities": self.sensitivities,
                }
                adjustments = feedback_fn(state)
            else:
                # Default: sensitivity-scaled proportional feedback
                adjustments = self._default_feedback(
                    current_params, error, damping_factor
                )

            for key, adjustment in adjustments.items():
                current_params[key] += adjustment
                logger.info(f"    {key}: {current_params[key] - adjustment:.4f} → {current_params[key]:.4f}")

            # Record in pool
            point = DesignPoint(
                parameters=current_params.copy(),
                outputs=outputs,
                iteration=iteration,
                phase=Phase.TARGETING,
                case_id=iteration,
                metadata={"error": error, "converged": converged}
            )
            self.pool.add(point)

        logger.info(f"Phase 2 complete: converged={converged}, final_params={current_params}")
        return current_params

    def _default_feedback(
        self,
        params: Dict[str, float],
        error: float,
        damping: float = 0.5,
    ) -> Dict[str, float]:
        """
        Default feedback control using sensitivities.

        For each parameter, adjustment = (error / sensitivity) * damping
        """
        adjustments = {}

        if self.sensitivities is None or self.sensitivities.empty:
            # Fallback: simple proportional control
            for param_name in params.keys():
                adjustments[param_name] = error * damping
        else:
            # Use Morris sensitivities to scale adjustments
            for param_name in params.keys():
                if param_name in self.sensitivities.index:
                    sensitivity = self.sensitivities.loc[param_name, "mean_absolute_effect"]
                    if sensitivity > 0:
                        adjustment = (error / sensitivity) * damping
                    else:
                        adjustment = error * damping
                else:
                    adjustment = error * damping

                adjustments[param_name] = adjustment

        return adjustments

    def phase3_refinement(
        self,
        converged_params: Dict[str, float],
        param_bounds: Dict[str, Tuple[float, float]],
        n_points: int = 10,
        strategy: str = "grid",
    ) -> None:
        """
        PHASE 3: Adaptive refinement around convergence region.

        Args:
            converged_params: Parameters from Phase 2 convergence
            param_bounds: Dict mapping parameter names to (min, max) tuples
            n_points: Number of refinement points
            strategy: Sampling strategy ('grid', 'random', 'latin_hypercube')
        """
        logger.info(f"\n=== Phase 3: Refinement (n_points={n_points}, strategy={strategy}) ===")

        if strategy == "grid":
            points = self._generate_grid_points(converged_params, param_bounds, n_points)
        elif strategy == "random":
            points = self._generate_random_points(converged_params, param_bounds, n_points, seed=42)
        elif strategy == "latin_hypercube":
            points = self._generate_lhs_points(converged_params, param_bounds, n_points, seed=42)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Execute refinement points
        for idx, params in enumerate(points):
            try:
                result = self.case_runner.run_case(params)
                outputs = result.outputs if hasattr(result, 'outputs') else {}
            except Exception as e:
                logger.error(f"Failed at refinement point {idx}: {e}")
                outputs = {self.target_output: float('nan')}

            point = DesignPoint(
                parameters=params,
                outputs=outputs,
                iteration=idx,
                phase=Phase.REFINEMENT,
                case_id=idx,
                metadata={"strategy": strategy}
            )
            self.pool.add(point)
            logger.info(f"  Point {idx+1}/{n_points}: {self.target_output}={outputs.get(self.target_output, 'N/A')}")

    def _generate_grid_points(
        self,
        center: Dict[str, float],
        bounds: Dict[str, Tuple[float, float]],
        n_total: int,
    ) -> List[Dict[str, float]]:
        """Generate grid points around convergence center."""
        param_names = list(center.keys())
        n_per_dim = int(np.ceil(n_total ** (1.0 / len(param_names))))

        points = []
        for param_name in param_names:
            min_val, max_val = bounds[param_name]
            linspace = np.linspace(min_val, max_val, n_per_dim)

            for val in linspace:
                point = center.copy()
                point[param_name] = val
                points.append(point)

        return points[:n_total]

    def _generate_random_points(
        self,
        center: Dict[str, float],
        bounds: Dict[str, Tuple[float, float]],
        n_points: int,
        seed: int = 42,
    ) -> List[Dict[str, float]]:
        """Generate random points within bounds."""
        rng = np.random.RandomState(seed)
        points = []

        for _ in range(n_points):
            point = {}
            for param_name in center.keys():
                min_val, max_val = bounds[param_name]
                point[param_name] = rng.uniform(min_val, max_val)
            points.append(point)

        return points

    def _generate_lhs_points(
        self,
        center: Dict[str, float],
        bounds: Dict[str, Tuple[float, float]],
        n_points: int,
        seed: int = 42,
    ) -> List[Dict[str, float]]:
        """Generate Latin Hypercube Sample points."""
        from .sampler import latin_hypercube_sample

        param_names = list(center.keys())
        param_bounds = [bounds[name] for name in param_names]

        lhs_array = latin_hypercube_sample(param_bounds, n_points, seed=seed)

        points = []
        for row in lhs_array:
            point = {name: float(val) for name, val in zip(param_names, row)}
            points.append(point)

        return points

    def run_full_workflow(
        self,
        parameter_ranges: Dict[str, Sequence[float]],
        param_bounds: Dict[str, Tuple[float, float]],
        initial_params: Dict[str, float],
        feedback_fn: Optional[Callable] = None,
        phase2_max_iter: int = 10,
        phase3_n_points: int = 10,
        phase3_strategy: str = "grid",
    ) -> ResultsPool:
        """
        Execute full three-phase adaptive workflow.

        Args:
            parameter_ranges: Parameter value sequences for Phase 1 screening
            param_bounds: Parameter bounds for Phase 3 refinement
            initial_params: Starting parameters for Phase 2
            feedback_fn: Custom feedback function for Phase 2
            phase2_max_iter: Max iterations for Phase 2
            phase3_n_points: Number of points in Phase 3
            phase3_strategy: Sampling strategy for Phase 3

        Returns:
            ResultsPool containing all design points from all phases
        """
        logger.info("╔═══════════════════════════════════════════════════════╗")
        logger.info("║  ADAPTIVE SENSITIVITY ANALYSIS WORKFLOW (3-Phase)     ║")
        logger.info("╚═══════════════════════════════════════════════════════╝")

        # Phase 1: Screening
        sensitivities = self.phase1_screening(parameter_ranges)

        # Phase 2: Targeting
        converged_params = self.phase2_targeting(
            initial_params,
            feedback_fn=feedback_fn,
            max_iterations=phase2_max_iter,
        )

        # Phase 3: Refinement
        self.phase3_refinement(
            converged_params,
            param_bounds,
            n_points=phase3_n_points,
            strategy=phase3_strategy,
        )

        logger.info("\n╔═══════════════════════════════════════════════════════╗")
        logger.info("║  WORKFLOW COMPLETE                                    ║")
        logger.info(f"║  Total design points: {len(self.pool.points)}                          ║")
        logger.info("╚═══════════════════════════════════════════════════════╝")

        return self.pool
