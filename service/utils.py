from __future__ import annotations

import os
import shutil
import string
import unicodedata
from pathlib import Path
from typing import Iterable

# Characters authorized in filenames
WHITELISTED_FILENAME_CHARS = f"-() {string.ascii_letters}{string.digits}"


def if_binary_move(file_full_path: str | os.PathLike, leak_destination_path: str | os.PathLike) -> bool:
    file_path = Path(file_full_path)
    import magic

    mime = magic.Magic(mime=True)
    mimetype = mime.from_file(str(file_path))
    if mimetype.rsplit("/", 1)[0] == "application":
        print(f"Moving {file_path} to unprocessed files")
        if file_path.exists():
            shutil.move(str(file_path), str(leak_destination_path))
        return True
    return False


def clean_filename(filename: str) -> str:
    """
    Render a valid filename for the feeder
    """
    # Remove whitespaces
    cleaned_filename = filename.replace(" ", "-")
    # Keep only valid ascii chars
    cleaned_filename = unicodedata.normalize("NFKD", cleaned_filename).encode("ASCII", "ignore").decode()
    # Keep only whitelisted chars
    return "".join(c for c in cleaned_filename if c in WHITELISTED_FILENAME_CHARS)


def is_compressed_file_ext(filename: str) -> bool:
    """
    Check if filename extension is in the list of allowed compressed file format
    """
    import patoolib

    return filename.lower().endswith(patoolib.ArchiveFormats)


def _list_files(directory: Path) -> Iterable[Path]:
    return sorted(path for path in directory.iterdir() if path.is_file())


def get_list_of_files(leaks_dir: str | os.PathLike, unprocessed_dir: str | os.PathLike) -> list[str]:
    """
    Render a list of leak files
    Uncompress compressed files, sanitize filenames, crush unprocessable files 
    """
    leaks_path = Path(leaks_dir)
    unprocessed_path = Path(unprocessed_dir)
    #  Search for compressed files and extract them in Leaks Folder
    list_of_files = _list_files(leaks_path)
    print([file.name for file in list_of_files])
    for cur_file in list_of_files:
        leak_destination_path = unprocessed_path.parent / "Unprocessed_files"
        if is_compressed_file_ext(cur_file.name):
            import patoolib

            patoolib.extract_archive(str(cur_file), verbosity=0, outdir=str(leaks_path), interactive=False)
            if cur_file.exists():
                cur_file.unlink()
            continue
            # TODO Keep trace of original compressed name ?
        if if_binary_move(cur_file, leak_destination_path):
            print("Binary found and has been moved")
    # Move directories in Unprocessed Folder
    # Only keep flatten uncompressed files
    # TODO manage structured uncompressed files
    list_of_directories = sorted(path for path in leaks_path.iterdir() if path.is_dir())
    for cur_dir in list_of_directories:
        shutil.move(str(cur_dir), str(unprocessed_path))

    # Sanitize filenames
    list_of_files = _list_files(leaks_path)
    for cur_file in list_of_files:
        sanitize_filename = clean_filename(cur_file.name)
        print(f"sanitize_filename: {sanitize_filename}")
        sanitize_filepath = leaks_path / sanitize_filename
        print(f"sanitize_filepath: {sanitize_filepath}")
        cur_file.rename(sanitize_filepath)

    # Get and return reluctant leak files to process
    list_of_files = _list_files(leaks_path)
    return [file.name for file in list_of_files]


if __name__ == "__main__":
    # zip gunzip, rar, tar
    import patoolib

    print(patoolib.ArchiveFormats)
