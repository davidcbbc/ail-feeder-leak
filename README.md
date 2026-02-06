# AIL LeakFeeder

AIL LeakFeeder is a helper module for the AIL Framework that automates ingesting leaked files into AIL. It watches a leaks directory, sanitizes and pre-processes files, splits large inputs into chunks, and publishes them to the AIL API.

![Ail LeakFeeder](/img/Data%20Leak%20Ingestion.png)

## Features

- Automatically discovers leak files from a configured directory.
- Sanitizes filenames and moves binary/unprocessable files to a separate folder.
- Splits large text files into chunked pieces and tracks them with a manifest.
- Pushes chunked data to AIL with source metadata and SHA-256 checksums.
- Resumes from partially processed manifests.

## Requirements

- Python 3.10+
- A running AIL instance with an API key
- System dependency for `python-magic`:
  - Debian/Ubuntu: `sudo apt-get install libmagic1`
  - Windows: `pip install python-magic-bin`

## Installation

```bash
pip3 install -U -r requirements.txt
```

If you are using a very new Python release (e.g., 3.13), make sure your packaging tools are up to date:

```bash
pip3 install -U pip setuptools wheel
```

## Configuration

The feeder uses `config.yaml` by default, and every value can be overridden via CLI flags or environment variables (see below). A minimal example:

```yaml
name: "leak-feeder"
leaks_folder: "Leaks_Folder"
out_folder: "Unprocessed_Leaks"
unprocessed_folder: "Unprocessed_files"
chunks: 500000
api_key: "YOUR_AIL_API_KEY"
ail_url: "https://ail.example.org"
uuid: "YOUR-FEEDER-UUID"
wait: 0.5
```

### Configuration options

- `name`: Feeder source name reported to AIL.
- `leaks_folder`: Folder containing new leak files to ingest.
- `out_folder`: Folder used for split files and their manifest.
- `unprocessed_folder`: Folder used for unprocessed directories.
- `chunks`: Maximum chunk size in bytes.
- `api_key`: AIL API key with import permissions.
- `ail_url`: Base URL for the AIL API (e.g., `https://ail.example.org`).
- `uuid`: Unique feeder identifier.
- `wait`: Delay between API calls (seconds).

## Usage

### Quick start

1. Place your leak files in the `leaks_folder` directory.
2. Run the feeder with your configuration:

```bash
python3 main.py --config config.yaml
```

### CLI overrides

```bash
python3 main.py \
  --name leak-feeder \
  --leaks_folder Leaks_Folder \
  --out_folder Unprocessed_Leaks \
  --unprocessed_folder Unprocessed_files \
  --chunks 500000 \
  --api_key "YOUR_AIL_API_KEY" \
  --ail_url "https://ail.example.org" \
  --uuid "YOUR-FEEDER-UUID" \
  --wait 0.5
```

### Environment variables

The `--chunks` value can be supplied using the `FEEDER_LEAKS_CHUNKS` environment variable if desired.

## Output folders

- `Leaks_Folder`: Drop new files here.
- `Unprocessed_Leaks`: Contains chunked files and `fs_manifest.csv` while processing.
- `Unprocessed_files`: Files detected as binary or unsupported; these are moved out of the ingest flow.

## Processing flow

1. The feeder scans `Leaks_Folder`, sanitizes filenames, and extracts archives.
2. Binary files are moved to `Unprocessed_files`.
3. Each text leak is split into chunks and a `fs_manifest.csv` is created.
4. Each chunk is sent to AIL and removed from the manifest on success.
5. Once the manifest is empty, the `Unprocessed_Leaks` directory is cleaned.

## Testing

Run the test suite with:

```bash
pytest -q
```

## Troubleshooting

- **Import errors for `magic`**: ensure the `libmagic` system package is installed.
- **SSL verification warnings**: the feeder disables certificate verification by default (matching prior behavior). Consider adding a trusted certificate or reverse proxy in production.
- **No files processed**: verify `Leaks_Folder` exists and contains text files, and ensure `chunks` is > 0.

## Contributing

Contributions are welcome. Please open a pull request with a clear summary and test results.
