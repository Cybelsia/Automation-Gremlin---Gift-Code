# Path Management Rule

- Always resolve file paths from the project root with the shared `BASE_DIR` helper.
- Never hardcode relative DB paths like `db/file.sqlite` in cogs or tasks.
- Use shared path constants for every SQLite, log, and data file.
- Create directories before opening files if needed.
- Log resolved absolute paths when opening important files.
