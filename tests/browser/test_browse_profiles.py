"""Tests for site profiles, navigator outcome gating, and orchestrator branching."""

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from lexoid.core.browse import agents as browse_agents
from lexoid.core.browse.profiles import SiteProfile, find_profile
from lexoid.core.browse.schemas import (
    BrowserAction,
    BrowserActionResult,
    BrowserActionTrace,
    BrowserSnapshot,
    BrowseErrorCode,
    BrowseLimits,
    BrowseTask,
    BrowseTerminalState,
    BrowseUsage,
    ElementRef,
    NavigationOutcome,
    OpenTab,
)
from lexoid.core.browse.tools import BrowserToolset


def test_site_profile_matches_host_and_task_type():
    profile = SiteProfile(
        profile_id="example-search",
        hosts=["example.test"],
        task_types=["search"],
        guidance=["Prefer a field-scoped search builder when one exists."],
    )

    matched = find_profile("https://records.example.test/search", "search", [profile])

    assert matched is profile
    assert matched is not None
    assert matched.supports_export is False
    assert find_profile("https://other.test/search", "search", [profile]) is None
    assert find_profile("https://example.test/x", "capture", [profile]) is None


def test_no_site_is_special_cased_by_default():
    assert find_profile("https://tmsearch.uspto.gov/", "search") is None
    assert find_profile("https://example.test/search", "search") is None


