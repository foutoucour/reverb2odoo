"""
Upload generated GPT knowledge-base files to an OpenAI vector store.

This command replaces the knowledge files in your custom GPT's vector store
with freshly generated ones.  Run ``reverb2odoo gpt-files`` first to produce
the markdown files, then run this command to push them to OpenAI.

Credentials are read from environment variables:

  OPENAI_API_KEY          – your OpenAI secret key
  OPENAI_VECTOR_STORE_ID  – the vector store that backs your custom GPT

Run with ``--list-vector-stores`` to discover available vector stores and find
the right ID, then set ``OPENAI_VECTOR_STORE_ID`` in your environment.
"""

from __future__ import annotations

from pathlib import Path

import click
from gpt_model import DEFAULT_GIBSON_FILE, DEFAULT_OTHER_FILE
from loguru import logger
from openai import OpenAI

#: Filenames managed inside the vector store (derived from the default output paths).
TARGET_FILENAMES: frozenset[str] = frozenset(
    {
        DEFAULT_GIBSON_FILE.name,
        DEFAULT_OTHER_FILE.name,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_vector_stores(client: OpenAI) -> None:
    """Print all vector stores in the account."""
    stores = list(client.vector_stores.list())
    if not stores:
        print("No vector stores found.")
        return
    print(f"\n{'ID':<30} {'Files':>8}  Name")
    print("=" * 60)
    for vs in stores:
        count = vs.file_counts.total if vs.file_counts else "?"
        print(f"  {vs.id:<28} {count:>8}  {vs.name or '(unnamed)'}")
    print()


def _find_files_to_replace(client: OpenAI, vector_store_id: str) -> list[str]:
    """Return file IDs in *vector_store_id* whose filename is one we manage.

    Iterates all files in the vector store, fetches each file's metadata to
    read the original filename, and returns the IDs that match
    :data:`TARGET_FILENAMES`.
    """
    vs_files = list(client.vector_stores.files.list(vector_store_id))
    to_replace: list[str] = []
    for vsf in vs_files:
        meta = client.files.retrieve(vsf.id)
        if meta.filename in TARGET_FILENAMES:
            logger.debug("Will replace: {} ({})", meta.filename, vsf.id)
            to_replace.append(vsf.id)
    return to_replace


def _delete_files(client: OpenAI, vector_store_id: str, file_ids: list[str]) -> None:
    """Remove *file_ids* from the vector store and delete the underlying file objects."""
    for file_id in file_ids:
        client.vector_stores.files.delete(file_id, vector_store_id=vector_store_id)
        client.files.delete(file_id)
        logger.info("Deleted: {}", file_id)


def _upload_files(client: OpenAI, vector_store_id: str, paths: list[Path]) -> None:
    """Upload each file in *paths* and attach it to *vector_store_id*.

    Uses ``upload_and_poll`` which combines the file upload, vector store
    attachment, and waits until indexing is complete before returning.
    """
    for path in paths:
        logger.info("Uploading {} …", path.name)
        with path.open("rb") as fh:
            vs_file = client.vector_stores.files.upload_and_poll(
                vector_store_id=vector_store_id,
                file=fh,
            )
        logger.success("Indexed: {} → {}", path.name, vs_file.id)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("gpt-upload")
@click.option(
    "--openai-api-key",
    envvar="OPENAI_API_KEY",
    required=True,
    help="OpenAI API key (env: OPENAI_API_KEY).",
)
@click.option(
    "--vector-store-id",
    envvar="OPENAI_VECTOR_STORE_ID",
    default=None,
    help="Vector store ID to update (env: OPENAI_VECTOR_STORE_ID).",
)
@click.option(
    "--list-vector-stores",
    "list_stores",
    is_flag=True,
    help="List all vector stores in your account and exit.",
)
@click.option(
    "--gibson-file",
    default=str(DEFAULT_GIBSON_FILE),
    show_default=True,
    help="Path to the Gibson models markdown file.",
)
@click.option(
    "--other-file",
    default=str(DEFAULT_OTHER_FILE),
    show_default=True,
    help="Path to the non-Gibson models markdown file.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without making any changes.",
)
def cli(
    openai_api_key: str,
    vector_store_id: str | None,
    list_stores: bool,
    gibson_file: str,
    other_file: str,
    dry_run: bool,
) -> None:
    """Upload GPT knowledge-base files to an OpenAI vector store.

    Finds and deletes any existing files with the same names in the vector
    store, then uploads the freshly generated ones.

    Run with --list-vector-stores first to find your vector store ID, then set
    OPENAI_VECTOR_STORE_ID in your environment (or pass --vector-store-id).
    """
    client = OpenAI(api_key=openai_api_key)

    if list_stores:
        _list_vector_stores(client)
        return

    if not vector_store_id:
        raise click.UsageError(
            "Provide --vector-store-id or set OPENAI_VECTOR_STORE_ID.\n"
            "Use --list-vector-stores to discover available stores."
        )

    paths = [Path(gibson_file), Path(other_file)]

    # Validate files exist before touching the OpenAI API.
    for path in paths:
        if not path.exists():
            raise click.UsageError(
                f"File not found: {path}\n"
                "Run 'reverb2odoo gpt-files' first to generate the knowledge-base files."
            )

    logger.info("Scanning vector store {} for existing files…", vector_store_id)
    to_delete = _find_files_to_replace(client, vector_store_id)

    if to_delete:
        logger.info("{} existing file(s) will be replaced.", len(to_delete))
    else:
        logger.info("No existing files to replace.")

    if dry_run:
        logger.info("Dry-run — would upload: {}", [p.name for p in paths])
        return

    if to_delete:
        _delete_files(client, vector_store_id, to_delete)

    _upload_files(client, vector_store_id, paths)
    logger.success("Vector store {} updated.", vector_store_id)
