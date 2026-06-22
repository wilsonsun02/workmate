"""Document processing tools.

This module contains tools for reading and converting documents to Markdown.
"""

import os
from fastmcp import Context

from ..context import mcp, get_components

# Control whether Document tools are exposed
ENABLE_DOCUMENT_TOOLS = (
    os.environ.get("MCP_ENABLE_DOCUMENT_TOOLS", "true").lower() == "true"
)


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_DOCUMENT_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def parse_file_2_md(path: str, ctx: Context) -> str:
    """Read a document or image and convert it to Markdown format.

    Supported formats: .txt, .md, .pdf, .docx, .doc, .ppt, .pptx, .csv, .xls, .xlsx,
                       .jpg, .jpeg, .png, .gif, .bmp, .webp

    For images, uses qwen3-vl-plus vision model to generate structured description
    including: image_overview, detailed_text_content, data_analysis, layout_structure,
    visual_style, color_scheme, typography_details, visual_guidance.

    Args:
        path: Absolute path to the file
        ctx: MCP context

    Returns:
        Markdown content of the document or structured image description
    """
    try:
        components = get_components()
        return await components["doc_reader"].read_to_markdown(path)
    except Exception as e:
        return f"Error reading document: {str(e)}"
