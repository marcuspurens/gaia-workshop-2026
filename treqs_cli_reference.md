# TReqs CLI Reference

Quick reference for all `treqs` commands. Run `treqs --help` or `treqs <command> --help` for the raw help text.

> Always run `treqs` commands from the **repository root** — it looks for `ttim.yaml` in the current working directory.

---

## treqs list

Lists all treqs elements found in the repository. Scans recursively by default.

```bash
treqs list [OPTIONS] [FILENAME]...
```

Pass one or more filenames or directories to limit scanning to those paths instead of the whole tree.

| Option | Description |
|--------|-------------|
| `--type TEXT` | Filter by element type (e.g. `--type requirement`) |
| `--uid TEXT` | Show only the element with this ID |

| `--outlinks` | Show outgoing traceability links for each element |
| `--inlinks` | Show incoming traceability links for each element |
| `--followlinks` | Follow links recursively (requires `--outlinks` or `--inlinks`) |
| `--recursive` | Search subfolders recursively. Default: `true` |
| `-o, --output [table\|md\|json\|plantuml\|mermaid]` | Output format. Default: `table` |
| `-t, --template` | Go template for custom output; omit path to use built-in HTML report |
| `-n, --project-name TEXT` | Project name used in output. Defaults to current folder name |

```bash
treqs list
treqs list --type requirement --inlinks
treqs list --uid 9a8a627687f111eb9d1ec4b301c00591
treqs list requirements/
treqs list -o plantuml
treqs list -o mermaid
```

> **Note (JSON output):** `outlinks` are always populated in JSON output. `inlinks` are only populated when `--inlinks` is also passed; otherwise the field is an empty array.

> **Note (stderr):** The summary line (e.g. `treqs list: read 4 files … Found 29 elements.`) is written to **stderr**, not stdout. The JSON on stdout is valid. Avoid `2>&1` redirects when piping JSON output to a parser.

---

## treqs check

Validates all elements against `ttim.yaml`. Scans recursively by default. Exits `0` on success, `1` on any failure — safe for CI.

```bash
treqs check [OPTIONS] [FILENAME]...
```

Pass one or more filenames or directories to validate specific paths only.

| Option | Description |
|--------|-------------|
| `--ttim TEXT` | Path to ttim.yaml. Defaults to `./ttim.yaml` |
| `-v, --verbose` | Show every file being scanned and the loaded TTIM config (global flag) |
| `-o, --output [table\|md\|json]` | Output format. Default: `table` |

```bash
treqs check
treqs check --verbose
treqs check --output json
treqs check requirements/
```

**Validates:**
- Element types exist in `ttim.yaml`
- Outlink/inlink types are permitted for the element type
- All link targets resolve to an existing element
- All `required: 'true'` inlinks are satisfied
- No duplicate IDs

> **Note:** If `./ttim.yaml` cannot be loaded, `treqs check` exits `1` and scans nothing — it will print `TTIM could not be loaded at ./ttim.yaml`.

> **Note (JSON output):** On success, `findings` is `null` (not `[]`). On failure, `findings` is an array of finding objects and `success` is `false`. The `summary` field correctly states the number of failed checks.

---

## treqs generateid

Generates one or more unique IDs (UUID1 hex, 32 characters).

```bash
treqs generateid [--amount N]
```

| Option | Description |
|--------|-------------|
| `--amount INTEGER` | Number of IDs to generate. Default: `1` |

```bash
treqs generateid
treqs generateid --amount 5
```

---

## treqs createlink

Prints a `<treqs-link>` tag snippet to stdout.

```bash
treqs createlink --linktype TYPE --target UID
```

| Option | Description |
|--------|-------------|
| `--linktype TEXT` | The link type (e.g. `tests`, `addresses`). Default: `relatesto` |
| `--target TEXT` | The ID of the target element |
| `-i, --interactive` | Prompt for linktype and target if not provided via flags |

```bash
treqs createlink --linktype tests --target 9a8a627687f111eb9d1ec4b301c00591
# Output: <treqs-link type="tests" target="9a8a627687f111eb9d1ec4b301c00591" />
```

---

## treqs create

Creates one or more element scaffolds and prints them to stdout. Ready to paste into any file.

```bash
treqs create [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--type TEXT` | Element type; selects the matching template. Default: `requirement` |
| `--label TEXT` | Short description prepended to the element body |
| `--amount INTEGER` | Number of elements to generate. Default: `1` |
| `-i, --interactive` | Prompt for type and label if not provided via flags |
| `--templatefolder TEXT` | Path to a folder with custom `.md` templates |

Built-in template types: `requirement`, `userstory`, `ears`, `planguage`.

```bash
treqs create --type requirement --label "User login"
treqs create --type userstory >> requirements/user_stories.md
```

---

## treqs ws

Creates a workspace from multiple TReqs-managed projects. This allows the validation of multiple repositiores through a single ttim file. 

```bash
treqs ws [OPTIONS]
```

Running this with no options will launch an interactive wizard guiding you through the setup.

| Option | Description |
|--------|-------------|
| `-c, --config TEXT` | Path to an existing configuration. Default: `config.yaml` |
| `-p, --project TEXT` | Project name to set up (skips interactive selection) |

---

## .treqs-ignore

Excludes files and directories from scanning. Follows Unix glob syntax. Place in the repository root.

```
build/**
dist/**
.venv/**
docs/**
README.md
```

| Pattern | Matches |
|---------|---------|
| `build/**` | Everything under `build/` |
| `*.md` | All `.md` files in root only |
| `**/*.md` | All `.md` files at any depth |
| `**/README.md` | Any file named `README.md` at any depth |

> **Watch out:** TReqs scans every file in the tree, including `.git/` internals. Any file containing `<treqs-element>` tag syntax — even inside a code fence in documentation — will be parsed as a real element. Add such files to `.treqs-ignore`.
