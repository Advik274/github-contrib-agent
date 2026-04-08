import json
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
        github_token="ghp_test123",
        mistral_api_key="mistral_test",
        github_username="testuser",
        interval_hours=4,
        veto_seconds=300,
    )


@pytest.fixture
def mock_repo():
    return Repository(
        full_name="testuser/test-repo",
        name="test-repo",
        default_branch="main",
        description="A test repository",
        language="Python",
        topics=["python", "test"],
    )


@pytest.fixture
def mock_file():
    return RepoFile(
        name="test.py",
        path="test.py",
        sha="abc123",
        size=1000,
        language="Python",
    )


class TestGitHubAgent:
    def test_agent_initialization(self, mock_config):
        agent = GitHubAgent(mock_config)
        assert agent.github_token == "ghp_test123"
        assert agent.mistral_api_key == "mistral_test"
        assert agent.github_username == "testuser"
        assert agent._api_calls == 0

    def test_validate_credentials_success(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "testuser"}

        with patch.object(GitHubAgent, "_get", return_value=mock_response):
            agent = GitHubAgent(mock_config)
            success, message = agent.validate_credentials()

            assert success is True
            assert "testuser" in message

    def test_validate_credentials_invalid_token(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(GitHubAgent, "_get", return_value=mock_response):
            agent = GitHubAgent(mock_config)
            success, message = agent.validate_credentials()

            assert success is False
            assert "Invalid" in message

    def test_get_user_repos(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "full_name": "testuser/repo1",
                "name": "repo1",
                "default_branch": "main",
                "description": "First repo",
                "language": "Python",
                "topics": ["python"],
                "fork": False,
            },
            {
                "full_name": "testuser/repo2",
                "name": "repo2",
                "default_branch": "master",
                "description": "Second repo",
                "language": "Java",
                "topics": [],
                "fork": False,
            },
        ]

        with patch.object(GitHubAgent, "_get", return_value=mock_response):
            agent = GitHubAgent(mock_config)
            repos = agent.get_user_repos()

            assert len(repos) == 2
            assert repos[0].full_name == "testuser/repo1"
            assert repos[1].language == "Java"

    def test_get_user_repos_filters_forks(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "full_name": "testuser/owned",
                "name": "owned",
                "default_branch": "main",
                "fork": False,
            },
            {
                "full_name": "otheruser/forked",
                "name": "forked",
                "default_branch": "main",
                "fork": True,
            },
        ]

        with patch.object(GitHubAgent, "_get", return_value=mock_response):
            agent = GitHubAgent(mock_config)
            repos = agent.get_user_repos()

            assert len(repos) == 1
            assert repos[0].full_name == "testuser/owned"

    def test_pick_contribution_target_returns_none_for_empty_repos(self, mock_config):
        agent = GitHubAgent(mock_config)
        target = agent.pick_contribution_target([])
        assert target is None

    def test_pick_contribution_target_no_files(self, mock_config, mock_repo):
        with patch.object(GitHubAgent, "get_repo_files", return_value=[]):
            agent = GitHubAgent(mock_config)
            target = agent.pick_contribution_target([mock_repo])
            assert target is None

    def test_generate_contribution_handles_empty_content(
        self, mock_config, mock_repo, mock_file
    ):
        target = ContributionTarget(
            repo=mock_repo,
            file=mock_file,
            content="",
            language="Python",
        )
        agent = GitHubAgent(mock_config)
        result = agent.generate_contribution(target)
        assert result is None

    def test_generate_contribution_invalid_json(
        self, mock_config, mock_repo, mock_file
    ):
        target = ContributionTarget(
            repo=mock_repo,
            file=mock_file,
            content="test content",
            language="Python",
        )

        with patch.object(GitHubAgent, "ask_mistral", return_value="invalid json"):
            agent = GitHubAgent(mock_config)
            result = agent.generate_contribution(target)
            assert result is None

    def test_generate_contribution_no_changes(self, mock_config, mock_repo, mock_file):
        content = "def test():\n    pass"
        target = ContributionTarget(
            repo=mock_repo,
            file=mock_file,
            content=content,
            language="Python",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "improved_code": "def test():\n    pass",
                "commit_message": "No changes",
                "description": "No changes made",
            }
        )

        with patch.object(
            GitHubAgent,
            "ask_mistral",
            return_value=mock_response.choices[0].message.content,
        ):
            agent = GitHubAgent(mock_config)
            result = agent.generate_contribution(target)
            assert result is None

    def test_run_success(self, mock_config, mock_repo, mock_file):
        mock_job = ContributionJob(
            target=ContributionTarget(
                repo=mock_repo,
                file=mock_file,
                content="def test():\n    pass",
                language="Python",
            ),
            contribution=Contribution(
                improved_code="def test():\n    pass\n",
                commit_message="Improve test",
                description="Added improvement",
            ),
        )

        with patch.object(GitHubAgent, "get_user_repos", return_value=[mock_repo]):
            with patch.object(
                GitHubAgent, "pick_contribution_target", return_value=mock_job.target
            ):
                with patch.object(
                    GitHubAgent,
                    "generate_contribution",
                    return_value=mock_job.contribution,
                ):
                    agent = GitHubAgent(mock_config)
                    result = agent.run()

                    assert result.success is True
                    assert result.job is not None
                    assert result.job.contribution.commit_message == "Improve test"

    def test_run_no_repos(self, mock_config):
        with patch.object(GitHubAgent, "get_user_repos", return_value=[]):
            agent = GitHubAgent(mock_config)
            result = agent.run()

            assert result.success is False
            assert "No repos" in result.message


class TestDataclasses:
    def test_repository_creation(self):
        repo = Repository(
            full_name="user/repo",
            name="repo",
            default_branch="main",
        )
        assert repo.full_name == "user/repo"
        assert repo.topics == []

    def test_contribution_target_creation(self, mock_repo, mock_file):
        target = ContributionTarget(
            repo=mock_repo,
            file=mock_file,
            content="test",
            language="Python",
        )
        assert target.language == "Python"

    def test_contribution_creation(self):
        contrib = Contribution(
            improved_code="code",
            commit_message="fix",
            description="Fixed something",
        )
        assert contrib.commit_message == "fix"

    def test_agent_result_success(self):
        result = AgentResult(success=True, message="Done")
        assert result.success is True
        assert result.job is None

    def test_agent_result_with_job(self, mock_repo, mock_file):
        job = ContributionJob(
            target=ContributionTarget(mock_repo, mock_file, "content", "Python"),
            contribution=Contribution("code", "msg", "desc"),
        )
        result = AgentResult(success=True, message="Done", job=job)
        assert result.job is not None
