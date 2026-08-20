"""End-to-end graph behaviour: wiring, error propagation, provenance.

Covers B6 (an error in any node must abort, not just nodes 2/4/7) and B8 (the
entry point must report failure rather than printing "[SUCCESS]" regardless).
"""

from __future__ import annotations

import json

import pytest

from config.settings import settings
from src.graph.workflow import (
    AGENT_NODE_NAMES,
    LINEAR_NODES,
    VideoEditorPipeline,
    create_editor_graph,
)
from src.schema.state import EditorState, merge_agent_evaluations
from tests.conftest import make_candidate


@pytest.fixture(scope="module")
def demo_state() -> EditorState:
    """One full demo run, reused across assertions."""
    return VideoEditorPipeline(use_checkpointer=False).run(
        "", demo_mode=True, thread_id="test-demo"
    )


class TestGraphStructure:
    def test_graph_compiles(self):
        assert create_editor_graph() is not None

    def test_six_agent_branches_exist(self):
        assert len(AGENT_NODE_NAMES) == 6
        assert len(set(AGENT_NODE_NAMES)) == 6

    def test_seven_linear_nodes(self):
        assert len(LINEAR_NODES) == 7


class TestDemoRun:
    def test_completes_without_error(self, demo_state):
        assert demo_state.error is None
        assert demo_state.failed_stage is None

    def test_produces_clips(self, demo_state):
        assert len(demo_state.final_clips) >= 1

    def test_all_ten_stages_are_logged(self, demo_state):
        joined = "\n".join(demo_state.logs)
        for label in ("Node 1", "Node 2", "Node 3", "Node 4", "Node 5",
                      "Node 6", "Node 7", "Node 8", "Node 9", "Node 10"):
            assert label in joined, label

    def test_all_six_agents_ran_and_merged(self, demo_state):
        """The reducer must compose six branches, not let them clobber."""
        assert demo_state.agent_evaluations
        for clip_id, per_agent in demo_state.agent_evaluations.items():
            assert len(per_agent) == 6, f"{clip_id} has {len(per_agent)} agents"

    def test_logs_from_parallel_branches_all_survive(self, demo_state):
        """With the old manual log copying, concurrent branches lost entries."""
        agent_logs = [line for line in demo_state.logs if "Node 8" in line]
        # One "scored" line plus one "completed in" line per agent.
        assert len(agent_logs) >= 6

    def test_ranks_are_sequential(self, demo_state):
        assert [c.rank for c in demo_state.final_clips] == \
               list(range(1, len(demo_state.final_clips) + 1))

    def test_clips_respect_the_duration_window(self, demo_state):
        for clip in demo_state.final_clips:
            assert settings.min_clip_duration_sec <= clip.duration_seconds \
                   <= settings.max_clip_duration_sec

    def test_no_two_clips_substantially_overlap(self, demo_state):
        from src.utils.metrics import overlap_ratio

        clips = demo_state.final_clips
        for i, a in enumerate(clips):
            for b in clips[i + 1:]:
                ratio = overlap_ratio(
                    a.start_seconds, a.end_seconds, b.start_seconds, b.end_seconds
                )
                assert ratio <= settings.dedup_overlap_threshold


class TestProvenance:
    def test_demo_run_is_marked_synthetic(self, demo_state):
        provenance = demo_state.provenance()
        assert provenance.is_synthetic
        assert provenance.media_source == "fixture"
        assert provenance.transcript_source == "fixture"

    def test_banner_says_synthetic(self, demo_state):
        assert "SYNTHETIC" in demo_state.provenance().banner().upper()

    def test_scoring_mode_is_recorded(self, demo_state):
        assert demo_state.scoring_mode in ("llm", "heuristic")

    def test_every_clip_carries_provenance(self, demo_state):
        assert all(c.provenance is not None for c in demo_state.final_clips)

    def test_warns_about_fixture_data(self, demo_state):
        assert any("synthetic" in w.lower() for w in demo_state.warnings)

    def test_serialised_output_exposes_synthetic_flag(self, demo_state):
        payload = {
            "provenance": demo_state.provenance().model_dump(mode="json"),
            "is_synthetic": demo_state.provenance().is_synthetic,
            "clips": [c.model_dump(mode="json") for c in demo_state.final_clips],
        }
        # Must survive a JSON round trip so consumers can see it.
        restored = json.loads(json.dumps(payload))
        assert restored["is_synthetic"] is True


