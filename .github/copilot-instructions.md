# Copilot Instructions for plex-to-tautulli

## Repository Overview

**Purpose**: A Python script to convert Plex watch history from the Plex API to the Tautulli database import format. This allows importing historical viewing data into Tautulli that predates Tautulli's installation.

**Repository Type**: Single-file Python utility script (383 lines)  
**Languages**: Python 3.12  
**Key Dependencies**: requests, python-dotenv, beautifulsoup4, lxml

## Project Structure

```
/
├── plex_history_to_tautulli.py  # Main script (383 lines)
├── requirements.txt              # Python dependencies
├── readme.md                     # User documentation
├── .gitignore                    # Git ignore rules
└── docs/
    └── tautulliImport.png        # Screenshot for documentation
```

### Key Files

- **plex_history_to_tautulli.py**: The main and only source file containing all functionality
  - Classes: `TautulliUser`, `PlexUser`, `PlexDevice`, `PlexLibrary`, `PlexMedia`, `PlexHistory`
  - Main functions: `fetch_plex_*()`, `fetch_tautulli_users()`, `insert_history()`, `init_db()`
  - Entry point: `if __name__ == "__main__": init_db(); main()`

- **requirements.txt**: Contains only 2 dependencies:
  ```
  requests>=2.32.3
  python-dotenv>=1.1.0
  ```
  ⚠️ **CRITICAL BUG**: `beautifulsoup4` and `lxml` are MISSING from requirements.txt but are imported and used in the code (`from bs4 import BeautifulSoup as Soup`). This will cause import errors.

## Environment Setup

### Python Version
- **Required**: Python 3.12 (as documented in readme.md)
- **Verified**: Python 3.12.3 works correctly

### Installation Steps

**IMPORTANT**: Always follow this exact sequence:

1. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```

2. **REQUIRED**: Install missing dependencies that aren't in requirements.txt:
   ```bash
   python -m pip install beautifulsoup4 lxml
   ```
   Without this step, the script will fail with `ModuleNotFoundError: No module named 'bs4'`

3. Verify imports work:
   ```bash
   python3 -c "import plex_history_to_tautulli; print('Import successful')"
   ```

### Environment Variables

Required environment variables (via `.env` file):
```
PLEX_API_KEY=<plex_access_token>
PLEX_URL=<ip_address>
PLEX_PORT=32400
TAUTULLI_URL=<ip_address>
TAUTULLI_PORT=8181
TAUTULLI_API_KEY=<tautulli_api_key>
```

The script will fail with `KeyError` if any of these are missing.

## Running the Script

**Command**: 
```bash
python3 plex_history_to_tautulli.py
```

**Prerequisites**:
- All dependencies installed (including beautifulsoup4 and lxml)
- `.env` file configured with valid credentials
- Access to running Plex and Tautulli servers

**Output**: Creates `plex_to_tautulli.db` SQLite database file

**Expected Behavior**: The script will:
1. Initialize a SQLite database (`plex_to_tautulli.db`)
2. Fetch data from Plex and Tautulli APIs
3. Process and map history records
4. Insert records into the database
5. Print skipped entries (missing rating keys or unmapped users)

## Build, Test, and Validation

### No Build Process
This is a pure Python script with no compilation or build step required.

### Syntax Validation
```bash
python3 -m py_compile plex_history_to_tautulli.py
```
This will detect syntax errors without running the script.

### No Automated Tests
There are no unit tests, integration tests, or test frameworks in this repository. Manual testing requires:
- Live Plex server with API access
- Live Tautulli instance with API access
- Actual history data to process

### No Linting Configuration
No linting tools (flake8, pylint, black, isort, mypy) are configured or used.

### No CI/CD Pipeline
There are no GitHub Actions, CI workflows, or automated validation pipelines. All validation is manual.

## Git Configuration

### .gitignore
Ignores:
- `.env` (secrets)
- `*.db` (generated database files)
- `__pycache__/` (Python bytecode)
- `*.pyc`, `*.pyo` (Python bytecode)

Always verify that `.env` and `*.db` files are NOT committed to avoid exposing credentials or bloating the repository.

## Known Issues and Workarounds

### 1. Missing Dependencies in requirements.txt
**Issue**: `beautifulsoup4` and `lxml` are imported but not listed in requirements.txt  
**Workaround**: Always run `pip install beautifulsoup4 lxml` after installing requirements.txt  
**Fix**: Add these to requirements.txt if modifying dependencies

### 2. Limited Library Support
Only `movie` and `show` library types are supported (see lines 166-172)

### 3. Missing Media Handling
Media without `ratingKey` in Plex History API will be skipped with a printed message (see line 182)

### 4. TODO in Code
Line 180: `# TODO: Try and use medias to look this up` - indicates potential optimization for media lookup

### 5. HTTP Only
The script only supports HTTP connections (line 11 prepends `http://`), not HTTPS

## Making Changes

### Code Style
- Type hints are used extensively (e.g., `str | None`, `list[PlexMedia]`)
- Uses Python 3.10+ union syntax (`str | None` instead of `Optional[str]`)
- Docstrings are present but minimal (mostly empty `""""""` on main function)
- Class attributes are documented in `__init__` methods

### Common Change Patterns

**Adding a new data field**:
1. Update the relevant class (`PlexMedia`, `PlexHistory`, etc.)
2. Update the corresponding `fetch_*()` function to extract the field
3. Update the `insert_history()` SQL statements if storing in database

**Adding support for a new library type**:
1. Add condition in `main()` around lines 166-172
2. Create corresponding `fetch_*_media()` function
3. Update `PlexMedia` class if the media structure differs

**Changing database schema**:
1. Update `init_db()` function (lines 357-381)
2. Update `insert_history()` SQL statements (lines 274-355)
3. Update version string in `init_db()` (currently 'v2.15.2')

### Testing Changes

Since there are no automated tests:
1. Create a `.env` file with test credentials
2. Run the script and verify it completes without errors
3. Check the output database file exists
4. Manually inspect the database contents or import into Tautulli
5. Verify console output for expected skip messages

## Important Notes for Agents

1. **Trust these instructions**: Only search for additional information if these instructions are incomplete or found to be incorrect.

2. **Dependencies are incomplete**: Always remember that `beautifulsoup4` and `lxml` must be installed separately from requirements.txt.

3. **No testing infrastructure**: Changes cannot be automatically validated. Manual verification with live servers is required.

4. **Single-file architecture**: All code is in one file. Be careful with large refactorings.

5. **Environment variables are required**: The script cannot run without properly configured `.env` file.

6. **Database is deleted on each run**: `init_db()` calls `remove('plex_to_tautulli.db')` (line 358), so the database is recreated fresh each time.

7. **No error handling for API failures**: Network errors or API failures will cause unhandled exceptions. Consider this when making changes that interact with external services.

8. **Type hints use modern syntax**: Uses Python 3.10+ union syntax (`|`) rather than `typing.Optional` or `typing.Union`.
