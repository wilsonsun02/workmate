"""Document reader module for MCP Filesystem.

This module provides functionality to read various document formats
and convert them to Markdown format.
"""

import base64
import csv
import os
from pathlib import Path
from typing import List

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import xlrd
except ImportError:
    xlrd = None

from .security import PathValidator


class DocumentReader:
    """Reads various document formats and converts to Markdown."""

    SUPPORTED_FORMATS = {
        ".txt",
        ".md",
        ".pdf",
        ".docx",
        ".doc",
        ".ppt",
        ".pptx",
        ".csv",
        ".xls",
        ".xlsx",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
    }

    IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    VISION_LLM_CONFIG = {
        "model": os.getenv("VISION_LLM_MODEL", "qwen3-vl-plus"),
        "temperature": 0.8,
        "top_p": 0.95,
        "extra_body": {"enable_thinking": False},
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
    }

    def __init__(self, validator: PathValidator):
        self.validator = validator

    async def read_to_markdown(self, path: str) -> str:
        """Read a document and convert to Markdown.

        Args:
            path: Absolute path to the file

        Returns:
            Markdown content of the file

        Raises:
            ValueError: If file format is not supported or file not found
            PermissionError: If access is denied
        """
        # Validate path
        try:
            resolved_path, is_allowed = await self.validator.validate_path(path)
            if not is_allowed:
                raise PermissionError(f"Access denied to path: {path}")
            path = str(resolved_path)
        except Exception as e:
            raise PermissionError(
                f"Access denied or invalid path: {path}. Error: {str(e)}"
            )

        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        ext = Path(path).suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported file format: {ext}")

        if ext in self.IMAGE_FORMATS:
            return await self._read_image(path)

        method_name = f"_read_{ext[1:]}"
        if hasattr(self, method_name):
            return await getattr(self, method_name)(path)

        if ext == ".doc":
            return await self._read_doc(path)
        elif ext == ".ppt":
            return await self._read_ppt(path)

        raise ValueError(f"No reader implemented for format: {ext}")

    async def _read_txt(self, path: str) -> str:
        """Read text file."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    async def _read_md(self, path: str) -> str:
        """Read Markdown file (same as text)."""
        return await self._read_txt(path)

    async def _read_pdf(self, path: str) -> str:
        """Read PDF file."""
        if PdfReader is None:
            return "Error: pypdf library not installed."

        try:
            reader = PdfReader(path)
            text = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text.append(f"## Page {i + 1}\n\n{page_text}")
            return "\n\n".join(text)
        except Exception as e:
            return f"Error reading PDF: {str(e)}"

    async def _read_docx(self, path: str) -> str:
        """Read Word (.docx) file."""
        if DocxDocument is None:
            return "Error: python-docx library not installed."

        try:
            doc = DocxDocument(path)
            text = []

            # Extract title if available (from core properties)
            if doc.core_properties.title:
                text.append(f"# {doc.core_properties.title}")

            for para in doc.paragraphs:
                if para.text.strip():
                    # Convert styles to markdown headers
                    if para.style.name.startswith("Heading"):
                        level = para.style.name.replace("Heading ", "")
                        try:
                            level_int = int(level)
                            prefix = "#" * min(level_int, 6)
                            text.append(f"{prefix} {para.text}")
                        except ValueError:
                            text.append(para.text)
                    elif para.style.name == "Title":
                        text.append(f"# {para.text}")
                    elif para.style.name == "Subtitle":
                        text.append(f"## {para.text}")
                    else:
                        text.append(para.text)

            return "\n\n".join(text)
        except Exception as e:
            return f"Error reading DOCX: {str(e)}"

    async def _read_doc(self, path: str) -> str:
        """Read legacy Word (.doc) file."""
        # Note: .doc support is limited in pure Python
        # We could try using antiword if installed, or just return a message
        return (
            "Error: Legacy .doc format is not fully supported in this environment. "
            "Please convert to .docx or .pdf first."
        )

    async def _read_pptx(self, path: str) -> str:
        """Read PowerPoint (.pptx) file."""
        if Presentation is None:
            return "Error: python-pptx library not installed."

        try:
            prs = Presentation(path)
            text = []

            for i, slide in enumerate(prs.slides):
                slide_text = [f"## Slide {i + 1}"]

                # Extract title
                if slide.shapes.title and slide.shapes.title.text:
                    slide_text.append(f"### {slide.shapes.title.text}")

                # Extract other text
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        # Skip title as we already added it
                        if shape == slide.shapes.title:
                            continue
                        slide_text.append(shape.text)

                text.append("\n\n".join(slide_text))

            return "\n\n---\n\n".join(text)
        except Exception as e:
            return f"Error reading PPTX: {str(e)}"

    async def _read_ppt(self, path: str) -> str:
        """Read legacy PowerPoint (.ppt) file."""
        return (
            "Error: Legacy .ppt format is not fully supported in this environment. "
            "Please convert to .pptx or .pdf first."
        )

    async def _read_csv(self, path: str) -> str:
        """Read CSV file and convert to Markdown table."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)

            if not rows:
                return "Empty CSV file."

            return self._rows_to_markdown_table(rows)
        except Exception as e:
            return f"Error reading CSV: {str(e)}"

    async def _read_xlsx(self, path: str) -> str:
        """Read Excel (.xlsx) file."""
        if openpyxl is None:
            return "Error: openpyxl library not installed."

        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                result = []

                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    rows = []
                    for row in ws.iter_rows(values_only=True):
                        # Convert None to empty string and other types to string
                        rows.append(
                            [str(cell) if cell is not None else "" for cell in row]
                        )

                    if rows:
                        result.append(f"## Sheet: {sheet_name}")
                        result.append(self._rows_to_markdown_table(rows))

                return "\n\n".join(result)
            finally:
                wb.close()
        except Exception as e:
            return f"Error reading XLSX: {str(e)}"

    async def _read_xls(self, path: str) -> str:
        """Read legacy Excel (.xls) file."""
        if xlrd is None:
            return "Error: xlrd library not installed."

        try:
            wb = xlrd.open_workbook(path)
            result = []

            for sheet in wb.sheets():
                rows = []
                for row_idx in range(sheet.nrows):
                    row = sheet.row_values(row_idx)
                    rows.append([str(cell) for cell in row])

                if rows:
                    result.append(f"## Sheet: {sheet.name}")
                    result.append(self._rows_to_markdown_table(rows))

            return "\n\n".join(result)
        except Exception as e:
            return f"Error reading XLS: {str(e)}"

    def _rows_to_markdown_table(self, rows: List[List[str]]) -> str:
        """Convert list of rows to Markdown table."""
        if not rows:
            return ""

        # Ensure all rows have same length
        max_cols = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (max_cols - len(row)) for row in rows]

        header = normalized_rows[0]
        body = normalized_rows[1:]

        # Create separator line
        separator = ["---"] * max_cols

        lines = []
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(separator) + " |")

        for row in body:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    async def _read_image(self, path: str) -> str:
        """调用 qwen3-vl-plus 视觉模型解析图片，返回结构化 JSON 描述（Markdown 格式包装）"""
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage
        except ImportError:
            return "Error: langchain_openai not installed."

        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(path).suffix.lower().lstrip(".")
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        cfg = self.VISION_LLM_CONFIG

        llm = ChatOpenAI(
            model=cfg["model"],
            temperature=cfg["temperature"],
            top_p=cfg["top_p"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            extra_body=cfg["extra_body"],
        )

        # 动态加载提示词文件
        # 计算项目根目录：mcp_filesystem/ 的父目录
        mcp_fs_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(mcp_fs_dir)
        prompt_path = os.path.join(project_root, "prompt", "IMAGE_ANALYSIS_PROMPT.md")

        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt = f.read()
        except Exception as e:
            prompt = "请详细描述这张图片的内容，包括：整体概述、详细文本内容、数据分析、布局结构、视觉风格、色彩方案、排版细节和视觉引导。"

        msg = HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/{mime};base64,{b64}"},
                },
                {"type": "text", "text": prompt},
            ]
        )

        try:
            resp = llm.invoke([msg])
            raw = resp.content.strip()
            # 提取 JSON 块（兼容模型在 ```json ... ``` 中返回的情况）
            import re as _re

            json_match = _re.search(r"\{[\s\S]*\}", raw)
            if json_match:
                import json as _json

                data = _json.loads(json_match.group())
                lines = [f"## {k}\n{v}" for k, v in data.items() if v]
                return "\n\n".join(lines)
            return raw
        except Exception as e:
            return f"Error analyzing image: {str(e)}"
