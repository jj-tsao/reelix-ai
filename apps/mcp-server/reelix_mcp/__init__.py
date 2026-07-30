"""Reelix MCP server — exposes the recommendation pipeline as MCP tools.

Keep this module import-light: ``__main__`` installs the stdio guard before
any heavy import, so nothing here may pull torch/nltk/reelix packages.
"""
