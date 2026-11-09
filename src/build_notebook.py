"""Turn notebooks/analysis.py ('# %%' cells) into notebooks/analysis.ipynb.
Execute it afterwards with:
    jupyter nbconvert --to notebook --execute --inplace notebooks/analysis.ipynb
"""
from pathlib import Path
import re
import nbformat

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "notebooks" / "analysis.py").read_text(encoding="utf-8")
cells = []
for block in re.split(r"^# %%", src, flags=re.M)[1:]:
    header, _, body = block.partition("\n")
    body = body.strip("\n")
    if header.strip() == "[markdown]":
        text = "\n".join(line[2:] if line.startswith("# ") else line.lstrip("#") for line in body.splitlines())
        cells.append(nbformat.v4.new_markdown_cell(text))
    else:
        cells.append(nbformat.v4.new_code_cell(body))
nb = nbformat.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}})
nbformat.write(nb, ROOT / "notebooks" / "analysis.ipynb")
print(f"{len(cells)} cells -> notebooks/analysis.ipynb")
