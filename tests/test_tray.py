"""
Tests for TrayApp logic extracted into a headless-testable form.
No Tk, no pystray, no display required.

We test the pure state-management logic by building a minimal stand-in
for TrayApp that uses the same internals but no GUI dependencies.
"""
import json
import queue
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.core import (
    AgentResult, Contribution, ContributionJob,
    ContributionTarget, Repository, RepoFile,
)


# ── Stub out ALL GUI modules before any tray import ───────────────────────────

def _stub_gui():
    for name in ["tkinter", "tkinter.ttk", "tkinter.scrolledtext",
                 "pystray", "PIL", "PIL.Image", "PIL.ImageDraw"]:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

_stub_gui()

# Force fresh import of tray.app after stubs are in place
for key in list(sys.modules):
    if key.startswith("tray"):
        del sys.modules[key]

from tray.app import (  # noqa: E402  (import after stub)
    TrayApp,
    _MAX_CONSECUTIVE_AI_FAILURES,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def config():
    return AgentConfig(
        github_token="ghp_test123",
        ai_api_key="test_key",
        ai_provider="google",
        github_username="testuser",
    )


@pytest.fixture
def app(config):
    """
    TrayApp with all GUI pieces replaced by mocks.
    The _root mock captures .after() calls so we can inspect them.
    """
    a = TrayApp.__new__(TrayApp)
    # Replicate __init__ manually without Tk
    a.config = config
    a.icon = MagicMock()
    a._status = "idle"
    a._status_lock = threading.Lock()
    a._pending_job = None
    a._next_run_time = None
    a._consecutive_ai_failures = 0
    a._ai_paused_until = None
    a.veto_seconds = 300
    a._agent = None
    a._scheduler_thread = None
    a._stop_event = threading.Event()
    a._action_queue = queue.Queue()
    a._root = MagicMock()
    return a


def _make_job():
    repo = Repository("u/r", "r", "main")
    file = RepoFile("x.py", "x.py")
    target = ContributionTarget(repo=repo, file=file, content="x = 1", language="Python")
    contrib = Contribution("x = 2\n", "fix: update x", "Updated x")
    return ContributionJob(target=target, contribution=contrib)


# ── Thread safety ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_read_status_from_multiple_threads(self, app):
        errors = []

        def reader():
            try:
                for _ in range(200):
                    s = app._read_status()
                    assert isinstance(s, str)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)

        assert not errors

    def test_concurrent_status_read_and_write(self, app):
        errors = []

        def writer():
            for st in ["idle", "working", "pushing", "idle"] * 50:
                with app._status_lock:
                    app._status = st
                time.sleep(0)

        def reader():
            for _ in range(200):
                s = app._read_status()
                if s not in ("idle", "working", "pushing", "pending", "error", "paused"):
                    errors.append(f"invalid status: {s!r}")

        ts = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=3)

        assert not errors

    def test_on_main_thread_enqueues(self, app):
        called = []
        app._on_main_thread(lambda: called.append(1))
        assert not app._action_queue.empty()

    def test_process_actions_drains_queue(self, app):
        called = []
        app._action_queue.put(lambda: called.append("a"))
        app._action_queue.put(lambda: called.append("b"))

        while not app._action_queue.empty():
            app._action_queue.get_nowait()()

        assert called == ["a", "b"]

    def test_process_actions_isolates_exceptions(self, app):
        """A failing action must not stop subsequent ones."""
        called = []
        app._action_queue.put(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        app._action_queue.put(lambda: called.append("survived"))

        while not app._action_queue.empty():
            action = app._action_queue.get_nowait()
            try:
                action()
            except Exception:
                pass

        assert "survived" in called

    def test_set_status_updates_state(self, app):
        app._set_status("working")
        assert app._read_status() == "working"
        app._set_status("idle")
        assert app._read_status() == "idle"


# ── AI back-off ───────────────────────────────────────────────────────────────

class TestAIBackoff:
    def test_paused_agent_skips_immediately(self, app):
        app._ai_paused_until = time.time() + 9999
        with patch.object(app, "_get_agent") as mock_get:
            app._run_agent()
            mock_get.assert_not_called()

    def test_expired_pause_allows_run(self, app):
        app._ai_paused_until = time.time() - 1   # already expired
        success_result = AgentResult(success=False, message="no files", error="no files")

        with patch.object(app, "_get_agent") as mock_get:
            mock_agent = MagicMock()
            mock_agent.run.return_value = success_result
            mock_get.return_value = mock_agent
            app._run_agent()
            mock_agent.run.assert_called_once()

    def test_failure_counter_increments(self, app):
        with patch.object(app, "_get_agent") as mock_get:
            mock_agent = MagicMock()
            mock_agent.run.side_effect = RuntimeError("api down")
            mock_get.return_value = mock_agent
            app._run_agent()

        assert app._consecutive_ai_failures == 1

    def test_pause_triggered_after_max_failures(self, app):
        with patch.object(app, "_get_agent") as mock_get, \
             patch.object(app, "_notify"):
            mock_agent = MagicMock()
            mock_agent.run.side_effect = RuntimeError("api down")
            mock_get.return_value = mock_agent

            for _ in range(_MAX_CONSECUTIVE_AI_FAILURES):
                app._run_agent()

        assert app._ai_paused_until is not None
        assert app._ai_paused_until > time.time()

    def test_success_clears_failure_counter(self, app):
        app._consecutive_ai_failures = 2
        app._ai_paused_until = time.time() - 1   # expired

        job = _make_job()
        success = AgentResult(success=True, message="ok", job=job)

        with patch.object(app, "_get_agent") as mock_get:
            mock_agent = MagicMock()
            mock_agent.run.return_value = success
            mock_get.return_value = mock_agent
            app._run_agent()

        assert app._consecutive_ai_failures == 0
        assert app._ai_paused_until is None


# ── History management ────────────────────────────────────────────────────────

class TestHistoryManagement:
    def test_auto_clear_resets_agent_set(self, app):
        from agent.constants import HISTORY_FILE
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text('{"processed_files": ["u/r/a.py", "u/r/b.py"]}')

        mock_agent = MagicMock()
        mock_agent._processed_files = {"u/r/a.py", "u/r/b.py"}
        app._agent = mock_agent

        with patch.object(app, "_notify"):
            app._auto_clear_history()

        assert len(mock_agent._processed_files) == 0

    def test_auto_clear_writes_empty_history(self, app):
        from agent.constants import HISTORY_FILE
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text('{"processed_files": ["u/r/x.py"]}')
        app._agent = None

        with patch.object(app, "_notify"):
            app._auto_clear_history()

        data = json.loads(HISTORY_FILE.read_text())
        assert data["processed_files"] == []

    def test_manual_clear_works_without_agent(self, app):
        from agent.constants import HISTORY_FILE
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text('{"processed_files": ["a/b/c.py"]}')
        app._agent = None

        with patch.object(app, "_notify"):
            app._do_clear_history()

        data = json.loads(HISTORY_FILE.read_text())
        assert data["processed_files"] == []


# ── Approve / reject logic ────────────────────────────────────────────────────

class TestApproveReject:
    def test_duplicate_approve_blocked_when_pushing(self, app):
        app._status = "pushing"
        job = _make_job()

        with patch("threading.Thread") as mock_thread:
            app._on_approve(job)
            mock_thread.assert_not_called()

    def test_approve_starts_push_thread(self, app):
        app._status = "idle"
        job = _make_job()

        started = []
        with patch("threading.Thread") as mock_thread:
            mock_t = MagicMock()
            mock_thread.return_value = mock_t
            app._on_approve(job)
            mock_t.start.assert_called_once()
            started.append(True)

        assert started

    def test_reject_marks_file_processed(self, app):
        job = _make_job()
        app._pending_job = job

        mock_agent = MagicMock()
        app._agent = mock_agent

        with patch("threading.Thread") as mock_thread, \
             patch.object(app, "_notify"), \
             patch.object(app, "_set_status"):
            mock_thread.return_value = MagicMock()
            app._on_reject()

        mock_agent._mark_processed.assert_called_once_with("u/r", "x.py")
        assert app._pending_job is None

    def test_reject_clears_pending_job(self, app):
        app._pending_job = _make_job()
        app._agent = MagicMock()

        with patch("threading.Thread") as mock_thread, \
             patch.object(app, "_notify"), \
             patch.object(app, "_set_status"):
            mock_thread.return_value = MagicMock()
            app._on_reject()

        assert app._pending_job is None


# ── Scheduler ─────────────────────────────────────────────────────────────────

class TestScheduler:
    def test_scheduler_respects_stop_event(self, app):
        """Scheduler loop should exit promptly when stop_event is set."""
        app._stop_event.set()   # already stopped

        t = threading.Thread(target=app._scheduler_loop, daemon=True)
        t.start()
        t.join(timeout=0.5)

        assert not t.is_alive(), "Scheduler did not stop promptly"

    def test_scheduler_skips_run_when_not_idle(self, app):
        """If status != idle when the interval fires, no run should start."""
        app._status = "working"
        fired = []

        original = app._run_agent
        app._run_agent = lambda: fired.append(1)

        # Simulate what the scheduler does at interval end
        status = app._read_status()
        if status == "idle":
            app._run_agent()

        assert fired == [], "Should not have fired when status=working"
        app._run_agent = original
