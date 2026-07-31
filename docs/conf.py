"""Sphinx configuration for the AI Supply Chain Planning Platform docs.

Built with MyST (Markdown) rather than reStructuredText - every page in this
directory is a plain .md file. See https://myst-parser.readthedocs.io/ for
the Markdown extensions available (admonitions, definition lists, etc.).
"""

project = "AI Supply Chain Planning Platform"
copyright = "2026"
author = "Supply Chain Platform Team"
release = "1.0"

extensions = [
    "myst_parser",
    "sphinx_rtd_theme",
    "sphinx_copybutton",
]

source_suffix = {
    ".md": "markdown",
}

master_doc = "index"

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_theme_options = {
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "titles_only": False,
}

# Long code blocks (prompts, schemas) shouldn't force horizontal scroll on narrow themes.
html_css_files = []