class TestNumericAdjustments:
    def test_adjustments_are_numeric_not_prose(self, demo_state):
        for clip in demo_state.final_clips:
            assert isinstance(clip.start_adjustment_sec, float)
            assert isinstance(clip.end_adjustment_sec, float)
            assert isinstance(clip.adjustment_rationale, str)

    def test_adjusted_range_is_valid(self, demo_state):
        for clip in demo_state.final_clips:
            assert clip.adjusted_start_seconds >= 0.0
            assert clip.adjusted_end_seconds > clip.adjusted_start_seconds


class TestErrorPropagationB6:
    """An error in *any* node must abort. The original only checked after 2/4/7,
    so node_05 set `error` and the unconditional edge to node_06 ignored it."""

    @pytest.mark.parametrize("node_index", range(7))
    def test_failure_in_each_linear_node_aborts(self, monkeypatch, node_index):
        from src.errors import PipelineError
        from src.nodes._base import pipeline_node

        node_name, _ = LINEAR_NODES[node_index]
        boom_stage = f"forced failure in {node_name}"

        # Wrapped exactly as the real nodes are, so this exercises the
        # decorator -> state.error -> conditional-edge path rather than letting
        # the exception escape the graph.
        @pipeline_node(stage="forced", label=node_name)
        def boom(state):
            raise PipelineError(boom_stage)

        # Patch the entry in the module-level list the builder reads.
        patched = list(LINEAR_NODES)
        patched[node_index] = (node_name, boom)
        monkeypatch.setattr("src.graph.workflow.LINEAR_NODES", patched)

        state = VideoEditorPipeline(use_checkpointer=False).run(
            "", demo_mode=True, thread_id=f"test-fail-{node_index}"
        )
        assert state.error is not None, f"{node_name} failure was not propagated"
        assert boom_stage in state.error
        assert not state.final_clips
        assert "ABORT" in "\n".join(state.logs).upper()

    def test_a_single_failing_agent_does_not_abort_the_run(self, monkeypatch):
        """Five verdicts are still usable, so one branch failing is tolerable."""
        from src.errors import LLMError

        original = None
        from src.agents import editors

        original = editors.evaluate_heuristically
        calls = {"n": 0}

        def flaky(agent, candidate, episode_duration=0.0):
            if agent.key == "debate":
                calls["n"] += 1
                raise LLMError("simulated agent outage")
            return original(agent, candidate, episode_duration)

        monkeypatch.setattr("src.agents.editors.evaluate_heuristically", flaky)

        state = VideoEditorPipeline(use_checkpointer=False).run(
            "", demo_mode=True, thread_id="test-flaky-agent"
        )
        assert state.error is None, "one bad agent must not fail the pipeline"
        assert state.final_clips
        assert any("Debate" in w for w in state.warnings)
        # The other five still recorded verdicts.
        for per_agent in state.agent_evaluations.values():
            assert "debate" not in per_agent
            assert len(per_agent) == 5


class TestRealSourceFailsLoudly:
    """§3: a nonexistent source must fail, not fall through to fixture data."""

    def test_missing_file_produces_an_error_not_clips(self):
        state = VideoEditorPipeline(use_checkpointer=False).run(
            "/definitely/not/a/real/file.mp3", thread_id="test-missing"
        )
        assert state.error is not None
        assert state.failed_stage == "download"
        assert not state.final_clips

    def test_error_does_not_masquerade_as_fixture_output(self):
        state = VideoEditorPipeline(use_checkpointer=False).run(
            "/definitely/not/a/real/file.mp3", thread_id="test-missing-2"
        )
        assert state.transcript_source != "fixture"
        assert "99%" not in " ".join(
            c.raw_text for c in state.candidate_clips
        )


class TestReducer:
    def test_merge_composes_agents_for_the_same_clip(self):
        from tests.test_chief_editor import build_evaluation

        left = {"clip_01": {"hook": build_evaluation(agent_name="Hook")}}
        right = {"clip_01": {"story": build_evaluation(agent_name="Story")}}
        merged = merge_agent_evaluations(left, right)
        assert set(merged["clip_01"]) == {"hook", "story"}

    def test_merge_keeps_separate_clips(self):
        from tests.test_chief_editor import build_evaluation

        left = {"clip_01": {"hook": build_evaluation()}}
        right = {"clip_02": {"hook": build_evaluation()}}
        merged = merge_agent_evaluations(left, right)
        assert set(merged) == {"clip_01", "clip_02"}

    def test_merge_does_not_mutate_inputs(self):
        from tests.test_chief_editor import build_evaluation

        left = {"clip_01": {"hook": build_evaluation()}}
        right = {"clip_01": {"story": build_evaluation()}}
        merge_agent_evaluations(left, right)
        assert set(left["clip_01"]) == {"hook"}

    def test_logs_reducer_appends(self):
        state = EditorState(logs=["first"])
        # LangGraph applies operator.add for this field.
        assert state.logs == ["first"]
        combined = state.logs + ["second"]
        assert combined == ["first", "second"]


