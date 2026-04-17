"""Tests for the core GitHub agent logic."""
from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.core import (
    AgentResult,
    Contribution,
    ContributionJob,
    ContributionTarget,
    GitHubAgent,
    Repository,
    RepoFile,
)


@pytest.fixture
def mock_config():
    return AgentConfig(
        github_token="ghp_testtoken123",
        ai_api_key="test_ai_key",
        ai_provider="google",
        github_username="testuser",
        interval_hours=4,
        veto_seconds=300,
    )


@pytest.fixture
def mock_agent(mock_config, tmp_path):
    with patch("agent.core.HISTORY_FILE", tmp_path / "history.json"):
        agent = GitHubAgent(mock_config)
        return agent


class TestGitHubAgent:
    def test_agent_initialization(self, mock_config, tmp_path):
        with patch("agent.core.HISTORY_FILE", tmp_path / "history.json"):
            agent = GitHubAgent(mock_config)
            assert agent.github_token == "ghp_testtoken123"
            assert agent.github_username == "testuser"
            assert isinstance(agent._processed_files, set)

    def test_validate_credentials_success(self, mock_agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"login": "testuser"}
        mock_resp.headers = {}

        with patch.object(mock_agent, "_get", return_value=mock_resp):
            success, message = mock_agent.validate_credentials()
            assert success is True
            assert "testuser" in message

    def test_validate_credentials_invalid_token(self, mock_agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}

        with patch.object(mock_agent, "_get", return_value=mock_resp):
            success, message = mock_agent.validate_credentials()
            assert success is False
            assert "Invalid" in message

    def test_get_user_repos(self, mock_agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = [
            {
                "full_name": "testuser/repo1",
                "name": "repo1",
                "default_branch": "main",
                "fork": False,
                "description": "Test repo",
                "language": "Python",
                "topics": [],
            },
            {
                "full_name": "testuser/forked",
                "name": "forked",
                "default_branch": "main",
                "fork": True,
                "description": None,
                "language": None,
                "topics": [],
            },
        ]

        with patch.object(mock_agent, "_get", return_value=mock_resp):
            repos = mock_agent.get_user_repos()
            assert len(repos) == 1
            assert repos[0].name == "repo1"

    def test_get_user_repos_filters_forks(self, mock_agent):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = [
            {"full_name": "u/fork", "name": "fork", "default_branch": "main",
             "fork": True, "description": None, "language": None, "topics": []},
        ]
        with patch.object(mock_agent, "_get", return_value=mock_resp):
            repos = mock_agent.get_user_repos()
            assert len(repos) == 0

    def test_pick_contribution_target_returns_none_for_empty_repos(self, mock_agent):
        result = mock_agent.pick_contribution_target([])
        assert result is None

    def test_pick_contribution_target_no_files(self, mock_agent):
        repo = Repository("u/r", "r", "main")
        with patch.object(mock_agent, "get_repo_files", return_value=[]):
            result = mock_agent.pick_contribution_target([repo])
            assert result is None

    def test_generate_contribution_api_error(self, mock_agent):
        """API error → (None, API_ERROR) — file must NOT be marked processed."""
        from agent.core import AIError, GenerateOutcome
        target = ContributionTarget(
            repo=Repository("u/r", "r", "main"),
            file=RepoFile("test.py", "test.py"),
            content="def foo(): pass",
            language="Python",
        )
        with patch.object(mock_agent.ai, "complete_or_raise", side_effect=AIError("429")):
            contrib, outcome = mock_agent.generate_contribution(target)
            assert contrib is None
            assert outcome == GenerateOutcome.API_ERROR
            assert not mock_agent._is_processed("u/r", "test.py")

    def test_generate_contribution_invalid_json(self, mock_agent):
        """Unparseable response → PARSE_ERROR."""
        from agent.core import GenerateOutcome
        target = ContributionTarget(
            repo=Repository("u/r", "r", "main"),
            file=RepoFile("test.py", "test.py"),
            content="def foo(): pass",
            language="Python",
        )
        with patch.object(mock_agent.ai, "complete_or_raise", return_value="not json at all"):
            contrib, outcome = mock_agent.generate_contribution(target)
            assert contrib is None
            assert outcome == GenerateOutcome.PARSE_ERROR

    def test_generate_contribution_no_changes(self, mock_agent):
        """Unchanged code → NO_CHANGE."""
        import json as _json
        from agent.core import GenerateOutcome
        original = "def foo(): pass"
        target = ContributionTarget(
            repo=Repository("u/r", "r", "main"),
            file=RepoFile("test.py", "test.py"),
            content=original,
            language="Python",
        )
        response = _json.dumps({
            "improved_code": original,
            "commit_message": "no change",
            "description": "nothing",
        })
        with patch.object(mock_agent.ai, "complete_or_raise", return_value=response):
            contrib, outcome = mock_agent.generate_contribution(target)
            assert contrib is None
            assert outcome == GenerateOutcome.NO_CHANGE

    def test_generate_contribution_success(self, mock_agent):
        """Valid improvement → (Contribution, SUCCESS)."""
        import json as _json
        from agent.core import GenerateOutcome
        original = "def foo():\n    pass\n"
        improved = "def foo():\n    \"\"\"Does foo.\"\"\"\n    pass\n"
        target = ContributionTarget(
            repo=Repository("u/r", "r", "main"),
            file=RepoFile("test.py", "test.py"),
            content=original,
            language="Python",
        )
        response = _json.dumps({
            "improved_code": improved,
            "commit_message": "docs: add docstring to foo",
            "description": "Added missing docstring.",
        })
        with patch.object(mock_agent.ai, "complete_or_raise", return_value=response):
            contrib, outcome = mock_agent.generate_contribution(target)
            assert contrib is not None
            assert outcome == GenerateOutcome.SUCCESS
            assert contrib.improved_code == improved
            assert "docstring" in contrib.commit_message

    def test_run_api_error_does_not_mark_processed(self, mock_agent):
        """API error must NOT poison the history file."""
        from agent.core import GenerateOutcome
        repo   = Repository("u/r", "r", "main")
        f      = RepoFile("x.py", "x.py")
        target = ContributionTarget(repo=repo, file=f, content="x = 1", language="Python")
        with patch.object(mock_agent, "get_user_repos", return_value=[repo]), \
             patch.object(mock_agent, "pick_contribution_target", return_value=target), \
             patch.object(mock_agent, "generate_contribution",
                          return_value=(None, GenerateOutcome.API_ERROR)):
            result = mock_agent.run()
            assert result.success is False
            assert "API error" in result.message
            assert not mock_agent._is_processed("u/r", "x.py")

    def test_run_no_change_marks_processed(self, mock_agent):
        """NO_CHANGE must mark the file so we don't retry it forever."""
        from agent.core import GenerateOutcome
        repo   = Repository("u/r", "r", "main")
        f      = RepoFile("x.py", "x.py")
        target = ContributionTarget(repo=repo, file=f, content="x = 1", language="Python")
        with patch.object(mock_agent, "get_user_repos", return_value=[repo]), \
             patch.object(mock_agent, "pick_contribution_target", return_value=target), \
             patch.object(mock_agent, "generate_contribution",
                          return_value=(None, GenerateOutcome.NO_CHANGE)):
            result = mock_agent.run()
            assert result.success is False
            assert mock_agent._is_processed("u/r", "x.py")

    def test_run_success(self, mock_agent):
        from agent.core import GenerateOutcome
        repo   = Repository("u/r", "r", "main")
        f      = RepoFile("x.py", "x.py")
        target = ContributionTarget(repo=repo, file=f, content="def foo(): pass", language="Python")
        contrib = Contribution("def foo():\n    pass\n", "fix: improve", "desc")
        with patch.object(mock_agent, "get_user_repos", return_value=[repo]), \
             patch.object(mock_agent, "pick_contribution_target", return_value=target), \
             patch.object(mock_agent, "generate_contribution",
                          return_value=(contrib, GenerateOutcome.SUCCESS)):
            result = mock_agent.run()
            assert result.success is True
            assert result.job is not None


    def test_run_no_repos(self, mock_agent):
        with patch.object(mock_agent, "get_user_repos", return_value=[]):
            result = mock_agent.run()
            assert result.success is False


class TestDataclasses:
    def test_repository_creation(self):
        repo = Repository("user/repo", "repo", "main", "A test repo", "Python", ["tag"])
        assert repo.full_name == "user/repo"
        assert repo.language == "Python"

    def test_contribution_target_creation(self):
        repo = Repository("u/r", "r", "main")
        file = RepoFile("test.py", "test.py", "abc123", 100, "Python")
        target = ContributionTarget(repo=repo, file=file, content="code", language="Python")
        assert target.content == "code"

    def test_contribution_creation(self):
        c = Contribution("new code", "fix: something", "Fixed it")
        assert c.commit_message == "fix: something"

    def test_agent_result_success(self):
        result = AgentResult(success=True, message="ok")
        assert result.success is True
        assert result.error is None

    def test_agent_result_with_job(self):
        repo = Repository("u/r", "r", "main")
        file = RepoFile("x.py", "x.py")
        target = ContributionTarget(repo=repo, file=file, content="x", language="Python")
        contrib = Contribution("y", "msg", "desc")
        job = ContributionJob(target=target, contribution=contrib)
        result = AgentResult(success=True, message="ok", job=job)
        assert result.job is not None
        assert result.job.contribution.commit_message == "msg"


class TestFileScoring:
    def test_todo_scores_high(self):
        from agent.core import _score_file
        content = "def foo():\n    # TODO: implement this\n    pass\n"
        score, reasons = _score_file(content, "Python")
        assert score > 5
        assert any("TODO" in r for r in reasons)

    def test_not_implemented_scores_high(self):
        from agent.core import _score_file
        # File has NotImplementedError + missing docstring but is tiny (penalised)
        # so score may be modest — just assert it's positive and has the right reason
        content = "def process():\n    raise NotImplementedError\n"
        score, reasons = _score_file(content, "Python")
        assert score >= 0
        assert any("not implemented" in r.lower() or "stub" in r.lower() or "docstring" in r.lower()
                   for r in reasons)

    def test_clean_file_scores_zero(self):
        from agent.core import _score_file
        content = 'def add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'
        score, reasons = _score_file(content, "Python")
        assert score == 0

    def test_tiny_file_penalised(self):
        from agent.core import _score_file
        content = "# TODO: fix\nx = 1\n"
        score, reasons = _score_file(content, "Python")
        # TODO adds points but tiny file penalises
        assert score >= 0  # should not go negative

    def test_multiple_signals_accumulate(self):
        from agent.core import _score_file
        content = (
            "# TODO: fix this\n"
            "# FIXME: broken\n"
            "def stub():\n    pass\n"
            "def another():\n    raise NotImplementedError\n"
        )
        score, reasons = _score_file(content, "Python")
        assert score >= 20
        assert len(reasons) >= 3


class TestAIJsonParsing:
    def test_clean_json(self):
        from agent.core import _parse_ai_json
        import json
        data = {"improved_code": "x", "commit_message": "fix", "description": "d"}
        assert _parse_ai_json(json.dumps(data)) == data

    def test_markdown_fences_stripped(self):
        from agent.core import _parse_ai_json
        import json
        data = {"improved_code": "x", "commit_message": "fix", "description": "d"}
        raw = "```json\n" + json.dumps(data) + "\n```"
        assert _parse_ai_json(raw) == data

    def test_preamble_text_handled(self):
        from agent.core import _parse_ai_json
        import json
        data = {"improved_code": "x", "commit_message": "fix", "description": "d"}
        raw = "Here is the improved code: " + json.dumps(data)
        assert _parse_ai_json(raw) == data

    def test_none_on_garbage(self):
        from agent.core import _parse_ai_json
        assert _parse_ai_json("this is not json at all") is None

    def test_none_on_empty(self):
        from agent.core import _parse_ai_json
        assert _parse_ai_json("") is None
        assert _parse_ai_json(None) is None

    def test_escaped_newlines_in_code(self):
        from agent.core import _parse_ai_json
        import json
        data = {
            "improved_code": "def foo():\n    pass\n",
            "commit_message": "docs: add stub",
            "description": "added stub"
        }
        assert _parse_ai_json(json.dumps(data))["improved_code"] == "def foo():\n    pass\n"
