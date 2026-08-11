"""Structural guards against defects that are easy to reintroduce.

These assert on the AST and on the compiled graph rather than on source text,
because the modules document the removed behaviour in their docstrings and a
substring scan would match that documentation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_FILES = sorted(
    [*PROJECT_ROOT.glob("src/**/*.py"), *PROJECT_ROOT.glob("config/*.py"),
     PROJECT_ROOT / "main.py", PROJECT_ROOT / "app.py"]
)


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


class TestB18NoSilentExceptionSwallowing:
    """The original had nine `except Exception: pass` handlers, which destroyed
    every diagnostic. A handler may recover, but it must not be silent."""

    @pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda p: str(p.name))
    def test_no_handler_body_is_only_pass(self, path):
        offenders = []
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.ExceptHandler):
                meaningful = [n for n in node.body if not isinstance(n, ast.Pass)]
                if not meaningful:
                    offenders.append(node.lineno)
        assert offenders == [], (
            f"{path.name} has `except: pass` at line(s) {offenders}; "
            f"log the reason or re-raise"
        )

    @pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda p: str(p.name))
    def test_no_bare_except_clause(self, path):
        bare = [
            node.lineno
            for node in ast.walk(parse(path))
            if isinstance(node, ast.ExceptHandler) and node.type is None
        ]
        assert bare == [], f"{path.name} has a bare `except:` at line(s) {bare}"


class TestB19NoInnerHtmlAssignment:
    def test_client_script_never_assigns_innerhtml(self):
        """Only a comment may mention it; assignment is what injects markup."""
        text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        code_lines = [
            line for line in text.splitlines()
            if "innerHTML" in line and not line.strip().startswith(("//", "B19", "*"))
        ]
        assert code_lines == [], f"innerHTML used in code: {code_lines}"

    def test_textcontent_is_used(self):
        text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        assert "textContent" in text


class TestB6EveryNodeIsGuarded:
    """Verified against the compiled graph, not the builder source."""

    def test_every_linear_node_can_reach_abort(self):
        from src.graph.workflow import LINEAR_NODES, create_editor_graph

        graph = create_editor_graph().get_graph()
        edges_by_source: dict[str, set[str]] = {}
        for edge in graph.edges:
            edges_by_source.setdefault(edge.source, set()).add(edge.target)

        for node_name, _ in LINEAR_NODES:
            targets = edges_by_source.get(node_name, set())
            assert "abort" in targets, (
                f"{node_name} has no edge to abort; an error there would be ignored"
            )

    def test_synthesis_node_is_guarded(self):
        from src.graph.workflow import create_editor_graph

        graph = create_editor_graph().get_graph()
        targets = {e.target for e in graph.edges if e.source == "node_09_synthesize"}
        assert "abort" in targets

    def test_all_six_agent_branches_join_at_synthesis(self):
        from src.graph.workflow import AGENT_NODE_NAMES, create_editor_graph

        graph = create_editor_graph().get_graph()
        for name in AGENT_NODE_NAMES:
            targets = {e.target for e in graph.edges if e.source == name}
            assert "node_09_synthesize" in targets, name

    def test_candidates_node_fans_out_to_all_agents(self):
        from src.graph.workflow import AGENT_NODE_NAMES, create_editor_graph

        graph = create_editor_graph().get_graph()
        targets = {e.target for e in graph.edges if e.source == "node_07_candidates"}
        for name in AGENT_NODE_NAMES:
            assert name in targets, f"node_07 does not dispatch to {name}"


class TestNoHardcodedPlaceholders:
    """Values the original presented as measurements while they were constants."""

    def test_no_1800_second_duration_placeholder(self):
        """The downloader returned a hardcoded 1800.0 duration for every file.

        config/settings.py is excluded: `ffmpeg_timeout_sec` is legitimately
        1800 seconds and is a timeout, not a claimed measurement.
        """
        literals = []
        for path in PYTHON_FILES:
            if path.name == "settings.py":
                continue
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Constant) and node.value == 1800.0:
                    literals.append(f"{path.name}:{node.lineno}")
        assert literals == [], f"1800.0 duration placeholder at {literals}"

    def test_no_nine_point_two_confidence_literal(self):
        literals = []
        for path in PYTHON_FILES:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Constant) and node.value == 9.2:
                    literals.append(f"{path.name}:{node.lineno}")
        assert literals == [], f"hardcoded 9.2 confidence at {literals}"


class TestPackageStructure:
    @pytest.mark.parametrize("package", [
        "config", "src", "src/agents", "src/analysis", "src/fixtures",
        "src/graph", "src/nodes", "src/providers", "src/schema", "src/utils",
    ])
    def test_every_package_has_an_init(self, package):
        assert (PROJECT_ROOT / package / "__init__.py").exists(), (
            f"{package} is missing __init__.py"
        )


class TestNoPrintInLibraryCode:
    """Library code must log, not print; only entry points may print."""

    @pytest.mark.parametrize(
        "path",
        [p for p in PYTHON_FILES if p.parent.name not in ("podcast_into_shorts",)
         and p.name not in ("main.py", "app.py")],
        ids=lambda p: str(p.name),
    )
    def test_no_bare_print_calls(self, path):
        prints = [
            node.lineno
            for node in ast.walk(parse(path))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        assert prints == [], f"{path.name} calls print() at line(s) {prints}"
