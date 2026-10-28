import argparse
import asyncio
import hashlib
import json
import os
import time
import types
from pathlib import Path

import pytest
from evaluate import odysseys_judge
from evaluate.odysseys_judge import (
    aggregate,
    execute_task,
    grade,
    load_selection,
    run,
    select_tasks,
    selection_digest,
    validate_judgment,
    validate_tasks,
    write_json,
)

KITCHEN_TASK = (
    "I’m setting up a new kitchen and want one of the first things I make "
    "to be roasted Brussels sprouts, so could you start on Google and find "
    "me a recipe that clearly uses both Parmesan and balsamic vinegar, "
    "then open the actual recipe page and note the title, oven temperature, "
    "and cook time because I want to make sure the cookware I buy fits "
    "that kind of roasting setup. Once you’ve got that recipe open, head "
    "to Le Creuset and look for a light green Dutch oven, and specifically "
    "check whether the 5.5 qt size is offered in that color so I can see "
    "if it would work for recipes in that range; please open the product "
    "page itself and leave it open so I can look at the color and size "
    "options on the page. While you’re at it, I’m also sorting out kitchen "
    "appliances before I start cooking, so go to YouTube and find a "
    "practical video about whether a dishwasher installation needs an air "
    "gap, open the video page, start playing it, and tell me the main "
    "decision points like when an air gap is required, when a high loop "
    "is used instead, and why the air gap exists in the first place. "
    "Please keep the recipe tab, the Le Creuset product tab, and the "
    "YouTube video tab open in separate tabs so I can compare everything "
    "visually afterward."
)

KITCHEN_RUBRICS = {
    "R1": {
        "requirement": "A roasted Brussels sprouts recipe was found and the actual recipe page shows both Parmesan and balsamic vinegar, along with the recipe title, oven temperature, and cook time.",
        "verification": "Grader can confirm the open recipe page contains the recipe title and visible recipe details, and the ingredients or recipe text visibly includes Parmesan and balsamic vinegar.",
    },
    "R2": {
        "requirement": "A light green Le Creuset Dutch oven product page was opened and the agent correctly confirmed whether the 5.5 qt size is available in that color, including product name and color.",
        "verification": "Grader can inspect the open Le Creuset product page and see the product name, the selected or referenced light green color, and visible size options or product details indicating whether 5.5 qt is available.",
    },
    "R3": {
        "requirement": "A relevant YouTube video about dishwasher air gaps was opened and played, and the summary captures when an air gap is required, the high loop alternative, and why an air gap is used.",
        "verification": "Grader can confirm the YouTube video page is open with playback started and that the reported summary matches the topic and covers requirement conditions, alternatives, and purpose.",
    },
    "R4": {
        "requirement": "The browser state preserves visual proof by keeping the recipe page, Le Creuset product page, and YouTube video page open in separate tabs.",
        "verification": "Grader can inspect the browser tab bar and confirm all three relevant pages remain open for side-by-side review.",
    },
}


def task(number=1, categories=None, level="easy", rubric_count=2):
    return {
        "task_id": f"{number:040x}",
        "confirmed_task": "Visit the original sites and report findings.",
        "website": "https://www.google.com",
        "level": level,
        "categories": categories or ["Law and Government > Government"],
        "rubrics": {
            f"R{i}": {"requirement": "Find a fact.", "verification": "Check the page."}
            for i in range(rubric_count)
        },
    }


def make_grade_args(runs, output, max_evidence_chars=200_000):
    return argparse.Namespace(
        runs=runs, output=output, model="judge", max_evidence_chars=max_evidence_chars
    )


def make_browse_args(deadline: float = 1):
    return argparse.Namespace(
        model="model", cdp_url=None, headful=False, deadline=deadline
    )


def model_dump(value):
    return types.SimpleNamespace(model_dump=lambda **kwargs: value)


def write_run(root, tasks, records):
    selection = {"tasks": tasks}
    write_json(root / "selection.json", selection)
    write_json(root / "run.json", {"selection_sha256": selection_digest(selection)})
    for record in records:
        write_json(root / "tasks" / f"{record['task_id']}.json", record)


