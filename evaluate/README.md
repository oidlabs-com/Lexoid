# Browser evaluation

Run browser tasks from Odysseys and grade saved results.
Run commands from the Lexoid repository root with its Python environment.
Browsing requires `lexoid[browse]` and provider API credentials.
Grading defaults to `claude-opus-5-5`.

## Get the dataset

Download the dataset used by the examples:

```bash
mkdir -p evaluate/data
curl -fL https://github.com/ljang0/Odysseys/blob/main/data/odysseys.json \
  -o evaluate/data/odysseys.json
```

See the upstream [MIT license](https://github.com/ljang0/Odysseys/blob/main/LICENSE)
and [citation](https://github.com/ljang0/Odysseys#citation).

## Select

```bash
python -m evaluate.odysseys_judge select
```

Preview Easy tasks in `Ecommerce & Shopping` or `Law and Government`.
Selection does not run a browser or make model calls.

Choose different tasks or a local dataset:

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
`--all-categories` filters as `select`.

Use `--headful` for an owned visible browser, or `--cdp-url` with a dedicated
evaluation browser. Do not attach a personal browsing session. Defaults are
100 task actions, 20 actions per navigator invocation, 20 captured pages, and
a 600-second task deadline. Configure them with `--max-steps`,
`--max-steps-per-run`, `--max-pages`, and `--deadline`.

Use a new output directory for each run. Results and execution errors are
saved there for grading. Live browser runs may take several minutes per task
and incur model costs.

## Grade saved runs

```bash
export ANTHROPIC_API_KEY=...
python -m evaluate.odysseys_judge grade \
  --runs evaluate/runs/baseline-01 \
  --output evaluate/runs/baseline-01/grades-v1.json
```

Override the default judge with `--model` and configure the corresponding
provider API key. The default judge requires `ANTHROPIC_API_KEY`.

**Grading transmits saved browser content to the selected provider.**
Only use public benchmark sessions and a provider you authorize. Grading
incurs model costs.

Each rubric includes a verdict
(`pass`, `fail`, or `needs_review`), reasoning, and evidence references.
Review judge decisions, especially passes involving visual or browser-state
requirements.

Missing runs, insufficient evidence, oversized inputs, and judge failures are
not passes. To inspect the evidence used for a verdict, see
`<report>-inputs/<task_id>.json` next to the report. Inputs above
`--max-evidence-chars` (default 200,000) are marked for review.
Judge failures are saved and produce a nonzero exit.

Reports include grading coverage and **lower/upper bounds**
for rubric average and perfect rate. Unresolved rubrics count
as zero for the lower bound and one for the upper bound. These are bounds on
the provisional judgments, not statistical confidence intervals.
Regrade without rebrowsing by choosing a new output file.

These are **provisional text-only results**, not official Odysseys scores.
Keep models, limits, browser setup, task selection, and judge configuration
fixed when comparing runs.
