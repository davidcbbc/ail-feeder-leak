import os
import shutil
import string
import unicodedata
from pathlib import Path

import magic
import patoolib

# Characters authorized in filenames
WHITELISTED_FILENAME_CHARS = f"-() {string.ascii_letters}{string.digits}"


def if_binary_move(file_full_path, leak_destination_path):
    mime = magic.Magic(mime=True)
    mimetype = mime.from_file(file_full_path)
    if mimetype.rsplit("/", 1)[0] == "application":
        print(f"Moving {file_full_path} to unprocessed files")
        if os.path.exists(file_full_path):
            shutil.move(file_full_path, leak_destination_path)
        return True
    return False


def clean_filename(filename):
    """
    Render a valid filename for the feeder
    """
    # Remove whitespaces
    cleaned_filename = filename.replace(" ", "-")
    # Keep only valid ascii chars
    cleaned_filename = unicodedata.normalize("NFKD", cleaned_filename).encode("ASCII", "ignore").decode()
    # Keep only whitelisted chars
    return "".join(c for c in cleaned_filename if c in WHITELISTED_FILENAME_CHARS)


def is_compressed_file_ext(filename):
    """
    Check if filename extension is in the list of allowed compressed file format
    """
    return filename.lower().endswith(patoolib.ArchiveFormats)


def get_list_of_files(leaks_dir, unprocessed_dir):
    """
    Render a list of leak files
    Uncompress compressed files, sanitize filenames, crush unprocessable files
    """
    leaks_path = Path(leaks_dir)
    unprocessed_path = Path(unprocessed_dir)
    unprocessed_path.mkdir(parents=True, exist_ok=True)

    list_of_files = sorted([f.name for f in leaks_path.iterdir() if f.is_file()])
    for cur_file in list_of_files:
        if is_compressed_file_ext(cur_file):
            cur_file_path = leaks_path / cur_file
            patoolib.extract_archive(str(cur_file_path), verbosity=0, outdir=str(leaks_path), interactive=False)
            if cur_file_path.exists():
                cur_file_path.unlink()
            continue

        if if_binary_move(str(leaks_path / cur_file), str(unprocessed_path)):
            print("Binary found and has been moved")
            continue

    list_of_directories = sorted([d for d in leaks_path.iterdir() if d.is_dir()])
    for cur_dir in list_of_directories:
        shutil.move(str(cur_dir), str(unprocessed_path))

    list_of_files = sorted([f.name for f in leaks_path.iterdir() if f.is_file()])
    for cur_file in list_of_files:
        sanitize_filename = clean_filename(cur_file)
        sanitize_filepath = leaks_path / sanitize_filename
        if sanitize_filepath != leaks_path / cur_file:
            os.rename(leaks_path / cur_file, sanitize_filepath)

    return sorted([f.name for f in leaks_path.iterdir() if f.is_file()])


if __name__ == "__main__":
    print(patoolib.ArchiveFormats)
