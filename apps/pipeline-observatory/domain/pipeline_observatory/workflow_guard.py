"""Static check that a GitHub Actions workflow cannot trigger itself (P08-TEST-12, D-03: "a workflow never triggers itself").

No YAML library is available (standard library only), so the check reads the text: the ``on:`` triggers, the ``name:`` and the ``run:``
blocks. A workflow is unsafe when it
  * SELF_PUSH: pushes commits (``git push``) while it is triggered by ``push`` on a branch/path it writes to, without a ``[skip ci]`` marker
    in the commit message, an ``if:`` guard on the actor, or a ``paths-ignore`` covering what it writes;
  * SELF_DISPATCH: dispatches itself (``gh workflow run <itself>``, ``/actions/workflows/<itself>/dispatches``, ``repository_dispatch``
    from its own steps) ;
  * SELF_WORKFLOW_RUN: listens to ``workflow_run`` of its own ``name:``;
  * SELF_PR_LOOP: opens or updates a pull request or issue comment while triggered by ``pull_request``/``issue_comment`` (a bot comment
    re-triggering the comment trigger).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SKIP_MARKERS = ("[skip ci]", "[ci skip]", "[no ci]", "[skip actions]", "[actions skip]")


@dataclass(frozen=True)
class Finding:
    code: str
    line: int
    text: str


def _triggers(lines: list[str]) -> tuple[set[str], str]:
    """The event names under the top-level ``on:`` and the raw text of that block."""
    for i, line in enumerate(lines):
        m = re.match(r"^(on|\"on\"|'on'):\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest.startswith("["):
            return {t.strip() for t in rest.strip("[]").split(",") if t.strip()}, rest
        if rest and not rest.startswith("#"):
            return {rest}, rest
        block = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.startswith((" ", "\t", "#")):
                break
            block.append(nxt)
        events = {re.match(r"^\s{1,4}([a-z_]+):", b).group(1) for b in block if re.match(r"^\s{1,4}[a-z_]+:", b)}
        return events, "\n".join(block)
    return set(), ""


def analyze(text: str, file_name: str = "") -> list[Finding]:
    """The self-trigger findings of one workflow file (empty list = safe). ``file_name`` is the workflow's own file name."""
    lines = text.splitlines()
    events, on_block = _triggers(lines)
    name_m = re.search(r"^name:\s*(.+?)\s*$", text, re.MULTILINE)
    own_name = name_m.group(1).strip("'\"") if name_m else ""
    own_file = file_name.rsplit("/", 1)[-1]
    findings: list[Finding] = []
    guarded_actor = bool(re.search(r"github\.actor\s*!=\s*'github-actions\[bot\]'|github\.triggering_actor\s*!=", text))
    ignores_paths = "paths-ignore" in on_block

    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        if re.search(r"\bgit\s+push\b", s) and "push" in events:
            window = "\n".join(lines[max(0, n - 12):n + 3])
            if not any(marker in window for marker in SKIP_MARKERS) and not guarded_actor and not ignores_paths:
                findings.append(Finding("SELF_PUSH", n, s))
        if re.search(r"\bgh\s+workflow\s+run\b", s) and (not own_file or own_file in s or own_name and own_name in s):
            findings.append(Finding("SELF_DISPATCH", n, s))
        if own_file and re.search(r"/actions/workflows/" + re.escape(own_file) + r"/dispatches", s):
            findings.append(Finding("SELF_DISPATCH", n, s))
        if re.search(r"(/dispatches\b|repository_dispatch)", s) and "repository_dispatch" in events and not own_file:
            findings.append(Finding("SELF_DISPATCH", n, s))
        if re.search(r"\bgh\s+(pr\s+(create|comment|edit)|issue\s+comment)\b", s) and events & {"pull_request", "issue_comment", "pull_request_target"} and not guarded_actor:
            findings.append(Finding("SELF_PR_LOOP", n, s))
    if "workflow_run" in events and own_name:
        m = re.search(r"workflows:\s*\[?([^\]\n]*)\]?(?:\n((?:\s+-.*\n?)*))?", on_block)
        listed = (m.group(1) + (m.group(2) or "")) if m else ""
        if own_name in listed.replace('"', "").replace("'", ""):
            findings.append(Finding("SELF_WORKFLOW_RUN", 1, f"workflow_run listens to {own_name!r}"))
    return findings


def is_safe(text: str, file_name: str = "") -> bool:
    return not analyze(text, file_name)
