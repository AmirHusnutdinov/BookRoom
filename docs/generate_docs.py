import zipfile
from pathlib import Path
import markdown

ROOT = Path("/build")
OUT = ROOT / "docs_site"
README = ROOT / "README.md"
ZIP_NAME = "bookroom_source.zip"

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "flask",
    "docs_site",
    "node_modules",
}

EXCLUDE_FILES = {
    ".env",
    "booking.db",
    ZIP_NAME,
    ".dockerignore",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
}


def should_skip(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def build_zip():
    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = OUT / ZIP_NAME

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if path.is_dir():
                continue
            if OUT in path.parents:
                continue
            if should_skip(path):
                continue
            zf.write(path, path.relative_to(ROOT))


def build_html():
    OUT.mkdir(parents=True, exist_ok=True)

    if README.exists():
        text = README.read_text(encoding="utf-8")
    else:
        text = "# README not found"

    body = markdown.markdown(text, extensions=["fenced_code", "tables"])

    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BookRoom Docs</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f5f7fb;
      color: #1f2937;
    }}
    .wrap {{
      max-width: 1000px;
      margin: 40px auto;
      padding: 24px;
    }}
    .card {{
      background: #fff;
      border-radius: 16px;
      padding: 32px;
      box-shadow: 0 6px 24px rgba(0,0,0,.08);
    }}
    .top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 24px;
    }}
    .btn {{
      display: inline-block;
      text-decoration: none;
      background: #2563eb;
      color: white;
      padding: 12px 18px;
      border-radius: 10px;
      font-weight: 600;
    }}
    .btn:hover {{
      background: #1d4ed8;
    }}
    pre {{
      background: #111827;
      color: #f9fafb;
      padding: 16px;
      overflow-x: auto;
      border-radius: 10px;
    }}
    code {{
      background: #eef2f7;
      padding: 2px 6px;
      border-radius: 6px;
    }}
    pre code {{
      background: transparent;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
    }}
    th, td {{
      border: 1px solid #d1d5db;
      padding: 10px;
      text-align: left;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="top">
        <div>
          <h1 style="margin:0;">BookRoom Documentation</h1>
          <p style="margin:.5rem 0 0 0;color:#6b7280;">README.md rendered as project docs</p>
        </div>
        <div>
          <a class="btn" href="/bookroom_source.zip" download>Скачать исходники (.zip)</a>
          <a class="btn" href="https://212.193.27.116" style="margin-left:8px;">Открыть приложение</a>
        </div>
      </div>
      {body}
    </div>
  </div>
</body>
</html>"""

    (OUT / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build_html()
    build_zip()
    