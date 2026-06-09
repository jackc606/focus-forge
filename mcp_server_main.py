"""Console entry point for the bundled MCP server (``focusforge-mcp.exe``).

PyInstaller builds this as a separate *console* executable so the stdio transport
that MCP clients (Claude Code / Desktop) speak has real stdin/stdout pipes — a
windowed GUI exe has none. It talks to a running Focus Forge over the loopback AI
Bridge, exactly like ``python -m focusforge_mcp`` does from source.
"""
from focusforge_mcp.server import main

if __name__ == "__main__":
    main()