class _OutcomeSession:
    """Session fake exposing only the text used to verify a reported outcome."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def text_content(self, tab_id: str) -> str:
        return self.text

    async def list_tabs(self) -> list[OpenTab]:
        from lexoid.core.browse.schemas import OpenTab

        return [OpenTab(tab_id="tab-1", target_id="t1", url="https://example.test/")]

    async def tab(self, tab_id: str) -> OpenTab:
        from lexoid.core.browse.schemas import OpenTab

        return OpenTab(tab_id=tab_id, target_id="t1", url="https://example.test/")


def _toolset(page_text: str) -> BrowserToolset:
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )

    async def emit(_trace) -> None:
        return None

    return BrowserToolset(cast(Any, _OutcomeSession(page_text)), task, "tab-1", emit)


@pytest.mark.asyncio
async def test_reported_outcome_requires_visible_evidence():
    toolset = _toolset("Showing 1 - 10 of 42 results")

    rejected = json.loads(
        await toolset.report_outcome("results_ready", "Showing 900 results")
    )

    assert rejected["success"] is False
    assert toolset.outcome is NavigationOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_reported_outcome_accepts_quoted_page_text():
    toolset = _toolset("Showing 1 - 10 of 42 results")

    accepted = json.loads(
        await toolset.report_outcome("results_ready", "1 - 10 of 42 results")
    )

    assert accepted["success"] is True
    assert toolset.outcome is NavigationOutcome.RESULTS_READY


@pytest.mark.asyncio
async def test_navigator_run_does_not_reuse_prior_outcome(monkeypatch):
    agent_runs = 0

    class _Agent:
        def __init__(self, *args, **kwargs):
            self.tools = kwargs["tools"]

        async def run(self, _prompt):
            nonlocal agent_runs
            agent_runs += 1
            if agent_runs == 1:
                report_outcome = next(
                    tool for tool in self.tools if tool.__name__ == "report_outcome"
                )
                await report_outcome("results_ready", "Showing 1 - 10 of 42 results")
            return SimpleNamespace(text="navigator finished")

    monkeypatch.setattr(browse_agents, "Agent", _Agent)
    monkeypatch.setattr(
        browse_agents, "browse_usage_from_response", lambda _response: BrowseUsage()
    )

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
        limits=BrowseLimits(max_steps=5),
    )

    async def emit(_trace):
        return None

    toolset = BrowserToolset(
        cast(Any, _OutcomeSession("Showing 1 - 10 of 42 results")),
        task,
        "tab-1",
        emit,
    )
    toolset.action_count = 2
    toolset.successful_action_count = 1

    first_outcome, _ = await browse_agents.navigate_with_tools(
        object(), toolset, task, "{}"
    )
    assert first_outcome is NavigationOutcome.RESULTS_READY
    assert toolset.outcome_evidence == "Showing 1 - 10 of 42 results"

    toolset.last_error_code = BrowseErrorCode.POLICY_DENIED
    second_outcome, _ = await browse_agents.navigate_with_tools(
        object(), toolset, task, "{}", objective="inspect another result"
    )

    assert second_outcome is NavigationOutcome.UNKNOWN
    assert toolset.outcome is NavigationOutcome.UNKNOWN
    assert toolset.outcome_evidence == ""
    assert toolset.last_error_code is None
    assert toolset.action_count == 2
    assert toolset.successful_action_count == 1


@pytest.mark.asyncio
async def test_begin_run_preserves_quarantine_state():
    toolset = _toolset("some text")
    toolset._quarantined = True
    toolset.outcome = NavigationOutcome.BLOCKED
    toolset.outcome_evidence = "tab unavailable"
    toolset.last_error_code = BrowseErrorCode.TAB_GONE

    toolset.begin_run()

    assert toolset.outcome is NavigationOutcome.BLOCKED
    assert toolset.outcome_evidence == "tab unavailable"
    assert toolset.last_error_code is BrowseErrorCode.TAB_GONE


@pytest.mark.asyncio
async def test_type_action_value_is_redacted_from_trace_and_tool_result():
    class _TypingSession(_OutcomeSession):
        def __init__(self) -> None:
            super().__init__("some text")
            self.executed_values: list[str | None] = []
            self.snapshot_value: BrowserSnapshot | None = None

        async def execute(self, action: BrowserAction) -> BrowserActionResult:
            self.executed_values.append(action.text)
            return BrowserActionResult(success=True, outcome="action executed")

        async def snapshot(self, _tab_id: str) -> BrowserSnapshot:
            assert self.snapshot_value is not None
            return self.snapshot_value

    traces: list[BrowserActionTrace] = []
    session = _TypingSession()

    async def emit(trace: BrowserActionTrace) -> None:
        traces.append(trace)

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )
    toolset = BrowserToolset(cast(Any, session), task, "tab-1", emit)
    snapshot = BrowserSnapshot(
        snapshot_id="snapshot-1",
        tab_id="tab-1",
        page_revision=0,
        url="https://example.test/",
        viewport_width=1280,
        viewport_height=720,
        scroll_x=0,
        scroll_y=0,
        elements=[
            ElementRef(
                ref="e0",
                snapshot_id="snapshot-1",
                tab_id="tab-1",
                frame_id="main",
                node_id="0:0",
                role="textbox",
                name="Password",
                input_type="password",
            )
        ],
        content_hash="snapshot-hash",
    )
    toolset._snapshot = snapshot
    session.snapshot_value = snapshot

    tool_result = await toolset._run(
        BrowserAction(kind="type", ref="e0", text="secret-value")
    )

    action_trace = next(trace for trace in traces if trace.event == "action")
    assert session.executed_values == ["secret-value"]
    assert action_trace.action is not None
    assert action_trace.action.text == "[redacted]"
    assert "secret-value" not in action_trace.model_dump_json()
    assert json.loads(tool_result)["action"]["text"] == "[redacted]"
    assert "secret-value" not in tool_result


@pytest.mark.asyncio
async def test_read_text_returns_bounded_rendered_text():
    emitted = []

    async def emit(trace):
        emitted.append(trace)

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )
    long_text = "Case #101: Pending approval.\n" * 200
    toolset = BrowserToolset(cast(Any, _OutcomeSession(long_text)), task, "tab-1", emit)

    raw = await toolset.read_text(max_chars=500)
    data = json.loads(raw)

    assert len(data["text"]) == 500
    assert data["total_chars"] == len(long_text)
    assert data["truncated"] is True
    assert toolset.action_count == 0
    assert toolset.successful_action_count == 0
    assert emitted[-1].event == "observation"
    assert emitted[-1].metadata["action"] == "read_text"


@pytest.mark.asyncio
async def test_read_text_available_in_toolset_functions():
    toolset = _toolset("some text")
    tool_names = [func.__name__ for func in toolset.functions()]
    assert "read_text" in tool_names
    assert "observe" in tool_names
    assert "list_tabs" in tool_names
    assert "switch_tab" in tool_names


@pytest.mark.asyncio
async def test_scroll_tool_supports_optional_ref():
    emitted = []

    async def emit(trace):
        emitted.append(trace)

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )

    class _ScrollSession:
        async def snapshot(self, tab_id: str):
            from lexoid.core.browse.schemas import BrowserSnapshot

            return BrowserSnapshot(
                snapshot_id="s1",
                tab_id=tab_id,
                page_revision=0,
                url="https://example.test/",
                viewport_width=1280,
                viewport_height=720,
                scroll_x=0,
                scroll_y=0,
                content_hash="h1",
            )

        async def execute(self, action):
            from lexoid.core.browse.schemas import BrowserActionResult

            return BrowserActionResult(success=True, outcome="ok")

        async def tab(self, tab_id: str):
            return OpenTab(tab_id=tab_id, target_id="t1", url="https://example.test/")

    toolset = BrowserToolset(cast(Any, _ScrollSession()), task, "tab-1", emit)
    await toolset.scroll(direction="down", ref="e1")
    assert toolset.action_count == 1
    assert toolset.successful_action_count == 1
    action_trace = [e for e in emitted if e.event == "action"][-1]
    decision_trace = [e for e in emitted if e.event == "decision"][-1]
    assert decision_trace.metadata["role"] == "navigator"
    assert decision_trace.metadata["state_ref"]["snapshot_id"] == "s1"
    assert decision_trace.metadata["options"]["operations"]
    assert decision_trace.metadata["options"]["element_count"] == 0
    assert decision_trace.metadata["options"]["selected_ref"] == "e1"
    assert "elements" not in decision_trace.metadata["options"]
    assert decision_trace.metadata["selected"] == {"kind": "scroll", "ref": "e1"}
    assert action_trace.action is not None
    assert action_trace.action.kind == "scroll"
    assert action_trace.action.ref == "e1"
    assert action_trace.action.text == "down"


@pytest.mark.asyncio
async def test_action_is_denied_when_destination_cannot_be_verified():
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="subject",
        allowed_domains=["example.test"],
    )

    class _UninspectableSession:
        async def snapshot(self, tab_id: str):
            from lexoid.core.browse.schemas import BrowserSnapshot

            return BrowserSnapshot(
                snapshot_id="s1",
                tab_id=tab_id,
                page_revision=0,
                url="https://example.test/",
                viewport_width=1280,
                viewport_height=720,
                scroll_x=0,
                scroll_y=0,
                content_hash="h1",
            )

        async def execute(self, action):
            from lexoid.core.browse.schemas import BrowserActionResult

            return BrowserActionResult(success=True, outcome="ok")

        async def tab(self, tab_id: str):
            raise RuntimeError("tab metadata unavailable")

    async def emit(_trace):
        return None

    toolset = BrowserToolset(cast(Any, _UninspectableSession()), task, "tab-1", emit)

    result = json.loads(await toolset.scroll(direction="down"))

    assert result["result"]["success"] is False
    assert result["result"]["error_code"] == "policy_denied"
    assert toolset.successful_action_count == 0


@pytest.mark.asyncio
async def test_blocked_navigation_skips_collection(monkeypatch):
    from lexoid.core.browse import orchestrator

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("collection ran despite blocked navigation")

    monkeypatch.setattr(orchestrator, "capture_page", fail_if_called)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

        async def tab(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id,
                target_id="t1",
                url="https://tmsearch.uspto.gov/",
            )

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())
    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _observation()
    )

    async def _observation():
        return "{}"

    async def navigate(*_args, **_kwargs):
        from lexoid.core.browse.schemas import BrowseUsage

        return NavigationOutcome.BLOCKED, BrowseUsage()

    monkeypatch.setattr(orchestrator, "navigate_with_tools", navigate)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    result = await orchestrator.run_task(task, navigator_client=object())

    task_result = result.task_results[0]
    assert task_result.status is BrowseTerminalState.BLOCKED
    assert task_result.navigation_outcome is NavigationOutcome.BLOCKED
    assert task_result.site_profile_id is None
    assert task_result.artifacts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "landing_url",
    ["https://evil.example/", "http://tmsearch.uspto.gov/"],
)
async def test_initial_redirect_outside_https_allowlist_is_blocked(
    monkeypatch, landing_url
):
    from lexoid.core.browse import orchestrator

    class _Session:
        def __init__(self):
            self.closed_tabs = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-1", target_id="t1", url=landing_url)

        async def close_tab(self, tab_id):
            self.closed_tabs.append(tab_id)

    session = _Session()
    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: session)

    async def fail_if_observed(self):
        raise AssertionError("redirected page was observed")

    monkeypatch.setattr(orchestrator.BrowserToolset, "observe", fail_if_observed)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="subject",
        allowed_domains=["tmsearch.uspto.gov"],
    )
    result = await orchestrator.run_task(task)

    assert result.task_results[0].status is BrowseTerminalState.BLOCKED
    assert session.closed_tabs == ["tab-1"]
    assert result.task_results[0].trace[-1].event == "terminal"


@pytest.mark.asyncio
async def test_initial_redirect_preserves_inferred_seed_warning(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import InferredSeed

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-1", target_id="t1", url="https://evil.example/")

        async def close_tab(self, tab_id):
            return None

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    task = BrowseTask(
        inferred_seeds=[
            InferredSeed(
                url="https://weather.gov/",
                source_text="NWS",
                rationale="official forecast",
            )
        ],
        subject="forecast",
        allowed_domains=["weather.gov"],
    )
    result = await orchestrator.run_task(task)

    assert result.task_results[0].status is BrowseTerminalState.BLOCKED
    assert any("inferred, not verified" in w for w in result.warnings)
    assert any("outside the HTTPS task allowlist" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_capture_is_skipped_if_active_tab_navigated_off_domain(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import BrowseUsage

    class _Session:
        def __init__(self):
            self._tab_url = "https://tmsearch.uspto.gov/"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-1", target_id="t1", url=self._tab_url)

        async def tab(self, tab_id):
            return OpenTab(tab_id=tab_id, target_id="t1", url=self._tab_url)

        async def settle(self, tab_id):
            return None

        async def retain_page(self, tab_id):
            return OpenTab(tab_id=tab_id, target_id="t1", url=self._tab_url)

    session = _Session()
    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: session)

    async def observe(self):
        return "{}"

    async def fail_if_captured(*args, **kwargs):
        raise AssertionError("capture_page was called for an off-domain tab")

    async def fake_navigate(client, toolset, task, snapshot, profile, **kwargs):
        # Simulate an off-domain navigation that altered tab destination
        session._tab_url = "https://evil.example/phish"
        return NavigationOutcome.BLOCKED, BrowseUsage()

    monkeypatch.setattr(orchestrator.BrowserToolset, "observe", observe)
    monkeypatch.setattr(orchestrator, "capture_page", fail_if_captured)
    monkeypatch.setattr(orchestrator, "navigate_with_tools", fake_navigate)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="search",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    result = await orchestrator.run_task(task, navigator_client=object())

    assert result.task_results[0].status is BrowseTerminalState.BLOCKED
    assert result.task_results[0].artifacts == []
    assert any(
        "current tab URL is outside the HTTPS task allowlist" in w
        for w in result.warnings
    )


def test_assessor_sufficiency_is_downgraded_when_a_claim_is_rejected():
    from lexoid.core.browse.orchestrator import _validate_assessment
    from lexoid.core.browse.schemas import (
        CandidateAssessment,
        CandidateConstraintEvidence,
        CandidateCriterionEvidence,
        EvidenceAssessment,
        EvidenceClaim,
        TaskConstraints,
        TaskFilter,
    )

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="restaurant property",
        allowed_domains=["example.test"],
        constraints=TaskConstraints(
            filters=[TaskFilter(field="Minimum Size", value="5,000 SF")],
            evaluation_criteria=["likely suited for Korean BBQ"],
        ),
    )
    claims = [
        EvidenceClaim(
            claim_id="claim-1",
            text="Listing is 5,200 SF.",
            quote="5,200 SF",
            artifact_id="artifact-1",
            source_url="https://example.test/listing/1",
        ),
        EvidenceClaim(
            claim_id="claim-2",
            text="Former restaurant use.",
            quote="Former restaurant use",
            artifact_id="artifact-1",
            source_url="https://example.test/listing/1",
        ),
    ]
    assessment = EvidenceAssessment(
        answerability="sufficient",
        candidates=[
            CandidateAssessment(
                label="Listing 1",
                source_url="https://example.test/listing/1",
                hard_constraints=[
                    CandidateConstraintEvidence(
                        field="Minimum Size",
                        status="supported",
                        claim_ids=["claim-1"],
                    )
                ],
                criteria_support=[
                    CandidateCriterionEvidence(
                        criterion="likely suited for Korean BBQ",
                        assessment="supported",
                        claim_ids=["claim-2"],
                    )
                ],
            )
        ],
    )

    checked, validation_warnings = _validate_assessment(
        assessment, task, claims, rejected_claim_count=1
    )

    assert checked.answerability == "partial"
    assert not any("validation" in gap for gap in checked.gaps)
    assert any(
        "failed exact-quote validation" in warning for warning in validation_warnings
    )


def test_assessor_sufficiency_requires_candidate_evidence_for_each_criterion():
    from lexoid.core.browse.orchestrator import _validate_assessment
    from lexoid.core.browse.schemas import (
        CandidateAssessment,
        CandidateConstraintEvidence,
        CandidateCriterionEvidence,
        EvidenceAssessment,
        EvidenceClaim,
        TaskConstraints,
        TaskFilter,
    )

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="restaurant property",
        allowed_domains=["example.test"],
        constraints=TaskConstraints(
            filters=[TaskFilter(field="Minimum Size", value="5,000 SF")],
            evaluation_criteria=["likely suited for Korean BBQ"],
        ),
    )
    claims = [
        EvidenceClaim(
            claim_id="claim-1",
            text="Listing is 5,200 SF.",
            quote="5,200 SF",
            artifact_id="artifact-1",
            source_url="https://example.test/listing/1",
        )
    ]
    assessment = EvidenceAssessment(
        answerability="sufficient",
        candidates=[
            CandidateAssessment(
                label="Listing 1",
                source_url="https://example.test/listing/1",
                hard_constraints=[
                    CandidateConstraintEvidence(
                        field=" minimum   size ",
                        status="supported",
                        claim_ids=["claim-1"],
                    )
                ],
                criteria_support=[
                    CandidateCriterionEvidence(
                        criterion="LIKELY SUITED FOR KOREAN BBQ",
                        assessment="unsupported",
                        claim_ids=[],
                    )
                ],
            )
        ],
    )

    checked, _ = _validate_assessment(assessment, task, claims, rejected_claim_count=0)

    assert checked.answerability == "partial"
    assert checked.next_action == "paginate"
    assert any("Only 0 candidate(s)" in gap for gap in checked.gaps)


def test_requested_candidate_count_ignores_incomplete_extra_candidates():
    from lexoid.core.browse.orchestrator import _validate_assessment
    from lexoid.core.browse.schemas import (
        CandidateAssessment,
        CandidateConstraintEvidence,
        CandidateCriterionEvidence,
        EvidenceAssessment,
        EvidenceClaim,
        TaskConstraints,
        TaskFilter,
    )

    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="restaurant property",
        allowed_domains=["example.test"],
        constraints=TaskConstraints(
            filters=[TaskFilter(field="Minimum Size", value="5,000 SF")],
            evaluation_criteria=["Korean BBQ suitability"],
            max_records=2,
        ),
    )
    claims = [
        EvidenceClaim(
            claim_id=f"claim-{index}",
            text=f"Evidence {index}",
            quote=f"Evidence {index}",
            artifact_id=f"artifact-{index}",
            source_url=f"https://example.test/listing/{index}",
        )
        for index in range(1, 4)
    ]
    candidates = []
    for index in range(1, 4):
        qualifies = index < 3
        candidates.append(
            CandidateAssessment(
                label=f"Listing {index}",
                source_url=f"https://example.test/listing/{index}",
                hard_constraints=[
                    CandidateConstraintEvidence(
                        field="minimum size",
                        status="supported" if qualifies else "missing",
                        claim_ids=[f"claim-{index}"] if qualifies else [],
                    )
                ],
                criteria_support=[
                    CandidateCriterionEvidence(
                        criterion="korean bbq suitability",
                        assessment="supported" if qualifies else "unsupported",
                        claim_ids=[f"claim-{index}"] if qualifies else [],
                    )
                ],
            )
        )
    assessment = EvidenceAssessment(answerability="sufficient", candidates=candidates)

    checked, warnings = _validate_assessment(
        assessment, task, claims, rejected_claim_count=0
    )

    assert checked.answerability == "sufficient"
    assert len(checked.candidates) == 3
    assert warnings == []


def test_synthesis_assessments_require_valid_claim_references():
    from lexoid.core.browse.orchestrator import _validate_synthesis_assessments
    from lexoid.core.browse.schemas import EvidenceClaim, SynthesisAssessment

    claims = [
        EvidenceClaim(
            claim_id="claim-1",
            text="A quoted fact",
            quote="quoted fact",
            artifact_id="artifact-1",
            source_url="https://example.test/",
        )
    ]
    proposals = [
        SynthesisAssessment(
            statement="Assessment with support.", based_on_claim_ids=["claim-1"]
        ),
        SynthesisAssessment(
            statement="Assessment with unknown support.",
            based_on_claim_ids=["claim-unknown"],
        ),
        SynthesisAssessment(statement="Assessment without support."),
    ]

    accepted, rejected = _validate_synthesis_assessments(proposals, claims)

    assert [item.statement for item in accepted] == ["Assessment with support."]
    assert len(rejected) == 2


@pytest.mark.asyncio
async def test_orchestrator_keeps_only_valid_synthesis_assessments(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import (
        BrowseUsage,
        EvidenceAssessment,
        EvidenceClaim,
        PageArtifact,
        SynthesisAssessment,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

        async def tab(self, tab_id):
            return OpenTab(tab_id=tab_id, target_id="t1", url="https://example.test/")

        async def settle(self, tab_id):
            return None

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    async def observe(self):
        return "{}"

    async def capture(*args, **kwargs):
        return PageArtifact(
            artifact_id="artifact-1",
            url="https://example.test/",
            tab_id="tab-1",
            content_hash="hash-1",
            text="Verified listing fact",
        )

    async def assess(*args, **kwargs):
        return (
            EvidenceAssessment(answerability="sufficient"),
            [
                EvidenceClaim(
                    claim_id="claim-1",
                    text="A listing fact.",
                    quote="Verified listing fact",
                    artifact_id="artifact-1",
                    source_url="https://example.test/",
                )
            ],
            BrowseUsage(),
        )

    async def synthesize(*args, **kwargs):
        return (
            "A verified listing fact.",
            ["claim-1"],
            [
                SynthesisAssessment(
                    statement="Likely relevant based on the listing fact.",
                    based_on_claim_ids=["claim-1"],
                ),
                SynthesisAssessment(
                    statement="Unsupported speculation.",
                    based_on_claim_ids=["claim-unknown"],
                ),
            ],
            BrowseUsage(),
        )

    monkeypatch.setattr(orchestrator.BrowserToolset, "observe", observe)
    monkeypatch.setattr(orchestrator, "capture_page", capture)
    monkeypatch.setattr(orchestrator, "assess_page", assess)
    monkeypatch.setattr(orchestrator, "synthesize_answer", synthesize)
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="listing",
        allowed_domains=["example.test"],
        retain_final_page=False,
    )

    result = await orchestrator.run_task(
        task, extractor_client=object(), synthesizer_client=object()
    )

    task_result = result.task_results[0]
    assert [item.statement for item in task_result.assessments] == [
        "Likely relevant based on the listing fact."
    ]
    assert "Unsupported speculation." not in result.answer
    assert any("Dropped unsupported assessment" in item for item in result.warnings)
    assert '"Verified listing fact" - https://example.test/' in result.answer


@pytest.mark.asyncio
async def test_orchestrator_routes_explicit_assessor_client_and_options(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import (
        BrowseUsage,
        EvidenceAssessment,
        EvidenceClaim,
        OpenTab,
        PageArtifact,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

        async def tab(self, tab_id):
            return OpenTab(tab_id=tab_id, target_id="t1", url="https://example.test/")

        async def settle(self, tab_id):
            return None

        async def advance_to_next_result_page(self, tab_id):
            return False

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    async def fake_observe(self):
        return '{"elements": []}'

    async def fake_capture(*args, **kwargs):
        return PageArtifact(
            artifact_id="art-1",
            url="https://example.test/",
            tab_id="tab-1",
            content_hash="hash-1",
            text="Verified text",
        )

    monkeypatch.setattr(orchestrator.BrowserToolset, "observe", fake_observe)
    monkeypatch.setattr(orchestrator, "capture_page", fake_capture)

    seen_client = []
    seen_options = []

    async def fake_assess(
        client, task, artifact, claims, gaps, *, prior_context=None, role_options=None
    ):
        seen_client.append(client)
        seen_options.append(role_options)
        return (
            EvidenceAssessment(
                answerability="sufficient",
                gaps=[],
                next_action="stop",
                next_action_reason="Sufficient",
            ),
            [
                EvidenceClaim(
                    claim_id="claim-1",
                    text="Verified text",
                    quote="Verified text",
                    artifact_id="art-1",
                    source_url="https://example.test/",
                )
            ],
            BrowseUsage(),
        )

    monkeypatch.setattr(orchestrator, "assess_page", fake_assess)

    custom_assessor = object()
    custom_options = {"reasoning": {"effort": "high"}}
    fallback_extractor = object()
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="listing",
        allowed_domains=["example.test"],
        retain_final_page=False,
    )

    await orchestrator.run_task(
        task,
        assessor_client=custom_assessor,
        assessor_options=custom_options,
        extractor_client=fallback_extractor,
        extractor_options={"reasoning": {"effort": "low"}},
    )

    assert seen_client == [custom_assessor]
    assert seen_options == [custom_options]


@pytest.mark.asyncio
async def test_orchestrator_assessor_falls_back_to_extractor(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import (
        BrowseUsage,
        EvidenceAssessment,
        EvidenceClaim,
        OpenTab,
        PageArtifact,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

        async def tab(self, tab_id):
            return OpenTab(tab_id=tab_id, target_id="t1", url="https://example.test/")

        async def settle(self, tab_id):
            return None

        async def advance_to_next_result_page(self, tab_id):
            return False

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    async def fake_observe(self):
        return '{"elements": []}'

    async def fake_capture(*args, **kwargs):
        return PageArtifact(
            artifact_id="art-1",
            url="https://example.test/",
            tab_id="tab-1",
            content_hash="hash-1",
            text="Verified text",
        )

    monkeypatch.setattr(orchestrator.BrowserToolset, "observe", fake_observe)
    monkeypatch.setattr(orchestrator, "capture_page", fake_capture)

    seen_client = []
    seen_options = []

    async def fake_assess(
        client, task, artifact, claims, gaps, *, prior_context=None, role_options=None
    ):
        seen_client.append(client)
        seen_options.append(role_options)
        return (
            EvidenceAssessment(
                answerability="sufficient",
                gaps=[],
                next_action="stop",
                next_action_reason="Sufficient",
            ),
            [
                EvidenceClaim(
                    claim_id="claim-1",
                    text="Verified text",
                    quote="Verified text",
                    artifact_id="art-1",
                    source_url="https://example.test/",
                )
            ],
            BrowseUsage(),
        )

    monkeypatch.setattr(orchestrator, "assess_page", fake_assess)

    extractor_client = object()
    extractor_options = {"reasoning": {"effort": "low"}}
    task = BrowseTask(
        seed_urls=["https://example.test/"],
        subject="listing",
        allowed_domains=["example.test"],
        retain_final_page=False,
    )

    await orchestrator.run_task(
        task,
        extractor_client=extractor_client,
        extractor_options=extractor_options,
    )

    assert seen_client == [extractor_client]
    assert seen_options == [extractor_options]


@pytest.mark.asyncio
async def test_allowed_subdomain_landing_is_observed(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import PageArtifact

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(
                tab_id="tab-1", target_id="t1", url="https://api.tmsearch.uspto.gov/"
            )

        async def tab(self, tab_id):
            return OpenTab(
                tab_id=tab_id, target_id="t1", url="https://api.tmsearch.uspto.gov/"
            )

        async def settle(self, tab_id):
            return None

        async def advance_to_next_result_page(self, tab_id):
            return False

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())
    observed = []

    async def observe(self):
        observed.append(True)
        return "{}"

    async def capture(*args, **kwargs):
        return PageArtifact(
            artifact_id="artifact-1",
            url="https://api.tmsearch.uspto.gov/",
            tab_id="tab-1",
            content_hash="hash",
            text="page",
        )

    monkeypatch.setattr(orchestrator.BrowserToolset, "observe", observe)
    monkeypatch.setattr(orchestrator, "capture_page", capture)
    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="subject",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    await orchestrator.run_task(task)

    assert observed == [True]


@pytest.mark.asyncio
async def test_investigate_objective_reruns_navigator_and_continues(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import BrowseUsage, EvidenceAssessment, PageArtifact

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(tab_id="tab-1", target_id="t1", url=url)

        async def tab(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id,
                target_id="t1",
                url="https://tmsearch.uspto.gov/",
            )

        async def settle(self, tab_id):
            return None

        async def retain_page(self, tab_id):
            from lexoid.core.browse.schemas import OpenTab

            return OpenTab(
                tab_id=tab_id, target_id="t1", url="https://tmsearch.uspto.gov/"
            )

        async def advance_to_next_result_page(self, tab_id):
            return False

        async def list_tabs(self):
            return [await self.tab("tab-1")]

    monkeypatch.setattr(orchestrator, "GhostBrowserSession", lambda cfg: _Session())

    async def _observation():
        return "{}"

    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _observation()
    )

    navigate_calls: list[tuple[str | None, list[str] | None, str | None]] = []

    async def navigate(
        client,
        toolset,
        task,
        observation,
        profile=None,
        objective=None,
        prior_attempts=None,
        gaps=None,
        reason=None,
        **kwargs,
    ):
        navigate_calls.append((objective, gaps, reason))
        return NavigationOutcome.RESULTS_READY, BrowseUsage()

    monkeypatch.setattr(orchestrator, "navigate_with_tools", navigate)

    async def fake_capture_page(session, tab_id, index, max_chars):
        return PageArtifact(
            artifact_id=f"artifact-{index}",
            url="https://tmsearch.uspto.gov/",
            tab_id=tab_id,
            content_hash=f"hash-{index}",
            text=f"page {index} text",
        )

    monkeypatch.setattr(orchestrator, "capture_page", fake_capture_page)

    assess_calls: list[str] = []

    async def fake_assess_page(
        client, task, artifact, prior_claims, prior_gaps, **kwargs
    ):
        assess_calls.append(artifact.artifact_id)
        if len(assess_calls) == 1:
            assessment = EvidenceAssessment(
                answerability="partial",
                gaps=["record detail unverified"],
                next_action="investigate",
                next_action_reason="need to open the first record",
                objective="open the first record and confirm the attorney field",
            )
        else:
            assessment = EvidenceAssessment(answerability="sufficient")
        return assessment, [], BrowseUsage()

    monkeypatch.setattr(orchestrator, "assess_page", fake_assess_page)

    task = BrowseTask(
        seed_urls=["https://tmsearch.uspto.gov/"],
        subject="Arash Samadani",
        allowed_domains=["tmsearch.uspto.gov"],
    )

    result = await orchestrator.run_task(
        task, navigator_client=object(), extractor_client=object()
    )

    task_result = result.task_results[0]
    assert assess_calls == ["artifact-1", "artifact-2"]
    assert navigate_calls == [
        (None, None, None),
        (
            "open the first record and confirm the attorney field",
            ["record detail unverified"],
            "need to open the first record",
        ),
    ]
    assert task_result.coverage.stop_reason == "sufficient"
    assert task_result.status is BrowseTerminalState.COMPLETED


@pytest.mark.asyncio
async def test_orchestrator_captures_and_paginates_on_switched_active_tab(monkeypatch):
    from lexoid.core.browse import orchestrator
    from lexoid.core.browse.schemas import (
        BrowseUsage,
        EvidenceAssessment,
        OpenTab,
        PageArtifact,
    )

    captured_tab_ids: list[str] = []
    advanced_tab_ids: list[str] = []
    settled_tab_ids: list[str] = []
    retained_tab_ids: list[str] = []

    class _MultiTabSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def open_page(self, url):
            return OpenTab(tab_id="tab-seed", target_id="t1", url=url)

        async def tab(self, tab_id):
            return OpenTab(
                tab_id=tab_id, target_id=tab_id, url=f"https://example.com/{tab_id}"
            )

        async def list_tabs(self):
            return [
                OpenTab(
                    tab_id="tab-seed", target_id="t1", url="https://example.com/search"
                ),
                OpenTab(
                    tab_id="tab-listing",
                    target_id="t2",
                    url="https://example.com/listing/1",
                ),
            ]

        async def settle(self, tab_id):
            settled_tab_ids.append(tab_id)

        async def retain_page(self, tab_id):
            retained_tab_ids.append(tab_id)
            return OpenTab(
                tab_id=tab_id, target_id=tab_id, url=f"https://example.com/{tab_id}"
            )

        async def advance_to_next_result_page(self, tab_id):
            advanced_tab_ids.append(tab_id)
            return False

    monkeypatch.setattr(
        orchestrator, "GhostBrowserSession", lambda cfg: _MultiTabSession()
    )
    monkeypatch.setattr(
        orchestrator.BrowserToolset, "observe", lambda self: _dummy_obs()
    )

    async def _dummy_obs():
        return "{}"

    async def navigate_and_switch(client, toolset, task, obs, profile=None, **kwargs):
        toolset._tab_id = "tab-listing"
        toolset.successful_action_count = 1
        return NavigationOutcome.RESULTS_READY, BrowseUsage()

    monkeypatch.setattr(orchestrator, "navigate_with_tools", navigate_and_switch)

    async def fake_capture(session, tab_id, index, max_chars):
        captured_tab_ids.append(tab_id)
        return PageArtifact(
            artifact_id=f"art-{index}",
            url=f"https://example.com/{tab_id}",
            tab_id=tab_id,
            content_hash=f"hash-{index}",
            text="evidence text",
        )

    monkeypatch.setattr(orchestrator, "capture_page", fake_capture)

    async def fake_assess(client, task, artifact, prior_claims, prior_gaps, **kwargs):
        return (
            EvidenceAssessment(answerability="partial", next_action="paginate"),
            [],
            BrowseUsage(),
        )

    monkeypatch.setattr(orchestrator, "assess_page", fake_assess)

    task = BrowseTask(
        seed_urls=["https://example.com/search"],
        subject="test",
        allowed_domains=["example.com"],
        retain_final_page=True,
    )

    result = await orchestrator.run_task(
        task,
        cdp_url="http://localhost:9222",
        navigator_client=object(),
        extractor_client=object(),
    )

    assert captured_tab_ids == ["tab-listing"]
    assert advanced_tab_ids == ["tab-listing"]
    assert settled_tab_ids == ["tab-listing"]
    assert retained_tab_ids == ["tab-listing"]
    assert result.task_results[0].status is BrowseTerminalState.LIMIT_REACHED
