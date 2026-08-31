# Comprehensive Labeeb Logging Plan

## Goal

Make local and future scheduler execution diagnosable without producing output
as a side effect of importing the package. Every simulation event should be
traceable to a campaign, unit, case, command, attempt, working directory, and
result status.

## Design decisions

- Keep library imports silent and attach `logging.NullHandler` to the package
  logger. Applications and the CLI own handler configuration.
- Preserve the existing `ExecutionResult`, `Case.execution_history`, and
  per-case `log_file` interfaces for backward compatibility.
- Use hierarchical loggers (`labeeb.case`, `labeeb.coupler`,
  `labeeb.execution`, `labeeb.campaign`, and `labeeb.analysis`).
- Use structured logger fields where supported and a readable fallback format;
  never log secrets or full environment contents.
- Treat simulator stdout/stderr as execution artifacts. Keep them in the
  result object when captured, and write them to an explicitly configured file
  when file logging is requested.

## Implementation phases

1. **Core defaults**
   - Add a package-level `configure_logging()` API with idempotent behavior.
   - Add `NullHandler` and standard level/format constants.
   - Ensure repeated configuration does not duplicate handlers or modify the
     caller's root logger.

2. **Contextual execution**
   - Add a `CaseLoggerAdapter` carrying campaign/unit, case ID, and attempt.
   - Pass context from `Campaign.run()`, `Case._execute()`, and convergence
     passes into command lifecycle records.
   - Log command start, cwd, timeout, completion, exit code, duration, captured
     output sizes, output parsing, retries, and failures.

3. **Diagnostics and controls**
   - Add optional `RotatingFileHandler` configuration with explicit path,
     maximum bytes, and backup count.
   - Add campaign execution settings for log level and log path.
   - Add CLI `-q/--quiet`, `-v/--verbose`, `-vv/--debug`, and `--log-file`
     switches as a thin adapter over the API.

4. **Verification and compatibility**
   - Test handler isolation, idempotent setup, contextual records, timeout and
     non-zero command records, captured stdout/stderr, and parallel case IDs.
   - Test Python 3.8-compatible typing and logging behavior.
   - Document a log schema and artifact naming convention for case studies.

## Acceptance criteria

- `import labeeb` emits no output and adds no root handler.
- A case log identifies the case and command without inspecting internal state.
- A failed or timed-out command has an unambiguous status, exit code, duration,
  and failure context in both logs and structured results.
- Parallel and retry runs remain distinguishable and do not interleave into a
  single ambiguous record.
- Existing tests and public execution interfaces remain compatible.
