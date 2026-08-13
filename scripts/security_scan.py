#!/usr/bin/env python
"""
Run the security scanners over this repository.

One entry point for the three checks that guard OWASP A06 (vulnerable and
outdated components) and give the project static analysis coverage:

* ``pip-audit``  — known CVEs in the pinned Python dependency set
* ``bandit``     — SAST over ``backend/app``
* ``npm audit``  — known CVEs in the frontend dependency tree

Usage::

    python scripts/security_scan.py                 # everything
    python scripts/security_scan.py --only bandit   # one scanner
    python scripts/security_scan.py --json          # machine-readable summary

Exits non-zero if any scanner reports a finding, so it works unchanged as a CI
gate and as a pre-release check. A scanner that is not installed is reported as
``skipped`` rather than silently passing — a missing scanner must never look
like a clean result. For the same reason, a scanner that *ran* but produced an
empty report is reported as **failed**: auditing nothing is not the same as
finding nothing.

.. note::
   ``pip-audit`` resolves the requirements inside a throwaway virtualenv, so it
   needs writable space on the temp drive. If it reports "audited 0 packages",
   check free space and point ``TMPDIR``/``TEMP`` somewhere with room.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"
ALLOWLIST_PATH = REPO_ROOT / "security-allowlist.json"

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

#: npm audit severity at or above which the scan fails.
NPM_AUDIT_LEVEL = "high"

#: bandit severity/confidence floor. Medium and above are actionable; the
#: low-severity band is dominated by style-level advisories.
BANDIT_SEVERITY = "medium"
BANDIT_CONFIDENCE = "medium"


class ScanResult:
    def __init__(
        self,
        name: str,
        status: str,
        summary: str,
        output: str = "",
        command: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self.status = status
        self.summary = summary
        self.output = output
        self.command = command or []

    def to_dict(self) -> Dict[str, object]:
        return {
            "scanner": self.name,
            "status": self.status,
            "summary": self.summary,
            "command": " ".join(self.command),
        }


def _run(command: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=False,
    )


def load_allowlist(path: Path = ALLOWLIST_PATH) -> Dict[str, Dict[str, dict]]:
    """Triaged findings that do not block the build, keyed by scanner/package."""
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        scanner: {entry["package"].lower(): entry for entry in entries}
        for scanner, entries in raw.items()
        if not scanner.startswith("_")
    }


def expired_allowlist_entries(
    allowlist: Dict[str, Dict[str, dict]], today: Optional[date] = None
) -> List[str]:
    """Entries past their review date.

    An accepted risk that nobody re-reads is just an unfixed vulnerability with
    extra steps, so an expired entry fails the run.
    """
    today = today or date.today()
    expired = []
    for scanner, entries in allowlist.items():
        for package, entry in entries.items():
            review_by = entry.get("review_by")
            if not review_by:
                expired.append(f"{scanner}:{package} (no review_by date)")
                continue
            if date.fromisoformat(review_by) < today:
                expired.append(f"{scanner}:{package} (due {review_by})")
    return expired


def _accepted(allowlist: Dict[str, Dict[str, dict]], scanner: str, package: str) -> bool:
    return package.lower() in allowlist.get(scanner, {})


def _resolve(executable: str, module: str) -> Optional[List[str]]:
    """Prefer the console script, fall back to ``python -m``.

    A user-level ``pip install`` on Windows frequently puts the script outside
    PATH; the module is always importable, so a working scanner is never
    reported as missing.
    """
    found = shutil.which(executable)
    if found:
        return [found]
    probe = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", module, "--version"],
        capture_output=True,
        text=True,
        shell=False,
    )
    return [sys.executable, "-m", module] if probe.returncode == 0 else None


def _missing(name: str, hint: str) -> ScanResult:
    return ScanResult(name, STATUS_SKIPPED, f"{name} is not installed — {hint}")


def run_pip_audit() -> ScanResult:
    """Known CVEs in the pinned Python dependencies (OWASP A06)."""
    runner = _resolve("pip-audit", "pip_audit")
    if runner is None:
        return _missing(
            "pip-audit", "pip install -r backend/requirements-security.txt"
        )

    command = runner + [
        "--requirement",
        "requirements.txt",
        "--strict",
        "--progress-spinner",
        "off",
        "--format",
        "json",
    ]
    proc = _run(command, BACKEND)
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return ScanResult(
            "pip-audit",
            STATUS_FAILED,
            "could not parse pip-audit output",
            (proc.stdout + proc.stderr)[-1500:],
            command,
        )

    # pip-audit exits non-zero both when it finds vulnerabilities and when it
    # fails to build its resolution environment. An empty dependency list means
    # nothing was audited, which is not the same as nothing being vulnerable —
    # reporting that as a pass would be a silent false negative.
    if not report.get("dependencies"):
        return ScanResult(
            "pip-audit",
            STATUS_FAILED,
            "pip-audit audited 0 packages (it did not run correctly)",
            (proc.stderr or proc.stdout)[-1500:],
            command,
        )

    vulnerable = [
        dep for dep in report.get("dependencies", []) if dep.get("vulns")
    ]
    allowlist = load_allowlist()
    blocking = [
        dep
        for dep in vulnerable
        if not _accepted(allowlist, "pip-audit", dep.get("name", ""))
    ]
    accepted = len(vulnerable) - len(blocking)
    if blocking:
        lines = [
            f"{dep['name']}=={dep.get('version')}: "
            + ", ".join(v.get("id", "?") for v in dep["vulns"])
            for dep in blocking
        ]
        return ScanResult(
            "pip-audit",
            STATUS_FAILED,
            f"{len(blocking)} vulnerable package(s)",
            "\n".join(lines),
            command,
        )
    checked = len(report.get("dependencies", []))
    note = f" ({accepted} triaged)" if accepted else ""
    return ScanResult(
        "pip-audit",
        STATUS_PASSED,
        f"no unreviewed CVEs in {checked} packages{note}",
        "",
        command,
    )


def run_bandit() -> ScanResult:
    """Static analysis over the application source."""
    runner = _resolve("bandit", "bandit")
    if runner is None:
        return _missing("bandit", "pip install -r backend/requirements-security.txt")

    command = runner + [
        "--configfile",
        "bandit.yaml",
        "--recursive",
        "app",
        "--severity-level",
        BANDIT_SEVERITY,
        "--confidence-level",
        BANDIT_CONFIDENCE,
        "--format",
        "json",
        "--quiet",
    ]
    proc = _run(command, BACKEND)
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return ScanResult(
            "bandit",
            STATUS_FAILED,
            "could not parse bandit output",
            proc.stdout + proc.stderr,
            command,
        )

    findings = report.get("results", [])
    if findings:
        lines = [
            f"{f.get('filename')}:{f.get('line_number')} "
            f"[{f.get('test_id')}/{f.get('issue_severity')}] {f.get('issue_text')}"
            for f in findings
        ]
        return ScanResult(
            "bandit",
            STATUS_FAILED,
            f"{len(findings)} finding(s) at {BANDIT_SEVERITY}+ severity",
            "\n".join(lines),
            command,
        )
    scanned = len(report.get("metrics", {})) - 1  # metrics carries a _totals key
    return ScanResult(
        "bandit",
        STATUS_PASSED,
        f"no findings at {BANDIT_SEVERITY}+ severity across {max(scanned, 0)} files",
        "",
        command,
    )


def run_npm_audit() -> ScanResult:
    """Known CVEs in the shipped frontend dependency tree (OWASP A06).

    Scoped with ``--omit=dev``: the gate is about code that reaches a user's
    browser. Build-only advisories (the react-scripts toolchain drags in a
    large unmaintained tree) are reported separately by
    ``npm audit`` without the flag, and tracked rather than blocking releases.
    """
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        return _missing("npm-audit", "install Node.js")
    if not (FRONTEND / "node_modules").exists():
        return ScanResult(
            "npm-audit",
            STATUS_SKIPPED,
            "frontend/node_modules is missing — run npm ci first",
        )

    command = [
        npm,
        "audit",
        "--omit=dev",
        "--audit-level",
        NPM_AUDIT_LEVEL,
        "--json",
    ]
    proc = _run(command, FRONTEND)
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return ScanResult(
            "npm-audit",
            STATUS_FAILED,
            "could not parse npm audit output",
            (proc.stdout + proc.stderr)[-1500:],
            command,
        )

    # Same reasoning as pip-audit: a run that produced no metadata did not
    # audit anything, and must not be reported as clean.
    if "metadata" not in report:
        return ScanResult(
            "npm-audit",
            STATUS_FAILED,
            "npm audit produced no report (it did not run correctly)",
            (proc.stderr or proc.stdout)[-1500:],
            command,
        )

    totals = (report.get("metadata") or {}).get("vulnerabilities") or {}
    detail = ", ".join(f"{level}={count}" for level, count in sorted(totals.items()))
    allowlist = load_allowlist()
    blocking = sorted(
        name
        for name, entry in (report.get("vulnerabilities") or {}).items()
        if entry.get("severity") in ("high", "critical")
        and not _accepted(allowlist, "npm-audit", name)
    )
    if blocking:
        return ScanResult(
            "npm-audit",
            STATUS_FAILED,
            f"{len(blocking)} unreviewed high/critical advisory(ies) ({detail})",
            "\n".join(blocking),
            command,
        )
    return ScanResult(
        "npm-audit",
        STATUS_PASSED,
        f"no unreviewed high/critical advisories in the shipped tree ({detail or 'none'})",
        "",
        command,
    )


SCANNERS = {
    "pip-audit": run_pip_audit,
    "bandit": run_bandit,
    "npm-audit": run_npm_audit,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=sorted(SCANNERS),
        action="append",
        help="Run only the named scanner (repeatable).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit a machine-readable summary."
    )
    parser.add_argument(
        "--allow-skipped",
        action="store_true",
        help="Treat a missing scanner as success (local runs only, never CI).",
    )
    args = parser.parse_args(argv)

    selected = args.only or list(SCANNERS)
    results = [SCANNERS[name]() for name in selected]
    expired = expired_allowlist_entries(load_allowlist())

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for result in results:
            marker = {
                STATUS_PASSED: "PASS",
                STATUS_FAILED: "FAIL",
                STATUS_SKIPPED: "SKIP",
            }[result.status]
            print(f"[{marker}] {result.name}: {result.summary}")
            if result.output:
                for line in result.output.splitlines():
                    print(f"        {line}")
        for entry in expired:
            print(f"[FAIL] allowlist: {entry} is past its review date")

    failed = [r for r in results if r.status == STATUS_FAILED]
    skipped = [r for r in results if r.status == STATUS_SKIPPED]
    if failed or expired:
        return 1
    if skipped and not args.allow_skipped:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
