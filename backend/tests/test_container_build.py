"""
Container build guards.

A Dockerfile is only validated when something builds it, and nothing in the
default test run has a Docker daemon. That gap is not theoretical: the frontend
image once carried two stages both named ``build``, which BuildKit rejects
outright ("duplicate stage name"), so ``docker compose up --build`` failed
while every test still passed.

These assertions parse the Dockerfiles and the compose file directly. They
catch the structural mistakes that make an image unbuildable without needing a
daemon. Real builds happen in the ``containers`` workflow.
"""

import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

DOCKERFILES = {
    "backend": REPO_ROOT / "backend" / "Dockerfile",
    "frontend": REPO_ROOT / "frontend" / "Dockerfile",
    "nginx": REPO_ROOT / "nginx" / "Dockerfile",
}

COMPOSE_TEXT = COMPOSE_FILE.read_text(encoding="utf-8")

_FROM = re.compile(r"^FROM\s+(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*$", re.IGNORECASE)
_COPY_FROM = re.compile(r"^COPY\s+.*?--from=(?P<source>\S+)", re.IGNORECASE)


def _logical_lines(dockerfile: Path):
    """Yield instructions with backslash continuations joined and comments dropped."""
    joined = []
    buffer = ""
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            buffer += line[:-1].rstrip() + " "
            continue
        joined.append((buffer + line).strip())
        buffer = ""
    if buffer:
        joined.append(buffer.strip())
    return joined


def _stages(dockerfile: Path):
    return [
        match.group("stage")
        for line in _logical_lines(dockerfile)
        if (match := _FROM.match(line)) and match.group("stage")
    ]


@pytest.mark.parametrize("name", sorted(DOCKERFILES))
class TestDockerfileStructure:
    def test_the_dockerfile_exists(self, name):
        assert DOCKERFILES[name].is_file()

    def test_stage_names_are_unique(self, name):
        # BuildKit fails the whole build on a duplicate, and the second
        # definition silently shadows the first for every `--from=` reference.
        stages = _stages(DOCKERFILES[name])
        duplicates = {stage for stage in stages if stages.count(stage) > 1}
        assert not duplicates, f"{name}: duplicate stage name(s) {sorted(duplicates)}"

    def test_copy_from_targets_are_declared_stages(self, name):
        dockerfile = DOCKERFILES[name]
        declared = set(_stages(dockerfile))
        for line in _logical_lines(dockerfile):
            match = _COPY_FROM.match(line)
            if not match:
                continue
            source = match.group("source")
            # A digit is a stage index and anything with a slash or colon is an
            # external image; neither needs a local stage.
            if source.isdigit() or "/" in source or ":" in source:
                continue
            assert source in declared, f"{name}: COPY --from={source} has no such stage"

    def test_the_image_declares_a_healthcheck(self, name):
        # compose gates `depends_on` on `service_healthy`, which never becomes
        # true for an image without one.
        assert any(
            line.upper().startswith("HEALTHCHECK") for line in _logical_lines(DOCKERFILES[name])
        ), f"{name}: no HEALTHCHECK"

    def test_the_container_does_not_run_as_root(self, name):
        users = [line.split()[1] for line in _logical_lines(DOCKERFILES[name]) if line.upper().startswith("USER ")]
        assert users, f"{name}: never drops to a non-root USER"
        assert users[-1] != "root"


class TestBuildContexts:
    """Everything compose asks to build must be present and lean."""

    def test_every_build_context_and_dockerfile_resolves(self):
        for context in re.findall(r"context:\s*(\S+)", COMPOSE_TEXT):
            resolved = (REPO_ROOT / context).resolve()
            assert resolved.is_dir(), f"missing build context {context}"
            assert (resolved / "Dockerfile").is_file(), f"missing Dockerfile in {context}"

    @pytest.mark.parametrize(
        ("context", "expected"),
        [
            # Several hundred megabytes of browsers, and a test tree the build
            # never reads — both would otherwise be uploaded on every build.
            ("frontend", (".playwright-browsers", "e2e", "node_modules", "build")),
            # A checked-out virtualenv would shadow nothing but still ships.
            ("backend", ("venv", ".venv", "tests", "*.db")),
        ],
    )
    def test_the_build_context_excludes_local_only_trees(self, context, expected):
        ignore_file = REPO_ROOT / context / ".dockerignore"
        assert ignore_file.is_file(), f"{context}: no .dockerignore"
        patterns = {
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        for entry in expected:
            assert entry in patterns, f"{context}/.dockerignore does not exclude {entry}"

    def test_secrets_stay_out_of_the_backend_image(self):
        patterns = (REPO_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
        for secret in (".env", "firebase-credentials.json"):
            assert secret in patterns
