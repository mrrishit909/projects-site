"""P08-TEST-12: a workflow never triggers itself. A static check over the workflow text: pushes without a skip marker or a guard, self-dispatch,
a workflow_run of its own name. Fixtures under tests/fixtures/workflows/; the real CI workflow of this app is checked too."""
from pathlib import Path

import pytest
from pipeline_observatory.workflow_guard import analyze, is_safe

from support_db import FIXTURES, ROOT

WF = FIXTURES / "workflows"
REAL = ROOT.parents[1] / ".github" / "workflows" / "pipeline-observatory-ci.yml"


def findings(name):
    return [(f.code) for f in analyze((WF / name).read_text(), name)]


@pytest.mark.parametrize("name", ["good.yml", "other_workflow_run.yml", "self_push_guarded.yml"])
def test_safe_workflows_are_not_flagged(name):
    assert findings(name) == []


@pytest.mark.parametrize("name,code", [("self_push.yml", "SELF_PUSH"), ("self_dispatch.yml", "SELF_DISPATCH"), ("self_dispatch_api.yml", "SELF_DISPATCH"),
                                       ("self_workflow_run.yml", "SELF_WORKFLOW_RUN")])
def test_self_triggering_workflows_are_flagged_with_their_reason(name, code):
    assert findings(name) == [code]


def test_a_finding_names_the_offending_line():
    f, = analyze((WF / "self_push.yml").read_text(), "self_push.yml")
    assert f.code == "SELF_PUSH" and "git push" in f.text and f.line == 17


def test_the_real_ci_workflow_of_this_app_cannot_trigger_itself():
    text = REAL.read_text()
    assert analyze(text, REAL.name) == [] and is_safe(text, REAL.name)
    assert "push:" in text and "branches: [business-data-lab]" in text and "contents: read" in text                  # read-only token, triggered by pushes of people only
    assert "git push" not in text and "gh workflow run" not in text and "workflow_run" not in text and "/dispatches" not in text


def test_adding_a_self_trigger_to_the_real_workflow_is_caught():
    text = REAL.read_text()
    assert [f.code for f in analyze(text + "      - run: git push origin HEAD\n", REAL.name)] == ["SELF_PUSH"]
    assert [f.code for f in analyze(text + f"      - run: gh workflow run {REAL.name}\n", REAL.name)] == ["SELF_DISPATCH"]
    safe_push = text + '      - run: |\n          git commit -m "evidence [skip ci]"\n          git push origin HEAD\n'
    assert analyze(safe_push, REAL.name) == []                                                                       # a skip marker breaks the loop


def test_a_workflow_that_only_runs_on_dispatch_may_push():
    text = "name: manual\non:\n  workflow_dispatch:\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: git push origin HEAD\n"
    assert analyze(text, "manual.yml") == []


def test_the_check_ignores_comments():
    text = (WF / "good.yml").read_text() + "      # - run: git push origin main\n      # gh workflow run good.yml\n"
    assert analyze(text, "good.yml") == []


def test_a_comment_loop_in_a_pull_request_workflow_is_flagged():
    text = "name: bot\non:\n  pull_request:\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: gh pr comment 1 --body hi\n"
    assert [f.code for f in analyze(text, "bot.yml")] == ["SELF_PR_LOOP"]
