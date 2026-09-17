# Shielding optimization workflow

For expensive MCNP evaluations, use the demo in
`/home/omari/calculations/mcnp/labeeb_demo/untitled0_optimized.py`.
It generates an initial LHS design, executes MCNP, joins inputs and harvested
outputs in `case.outputs_db`, filters by the dose limit, and writes the lightest
feasible design plus a mass/dose Pareto front.

Mass is calculated directly from geometry and material densities. A Gaussian
Process surrogate is optionally fitted to successful dose-rate results to
propose additional candidates; every proposal must be verified by MCNP.

The optimization target is:

```
minimize shield_total_mass
subject to surface_dose_rate <= DOSE_LIMIT
```
