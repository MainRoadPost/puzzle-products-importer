# Puzzle Products Importer

## About the tool

**puzzle-products-importer** is a small application that allows uploading products into a Puzzle project from a CSV spreadsheet.

This tool is useful for populating products in large projects based on budget/estimate data.

## Usage

To launch the application run the following command in a terminal:

```
puzzle-products-importer
```

This command opens a graphical application with the following UI:

![Interface](/images/puzzle-products-importer_ui.png)

Select a domain and log in using your studio account credentials.

Once logged in you'll be able to select an available project. Choose the project you want to import into.

Next, choose a CSV file to import. You can create this file in Excel or any spreadsheet editor using your budget/estimate data. The CSV must follow the template below:

| path             | code  | awarded | due        | picture          | deliverable | status  | tags      |
|------------------|-------|---------|------------|------------------|-------------|---------|-----------|
| episode01/seq01  | 0010  | 10      | 2025-11-26 | images/0010.png  | TRUE        | ACTIVE  | tag1 tag2 |
| episode01/seq01  | 0020  |         |            |                  |             |         |           |

-- The `path` column should contain the hierarchy of nested product groups for the product separated by slashes (`/`).
-- `code` is the product name/id that will be used on the server.
-- `awarded` is the number of allocated resources for the shot in person-hours.
-- `due` is the product deadline in format YYYY-MM-DD.
-- `picture` is the path to the product preview image (should be 256×256 pixels square).
-- `deliverable` indicates whether the product is delivered to the client; values can be `TRUE` or `FALSE`.
-- `status` is the product status; allowed values are `ACTIVE`, `COMPLETED`, or `CANCELED`.
-- `tags` are space-separated product tags.

Only first two columns are required to be filled, others can be left empty.

Dry run
-------

The application supports a "Dry run" mode which is useful for testing CSV parsing and preparing GraphQL mutations without actually creating or updating records on the server. When Dry run is enabled the app will prepare and log `ProductAdd` and `ProductChange` payloads but will not send them to the API.

## Installing the application

The `uv` tool is used for dependency management and building. Make sure it's installed on your system.

**Steps to run locally:**

1. Clone the repository to a local folder using `git clone`.

2. Install project dependencies using `uv`:

   ```bash
   uv sync
   ```

3. **Important:** Before first run generate the GraphQL client code files with `ariadne-codegen` command:

   ```bash
   uv run ariadne-codegen
   ```

   This command creates/updates the `puzzle` module using `schema.graphql` and `queries.graphql`.

4. Run the application to verify it starts correctly:

   ```bash
   uv run puzzle-products-importer
   ```

5. Optionally install the app into your studio toolset using the helper script:

   ```bash
   mrp-install.sh
   ```

## Tests

To run the project tests, use `uv` and Python's unittest test runner:

```bash
uv run python -m unittest discover -v
```

## Changing the generated client

The GraphQL client for Puzzle is generated into the `puzzle` module by `ariadne-codegen`. Do not edit the generated client code by hand.

To update the client after schema or query changes:

1. Make sure `schema.graphql` contains an up-to-date schema.
2. Update `queries.graphql` with the required queries/mutations.
3. Regenerate the client:

   ```bash
   uv run ariadne-codegen
   ```

**Note:** Running `ariadne-codegen` is required before the first run and after any changes to schema or query files.

## Updating the schema

To update the schema you need the `cynic-cli` tool (requires [Rust](https://www.rust-lang.org/tools/install) to be installed):

```shell
cargo install --git https://github.com/obmarg/cynic.git cynic-cli
```

After installing `cynic-cli`, run `./get-schema.sh > schema.graphql` in the repository root to authenticate against the Puzzle server and download the current GraphQL schema.

The script expects the following environment variables to be set in `.env`:
- `PUZZLE_API` — GraphQL endpoint URL of the Puzzle server.
- `PUZZLE_USER_DOMAIN` — studio domain (leave blank if not used).
- `PUZZLE_USERNAME` — username to authenticate with.
- `PUZZLE_PASSWORD` — password for the user.

Optionally, set `LOG_LEVEL` (e.g., `LOG_LEVEL=INFO`) to control logging verbosity.

See `example.env` for an example `.env` file.
