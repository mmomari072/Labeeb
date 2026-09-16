# Changelog

## 2.1.0

- Construct mixed normal, uniform, OAT, constant, and derived columns together.
- Choose Monte Carlo or Latin hypercube sampling independently of distributions.
- Reuse random draws across OAT rows or generate independent draws per row.
- Resolve derived expression chains in dependency order and recompute them after
  database source updates; support explicit dependencies for row callbacks.
- Support seeded custom `draw(size, rng)` samplers and custom LHS inverse CDFs.
- Validate distribution parameters, sampling options, and design column names.

Existing data constructors and default independent Monte Carlo sampling remain
supported. Legacy custom callables manage their own RNG state. Plan serialization,
correlated mixed designs, and additional built-in distributions are future work.
