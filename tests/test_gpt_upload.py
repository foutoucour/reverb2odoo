"""Tests for gpt_upload — OpenAI vector store update logic."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gpt_upload import (
    TARGET_FILENAMES,
    _delete_files,
    _find_files_to_replace,
    _list_vector_stores,
    _upload_files,
    cli,
)

# ── helpers ───────────────────────────────────────────────────────────────


def _make_client(vs_files=None, file_metas=None):
    """Return a mock OpenAI client with pre-configured responses."""
    client = MagicMock()

    # vector_stores.list()
    client.vector_stores.list.return_value = []

    # vector_stores.files.list()
    client.vector_stores.files.list.return_value = vs_files or []

    # files.retrieve() — called once per vs_file to get filename
    if file_metas is not None:
        client.files.retrieve.side_effect = file_metas
    else:
        client.files.retrieve.return_value = MagicMock(filename="other.md")

    return client


# ── TARGET_FILENAMES ──────────────────────────────────────────────────────


def test_target_filenames_contains_expected_files():
    assert "models_body_size_gibson.md" in TARGET_FILENAMES
    assert "models_body_size.md" in TARGET_FILENAMES
    assert len(TARGET_FILENAMES) == 2


# ── _list_vector_stores ───────────────────────────────────────────────────


class TestListVectorStores:
    def test_prints_stores(self, capsys):
        client = MagicMock()
        vs1 = MagicMock(id="vs_abc", name="My GPT", file_counts=MagicMock(total=2))
        vs2 = MagicMock(id="vs_xyz", name="Other", file_counts=MagicMock(total=0))
        client.vector_stores.list.return_value = [vs1, vs2]

        _list_vector_stores(client)

        out = capsys.readouterr().out
        assert "vs_abc" in out
        assert "My GPT" in out
        assert "vs_xyz" in out

    def test_empty_account(self, capsys):
        client = MagicMock()
        client.vector_stores.list.return_value = []

        _list_vector_stores(client)

        assert "No vector stores found" in capsys.readouterr().out

    def test_unnamed_store(self, capsys):
        client = MagicMock()
        vs = MagicMock(id="vs_anon", name=None, file_counts=MagicMock(total=1))
        client.vector_stores.list.return_value = [vs]

        _list_vector_stores(client)

        assert "(unnamed)" in capsys.readouterr().out


# ── _find_files_to_replace ────────────────────────────────────────────────


class TestFindFilesToReplace:
    def _vs_file(self, file_id):
        vsf = MagicMock()
        vsf.id = file_id
        return vsf

    def test_returns_ids_for_matching_filenames(self):
        client = MagicMock()
        client.vector_stores.files.list.return_value = [
            self._vs_file("file-111"),
            self._vs_file("file-222"),
        ]
        client.files.retrieve.side_effect = [
            MagicMock(filename="models_body_size_gibson.md"),
            MagicMock(filename="models_body_size.md"),
        ]

        result = _find_files_to_replace(client, "vs_abc")

        assert result == ["file-111", "file-222"]

    def test_skips_unrelated_files(self):
        client = MagicMock()
        client.vector_stores.files.list.return_value = [
            self._vs_file("file-333"),
            self._vs_file("file-444"),
        ]
        client.files.retrieve.side_effect = [
            MagicMock(filename="unrelated.pdf"),
            MagicMock(filename="models_body_size_gibson.md"),
        ]

        result = _find_files_to_replace(client, "vs_abc")

        assert result == ["file-444"]

    def test_empty_vector_store(self):
        client = MagicMock()
        client.vector_stores.files.list.return_value = []

        result = _find_files_to_replace(client, "vs_abc")

        assert result == []
        client.files.retrieve.assert_not_called()

    def test_no_matching_files(self):
        client = MagicMock()
        client.vector_stores.files.list.return_value = [self._vs_file("file-999")]
        client.files.retrieve.return_value = MagicMock(filename="something_else.txt")

        result = _find_files_to_replace(client, "vs_abc")

        assert result == []


# ── _delete_files ─────────────────────────────────────────────────────────


class TestDeleteFiles:
    def test_deletes_from_vector_store_and_file_storage(self):
        client = MagicMock()

        _delete_files(client, "vs_abc", ["file-111", "file-222"])

        assert client.vector_stores.files.delete.call_count == 2
        assert client.files.delete.call_count == 2
        client.vector_stores.files.delete.assert_any_call("file-111", vector_store_id="vs_abc")
        client.vector_stores.files.delete.assert_any_call("file-222", vector_store_id="vs_abc")
        client.files.delete.assert_any_call("file-111")
        client.files.delete.assert_any_call("file-222")

    def test_empty_list_makes_no_calls(self):
        client = MagicMock()

        _delete_files(client, "vs_abc", [])

        client.vector_stores.files.delete.assert_not_called()
        client.files.delete.assert_not_called()

    def test_vector_store_deleted_before_file_object(self):
        """Ensures the vector store link is removed before the file object."""
        client = MagicMock()
        call_order = []
        client.vector_stores.files.delete.side_effect = lambda *a, **kw: call_order.append("vs")
        client.files.delete.side_effect = lambda *a, **kw: call_order.append("file")

        _delete_files(client, "vs_abc", ["file-111"])

        assert call_order == ["vs", "file"]


# ── _upload_files ─────────────────────────────────────────────────────────


class TestUploadFiles:
    def test_uploads_each_path(self, tmp_path):
        gibson = tmp_path / "models_body_size_gibson.md"
        other = tmp_path / "models_body_size.md"
        gibson.write_text("# Gibson", encoding="utf-8")
        other.write_text("# Other", encoding="utf-8")

        client = MagicMock()
        uploaded = MagicMock(id="file-new-111")
        client.vector_stores.files.upload_and_poll.return_value = uploaded

        _upload_files(client, "vs_abc", [gibson, other])

        assert client.vector_stores.files.upload_and_poll.call_count == 2
        calls = client.vector_stores.files.upload_and_poll.call_args_list
        assert all(c.kwargs["vector_store_id"] == "vs_abc" for c in calls)

    def test_empty_paths_makes_no_calls(self):
        client = MagicMock()
        _upload_files(client, "vs_abc", [])
        client.vector_stores.files.upload_and_poll.assert_not_called()


# ── CLI ───────────────────────────────────────────────────────────────────


class TestGptUploadCli:
    runner = CliRunner()

    def _base_args(self, vector_store_id="vs_test"):
        return ["--openai-api-key", "sk-test", "--vector-store-id", vector_store_id]

    def test_help(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--list-vector-stores" in result.output
        assert "--vector-store-id" in result.output
        assert "--dry-run" in result.output

    def test_missing_vector_store_id_raises_error(self, tmp_path):
        result = self.runner.invoke(cli, ["--openai-api-key", "sk-test"])
        assert result.exit_code != 0
        assert "OPENAI_VECTOR_STORE_ID" in result.output

    def test_list_vector_stores_flag(self):
        mock_client = MagicMock()
        mock_client.vector_stores.list.return_value = []

        with patch("gpt_upload.OpenAI", return_value=mock_client):
            result = self.runner.invoke(
                cli, ["--openai-api-key", "sk-test", "--list-vector-stores"]
            )

        assert result.exit_code == 0
        mock_client.vector_stores.list.assert_called_once()

    def test_missing_file_raises_error(self, tmp_path):
        mock_client = MagicMock()

        with patch("gpt_upload.OpenAI", return_value=mock_client):
            result = self.runner.invoke(
                cli,
                self._base_args()
                + [
                    "--gibson-file",
                    str(tmp_path / "missing_gibson.md"),
                    "--other-file",
                    str(tmp_path / "missing_other.md"),
                ],
            )

        assert result.exit_code != 0
        assert "File not found" in result.output

    def test_dry_run_skips_delete_and_upload(self, tmp_path):
        gibson = tmp_path / "models_body_size_gibson.md"
        other = tmp_path / "models_body_size.md"
        gibson.write_text("# Gibson", encoding="utf-8")
        other.write_text("# Other", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.vector_stores.files.list.return_value = []

        with patch("gpt_upload.OpenAI", return_value=mock_client):
            result = self.runner.invoke(
                cli,
                self._base_args()
                + [
                    "--gibson-file",
                    str(gibson),
                    "--other-file",
                    str(other),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_client.files.delete.assert_not_called()
        mock_client.vector_stores.files.upload_and_poll.assert_not_called()

    def test_full_flow_replaces_and_uploads(self, tmp_path):
        gibson = tmp_path / "models_body_size_gibson.md"
        other = tmp_path / "models_body_size.md"
        gibson.write_text("# Gibson", encoding="utf-8")
        other.write_text("# Other", encoding="utf-8")

        old_vs_file = MagicMock(id="file-old-111")
        mock_client = MagicMock()
        mock_client.vector_stores.files.list.return_value = [old_vs_file]
        mock_client.files.retrieve.return_value = MagicMock(filename="models_body_size_gibson.md")
        mock_client.vector_stores.files.upload_and_poll.return_value = MagicMock(id="file-new-222")

        with patch("gpt_upload.OpenAI", return_value=mock_client):
            result = self.runner.invoke(
                cli,
                self._base_args() + ["--gibson-file", str(gibson), "--other-file", str(other)],
            )

        assert result.exit_code == 0, result.output
        # Old file removed from vector store and deleted
        mock_client.vector_stores.files.delete.assert_called_once_with(
            "file-old-111", vector_store_id="vs_test"
        )
        mock_client.files.delete.assert_called_once_with("file-old-111")
        # Both new files uploaded
        assert mock_client.vector_stores.files.upload_and_poll.call_count == 2

    def test_no_existing_files_skips_delete(self, tmp_path):
        gibson = tmp_path / "models_body_size_gibson.md"
        other = tmp_path / "models_body_size.md"
        gibson.write_text("# Gibson", encoding="utf-8")
        other.write_text("# Other", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.vector_stores.files.list.return_value = []
        mock_client.vector_stores.files.upload_and_poll.return_value = MagicMock(id="file-new-333")

        with patch("gpt_upload.OpenAI", return_value=mock_client):
            result = self.runner.invoke(
                cli,
                self._base_args() + ["--gibson-file", str(gibson), "--other-file", str(other)],
            )

        assert result.exit_code == 0, result.output
        mock_client.files.delete.assert_not_called()
        assert mock_client.vector_stores.files.upload_and_poll.call_count == 2
