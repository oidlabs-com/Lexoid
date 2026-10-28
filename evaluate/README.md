# Browser evaluation

Odysseys is the first dataset adapter, not a universal benchmark format.
Run commands from the Lexoid repository root with its Python environment.
Selection uses the standard library; browsing requires `lexoid[browse]`.
Grading uses Lexoid's existing provider bridge and defaults to `claude-opus-5-5`.

## Select

```bash
python -m evaluate.odysseys_judge select
```

Reads the original `evaluate/data/odysseys.json` and previews the selected
tasks without creating a filtered dataset: **15 unique Easy tasks, 71 rubrics**
with the current upstream data at commit
`837814633ef948479abb3d142458f0acdb73fa65`.
Tasks match any descendant of `Ecommerce & Shopping` (13 tasks) or
`Law and Government` (2 tasks). Selection preserves entire tasks, including
other category tags, original prompts, IDs, website metadata, and all rubrics.
It deduplicates by selection rather than repeating multi-category tasks.
Each run snapshots its selected tasks, source SHA-256, and filters for later
grading. The source hash identifies the exact input without a hardcoded revision lookup.

To extend or select an offline copy:

```bash
python -m evaluate.odysseys_judge select --level medium --category "Law and Government"
python -m evaluate.odysseys_judge select --level all --all-categories
python -m evaluate.odysseys_judge select --input /path/to/odysseys.json
```

## Execute

```bash
python -m evaluate.odysseys_judge run \
  --model YOUR_BROWSER_MODEL --output evaluate/runs/baseline-01
```

`run` accepts the same `--input`, `--level`, `--category` (repeatable), and
`--all-categories` filters as `select`. Defaults remain Easy tasks in either
Ecommerce & Shopping or Law and Government.

Use `--headful` for an owned visible browser, or `--cdp-url` with a dedicated
evaluation browser. Do not attach a personal browsing session. Defaults are
100 task actions, 20 actions per navigator invocation, 20 captured pages, and
a 600-second task deadline; these are **Lexoid limits, not equivalent to
OSWorld's 100 steps**. Configure them with `--max-steps`,
`--max-steps-per-run`, `--max-pages`, and `--deadline`.

Runs are sequential. A new output directory is required. Each task saves
the full structured result, lifecycle events, elapsed time, and explicit
execution errors. Errors do not remove tasks from the selection. Interrupted
runs may have missing task files; grading keeps those checkpoints unresolved.
Run metadata records the model, limits, and browser mode; no Git checkout is required.
Record the code version separately when comparing implementations.
Usage is whatever the current browse API reports, not a complete cost ledger.

The original prompt is passed unchanged. The upstream Google starting-URL
metadata is retained but **not enforced as browser initial state**. Sources
are not injected, discovery permissions are not widened, and policy-blocked
tasks remain in the denominator. This is a Lexoid-native adaptation, not the
official OSWorld runner.

## Grade saved runs

```bash
export ANTHROPIC_API_KEY=...
python -m evaluate.odysseys_judge grade \
  --runs evaluate/runs/baseline-01 \
  --output evaluate/runs/baseline-01/grades-v1.json
```

Override the default judge with `--model`. Lexoid resolves the provider from the
model name and uses its existing native client and credential configuration.
Claude uses Anthropic directly with `ANTHROPIC_API_KEY`; no gateway is required.
Request timeouts and retries follow the shared provider implementation rather
than evaluator-specific settings.

**Grading transmits saved browser content to the selected provider.**
Only use public benchmark sessions and a provider
you authorize. No live execution or paid judge calls happen during selection
or offline tests. Judge credentials are not written to reports.

Each checkpoint includes its original requirement and verification, a verdict
(`pass`, `fail`, or `needs_review`), reasoning, and evidence references.
The judge is instructed to require every part of a checkpoint and to flag
visual appearance, video playback, and retained-tab state for manual review
when independent evidence is unavailable. Returned tab metadata is not final
state verification. Judge classification itself is fallible: review its
decisions, especially any pass involving visual/state requirements.

Missing runs, insufficient evidence, oversized inputs, and judge failures are
not passes. Inputs above `--max-evidence-chars` (default 200,000) are marked
for review rather than silently truncated. Judge failures are logged, saved,
and produce a nonzero exit. Execution errors can still have partial evidence;
the judge may assess supported checkpoints, but unsupported ones need review.

Reports include grading coverage, checkpoint counts, and **lower/upper bounds**
for task-macro rubric average and perfect rate. Unresolved checkpoints count
as zero for the lower bound and one for the upper bound. These are bounds on
the provisional judgments, not statistical confidence intervals. No reviewed-only
average hides unresolved tasks. Regrade without rebrowsing by choosing a new
output file. Record any manual adjudication separately; this version does not
implement a review UI or merge manual overrides.

These are **provisional text-only results**, not official Odysseys scores.
No screenshots, independent terminal-state inspection, or official trajectory
efficiency metric are implemented yet. Keep models, limits, browser setup,
task selection, and judge configuration fixed for pre/post-vision comparisons.

## Offline tests

```bash
python -m pytest evaluate/tests -v
```

`test_end_to_end` is a real, opt-in pipeline smoke test. It runs the kitchen
task through Lexoid browse and the configured judge; it does not mock either
model client. It is skipped in the regular test suite. To run it:

```bash
RUN_ODYSSEYS_LIVE_SMOKE=1 \
  .venv/bin/python -m pytest evaluate/tests/test_odysseys.py::test_end_to_end -v -s
```

By default, browsing uses `gpt-5.6-sol` and grading uses `claude-opus-5-5`.
Set `ODYSSEYS_SMOKE_BROWSER_MODEL` or `ODYSSEYS_SMOKE_JUDGE_MODEL` to override
them, and configure the corresponding provider API keys. The saved browser run
and grades remain under `evaluate/runs/smoke-<timestamp>`; set
`ODYSSEYS_SMOKE_OUTPUT` to choose another new output directory. This exercises
live websites and sends captured page content to the judge provider, so it may
take several minutes and incur model costs. The test checks that browse returns
a result and all rubrics are graded without judge errors; it does not require
the benchmark task itself to pass.

Keep the original dataset at `evaluate/data/odysseys.json` (ignored by Git).
To obtain the pinned original:

```bash
mkdir -p evaluate/data
curl -fL https://raw.githubusercontent.com/ljang0/Odysseys/837814633ef948479abb3d142458f0acdb73fa65/data/odysseys.json \
  -o evaluate/data/odysseys.json
```

See the upstream [MIT license](https://github.com/ljang0/Odysseys/blob/main/LICENSE)
and [citation](https://github.com/ljang0/Odysseys#citation).
