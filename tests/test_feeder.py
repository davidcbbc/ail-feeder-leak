from __future__ import annotations

from pathlib import Path

import pytest

from service.feeder import iter_split_lines, remove_split_manifest, split_to_manifest
from service.utils import clean_filename


def test_clean_filename_sanitizes() -> None:
    assert clean_filename("file name💾.txt") == "file-nametxt"


def test_iter_split_lines_respects_chunk_size(tmp_path: Path) -> None:
    source = tmp_path / "leak.txt"
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    chunks = list(iter_split_lines(source, chunk_size=8))
    assert chunks
    assert all(chunk.endswith(b"\n") for chunk in chunks[:-1])
    assert max(len(chunk) for chunk in chunks) <= 8


def test_split_to_manifest_and_remove(tmp_path: Path) -> None:
    source = tmp_path / "leak.txt"
    source.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    entries = split_to_manifest(source, tmp_path, chunk_size=10)
    assert entries

    manifest_file = tmp_path / "fs_manifest.csv"
    remove_split_manifest(manifest_file, "filename", entries[0][0])

    remaining = manifest_file.read_text(encoding="utf-8")
    assert entries[0][0] not in remaining


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_split_to_manifest_rejects_invalid_size(tmp_path: Path, chunk_size: int) -> None:
    source = tmp_path / "leak.txt"
    source.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    with pytest.raises(ValueError):
        split_to_manifest(source, tmp_path, chunk_size=chunk_size)