class TestCLIExitCodes:
    """B8: the CLI must not print success unconditionally."""

    def test_demo_run_exits_zero(self, tmp_path, monkeypatch):
        import main as cli

        monkeypatch.setattr(settings, "output_dir", tmp_path)
        assert cli.main(["--demo", "--output", "demo.json"]) == cli.EXIT_OK
        written = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
        assert written["is_synthetic"] is True
        assert written["clips"]

    def test_bad_source_exits_nonzero(self, tmp_path, monkeypatch):
        import main as cli

        monkeypatch.setattr(settings, "output_dir", tmp_path)
        code = cli.main(["--source", "/nope/missing.mp3"])
        assert code == cli.EXIT_PIPELINE_ERROR

    def test_output_path_traversal_is_rejected(self, tmp_path, monkeypatch):
        import main as cli

        monkeypatch.setattr(settings, "output_dir", tmp_path)
        assert cli.main(["--demo", "--output", "../escaped.json"]) == cli.EXIT_BAD_USAGE
        assert not (tmp_path.parent / "escaped.json").exists()

    def test_absolute_output_path_is_rejected(self, tmp_path, monkeypatch):
        import main as cli

        monkeypatch.setattr(settings, "output_dir", tmp_path)
        target = tmp_path.parent / "absolute.json"
        assert cli.main(["--demo", "--output", str(target)]) == cli.EXIT_BAD_USAGE

    def test_source_and_demo_are_mutually_exclusive(self):
        import main as cli

        with pytest.raises(SystemExit):
            cli.main(["--demo", "--source", "x.mp3"])

    def test_one_of_source_or_demo_is_required(self):
        import main as cli

        with pytest.raises(SystemExit):
            cli.main([])


class TestDefaultCheckpointerRun:
    """The default construction path -- the one real users actually get.

    Every other pipeline test in this file passes `use_checkpointer=False`, so
    `VideoEditorPipeline()` with its real defaults was exercised by nothing.
    That is how the SQLite checkpointer shipped closing its own database before
    first use: `SqliteSaver.from_conn_string(db).__enter__()` kept no reference
    to the `@contextmanager` generator, so garbage collection ran its `finally`
    and closed the connection. Every entry point -- `--demo` included -- then
    died on the first checkpoint read with

        sqlite3.ProgrammingError: Cannot operate on a closed database.

    These tests fail against c395d0d and pass with the connection owned directly.
    """

    @staticmethod
    def _close(pipeline) -> None:
        """Release the SQLite handle so tmp_path cleanup works on Windows."""
        conn = getattr(pipeline.checkpointer, "conn", None)
        if conn is not None:
            conn.close()

    def test_demo_runs_end_to_end_with_the_default_checkpointer(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "checkpoint_dir", tmp_path / "checkpoints")
        assert settings.checkpoint_enabled, (
            "this test only means anything while checkpointing defaults to on"
        )

        # No use_checkpointer=False. This is the constructor main.py and app.py use.
        pipeline = VideoEditorPipeline()
        try:
            assert pipeline.checkpointer is not None, (
                "default construction must attach a checkpointer"
            )

            state = pipeline.run("", demo_mode=True, thread_id="default-ckpt")

            assert state.error is None, (
                f"default pipeline failed at {state.failed_stage}: {state.error}"
            )
            assert state.final_clips, "default pipeline produced no clips"
        finally:
            self._close(pipeline)

    def test_checkpointer_connection_is_still_usable_after_the_run(
        self, tmp_path, monkeypatch
    ):
        """Reading state back proves the connection outlived construction.

        This is the assertion that pins the bug: on c395d0d the connection is
        already closed by the time anything touches it.
        """
        monkeypatch.setattr(settings, "checkpoint_dir", tmp_path / "checkpoints")

        pipeline = VideoEditorPipeline()
        try:
            pipeline.run("", demo_mode=True, thread_id="readback")

            saved = pipeline.checkpointer.get_tuple(
                {"configurable": {"thread_id": "readback"}}
            )
            assert saved is not None, "the run wrote no checkpoint"
        finally:
            self._close(pipeline)
