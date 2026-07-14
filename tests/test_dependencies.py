"""Keep project metadata, Docker requirements, and constraints synchronized."""

from pathlib import Path
from tomllib import loads

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).parents[1]


def _requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_runtime_dependency_declarations_and_constraints_agree():
    project = loads((ROOT / "pyproject.toml").read_text())
    metadata_requirements = {
        canonicalize_name(req.name): req
        for dep in project["project"]["dependencies"]
        for req in [Requirement(dep)]
    }
    docker_requirements = {
        canonicalize_name(req.name): req
        for dep in _requirement_lines(ROOT / "requirements.txt")
        for req in [Requirement(dep)]
    }
    constraints = {
        canonicalize_name(req.name): req
        for dep in _requirement_lines(ROOT / "constraints.txt")
        for req in [Requirement(dep)]
    }

    assert metadata_requirements == docker_requirements
    for name, requirement in metadata_requirements.items():
        assert name in constraints
        assert constraints[name].specifier == requirement.specifier