def test_original_dataset_filtered_without_creating_subset_file(tmp_path):
    source = tmp_path / "odysseys.json"
    write_json(source, [task(), task(2, level="hard")])
    args = argparse.Namespace(
        input=source, category=None, all_categories=False, level="easy"
    )

    selected = load_selection(args)

    assert selected["tasks"] == [task()]
    assert selected["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert list(tmp_path.iterdir()) == [source]
    args.level = "all"
    args.all_categories = True
    assert len(load_selection(args)["tasks"]) == 2


def test_selects_category_union_once_and_preserves_whole_task():
    both = task(
        categories=[
            "Law and Government > Government",
            "Ecommerce & Shopping > Coupons and Rebates",
            "Other > Example",
        ]
    )
    tasks = [both, task(2, level="hard"), task(3, categories=["Other"])]

    selected = select_tasks(
        tasks, ["Law and Government", "Ecommerce & Shopping"], "easy"
    )

    assert selected == [both]
    assert len(selected[0]["rubrics"]) == 2


def test_category_prefix_has_boundary():
    tasks = [task(categories=["Law and Governmental"])]
    assert select_tasks(tasks, ["Law and Government"], "easy") == []


def test_upstream_untagged_tasks_are_not_category_matches():
    untagged = task(2, level="hard")
    del untagged["categories"]
    assert select_tasks([task(), untagged], ["Law and Government"], "easy") == [task()]


def test_duplicate_and_unsafe_ids_rejected():
    with pytest.raises(ValueError):
        validate_tasks([task(), task()])
    unsafe = {**task(), "task_id": "../escape"}
    with pytest.raises(ValueError):
        validate_tasks([unsafe])


def test_manifest_digest_detects_changes():
    assert selection_digest({"tasks": [task()]}) != selection_digest(
        {"tasks": [task(2)]}
    )


def test_judge_validation():
    valid = {"verdict": "needs_review", "reason": "Need screenshot", "evidence": []}
    assert validate_judgment(valid)["verdict"] == "needs_review"


@pytest.mark.parametrize(
    "judgment",
    [
        {"verdict": "pass", "reason": "OK", "evidence": []},
        {"verdict": "maybe", "reason": "OK", "evidence": ["artifact-1"]},
        {"verdict": "pass", "reason": "", "evidence": ["artifact-1"]},
    ],
)
def test_invalid_judgments_rejected(judgment):
    with pytest.raises(ValueError):
        validate_judgment(judgment)


def test_missing_tasks_stay_in_macro_denominator():
    tasks = [task(rubric_count=2), task(2, rubric_count=4)]
    grades = {
        tasks[0]["task_id"]: {
            "R0": {"verdict": "pass"},
            "R1": {"verdict": "fail"},
        }
    }

    summary = aggregate(tasks, grades)

    assert summary["rubrics"] == 6
    assert summary["needs_review"] == 4
    assert summary["grading_coverage"] == pytest.approx(2 / 6)
    assert summary["rubric_average_lower_bound"] == 0.25
    assert summary["rubric_average_upper_bound"] == 0.75
    assert summary["perfect_rate_lower_bound"] == 0
    assert summary["perfect_rate_upper_bound"] == 0.5


def test_judge_errors_not_passes():
    value = task()
    grades = {value["task_id"]: {"R0": {"verdict": "needs_review", "error": "failed"}}}

    summary = aggregate([value], grades)

    assert summary["grading_errors"] == 1
    assert summary["pass"] == 0
    assert summary["needs_review"] == 2


def test_judge_errors_and_oversized_evidence_are_persisted(tmp_path, monkeypatch):
    def failing_judge(prompt):
        raise ValueError("Invalid judge response")

    monkeypatch.setattr(odysseys_judge, "make_judge", lambda model: failing_judge)
    write_run(
        tmp_path,
        [task()],
        [{"task_id": task()["task_id"], "result": {"answer": "A fact"}}],
    )

    failed = make_grade_args(tmp_path, tmp_path / "failed-grades.json")
    assert grade(failed)
    report = json.loads(failed.output.read_text())
    assert report["summary"]["grading_errors"] == 2
    assert report["summary"]["needs_review"] == 2

    oversized = make_grade_args(
        tmp_path, tmp_path / "oversized-grades.json", max_evidence_chars=1
    )
    assert not grade(oversized)
    report = json.loads(oversized.output.read_text())
    assert report["summary"]["grading_errors"] == 0
    assert report["summary"]["needs_review"] == 2
    assert (
        "not silently truncated" in report["grades"][task()["task_id"]]["R0"]["reason"]
    )


def test_saved_run_grading_and_missing_run_denominator(tmp_path, monkeypatch):
    prompts = []

    def judge(prompt):
        prompts.append(prompt)
        return json.dumps(
            {
                "verdict": "needs_review",
                "reason": "Independent terminal tab state is not captured",
                "evidence": [],
            }
        )

    monkeypatch.setattr(odysseys_judge, "make_judge", lambda model: judge)
    record = {
        "task_id": task()["task_id"],
        "status": "returned",
        "result": {"answer": "A fact"},
    }
    write_run(tmp_path, [task(), task(2)], [record])
    args = make_grade_args(tmp_path, tmp_path / "grades.json")

    assert not grade(args)
    with pytest.raises(ValueError):
        grade(args)

    report = json.loads(args.output.read_text())
    assert len(prompts) == 2
    assert report["summary"]["rubrics"] == 4
    assert report["summary"]["needs_review"] == 4
    assert "rubric" in json.loads(prompts[0])


@pytest.mark.asyncio
async def test_preserves_prompt_and_serializes_result():
    captured = {}

    async def browse(query, **kwargs):
        captured.update(query=query, **kwargs)
        return model_dump({"answer": "A fact", "task_results": []})

    record = await execute_task(task(), make_browse_args(), browse, object())

    assert captured["query"] == task()["confirmed_task"]
    assert record["status"] == "returned"
    assert record["result"]["answer"] == "A fact"
    assert record["elapsed_seconds"] >= 0


@pytest.mark.asyncio
async def test_failure_retains_emitted_events():
    async def browse(query, **kwargs):
        kwargs["event_listener"](model_dump({"event": "action"}))
        raise ValueError("blocked")

    record = await execute_task(task(), make_browse_args(), browse, None)

    assert record["status"] == "error"
    assert record["error"]["type"] == "ValueError"
    assert record["events"] == [{"event": "action"}]


@pytest.mark.asyncio
async def test_deadline_is_explicit_failure():
    async def browse(query, **kwargs):
        await asyncio.sleep(10)

    record = await execute_task(task(), make_browse_args(deadline=0.001), browse, None)

    assert record["error"]["type"] == "TimeoutError"


@pytest.mark.live
@pytest.mark.asyncio
async def test_end_to_end(tmp_path):
    if os.getenv("RUN_ODYSSEYS_LIVE_SMOKE") != "1":
        pytest.skip(
            "Set RUN_ODYSSEYS_LIVE_SMOKE=1 to run the live browser-and-judge smoke test"
        )

    example = {
        **task(categories=["Ecommerce & Shopping > Ecommerce and Shopping - Other"]),
        "confirmed_task": KITCHEN_TASK,
        "rubrics": KITCHEN_RUBRICS,
    }
    source = tmp_path / "odysseys.json"
    write_json(source, [example])
    output = Path(
        os.getenv(
            "ODYSSEYS_SMOKE_OUTPUT",
            f"evaluate/runs/smoke-{time.time_ns()}",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    run_args = argparse.Namespace(
        input=source,
        category=None,
        all_categories=False,
        level="easy",
        output=output,
        model=os.getenv("ODYSSEYS_SMOKE_BROWSER_MODEL", "gpt-5.6-sol"),
        cdp_url=None,
        headful=False,
        deadline=1000,
        max_steps=100,
        max_steps_per_run=20,
        max_pages=20,
    )
    args = make_grade_args(
        run_args.output,
        output / "grades-live.json",
    )
    args.model = os.getenv("ODYSSEYS_SMOKE_JUDGE_MODEL", "claude-opus-5-5")

    assert not await run(run_args)
    run_record = json.loads(
        (output / "tasks" / f"{example['task_id']}.json").read_text()
    )
    assert run_record["status"] == "returned", run_record["error"]
    assert run_record["result"] is not None
    assert not grade(args)

    report = json.loads(args.output.read_text())
    task_grades = report["grades"][example["task_id"]]
    assert set(task_grades) == set(KITCHEN_RUBRICS)
    assert all(
        grade["verdict"] in {"pass", "fail", "needs_review"}
        for grade in task_grades.values()
    )
    assert report["summary"]["grading_errors"] == 0
