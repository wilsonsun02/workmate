"""Document conversion utilities.

This module contains functions for converting markdown to Word documents.
"""

import json
import os
import re
from urllib.parse import urlparse
import requests
from io import BytesIO
from copy import deepcopy
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.oxml.ns import qn
from docx.enum.table import WD_ALIGN_VERTICAL, WD_ROW_HEIGHT
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT, WD_LINE_SPACING
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from dotenv import load_dotenv

load_dotenv()

from loguru import logger

W_NAMESPACE_URI = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load_template_style_from_json(template_type):
    """Load template style from TemplateCache (priority) or local JSON file (fallback)."""
    try:
        from workflow.template_cache import get_template_cache

        cache = get_template_cache()
        if cache:
            template = cache.get_template_by_type_sync(
                str(template_type), category="report"
            )
            if template:
                style = template.get("style_config")
                if style and isinstance(style, str):
                    style = json.loads(style)
                if style:
                    template_file_path = template.get("local_file_path")
                    return (
                        style.get("DOCX_STYLE", {}),
                        style.get("TABLE_STYLE", {}),
                        style.get("IMG_STYLE", {}),
                        template_file_path,
                    )
    except Exception as e:
        logger.debug("TemplateCache 获取报告模板失败，fallback 到本地文件: {}", e)

    template_dir = os.getenv("TEMPLATE_DIR", "template")
    json_path = os.path.join(template_dir, "template_style.json")
    if not os.path.exists(json_path):
        return {}, {}, {}, None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            templates = json.load(f)

        target_template = None
        for t in templates:
            if (
                str(t.get("template_type")) == str(template_type)
                or t.get("template_name") == template_type
            ):
                target_template = t
                break

        if not target_template:
            return {}, {}, {}, None

        style = target_template.get("template_style", {})
        if isinstance(style, str):
            style = json.loads(style)

        template_file_path = target_template.get("template_file_path")
        if template_file_path:
            template_file_path = os.path.join(
                template_dir, os.path.basename(template_file_path)
            )

        return (
            style.get("DOCX_STYLE", {}),
            style.get("TABLE_STYLE", {}),
            style.get("IMG_STYLE", {}),
            template_file_path,
        )
    except Exception as e:
        logger.error("Error loading template style: {}", e)
        return {}, {}, {}, None


def set_run_font(run, style_cfg):
    font_name = style_cfg.get("font_name", "微软雅黑")
    font_size = style_cfg.get("font_size", 12)
    color = tuple(style_cfg.get("color", (0, 0, 0)))
    font = run.font
    font.name = font_name
    font.size = Pt(font_size)
    font.color.rgb = RGBColor(*color)
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), font_name)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    if color:
        solid = run.font.color
        solid.rgb = RGBColor(*color)


def apply_paragraph_style(paragraph, style_cfg):
    runs = paragraph.runs if paragraph.runs else [paragraph.add_run()]
    for run in runs:
        set_run_font(run, style_cfg)

    style_name = style_cfg.get("style_name")
    if style_name:
        try:
            paragraph.style = style_name
        except (KeyError, ValueError):
            try:
                paragraph.style = paragraph.part.document.styles[style_name]
            except (KeyError, ValueError):
                pass

    align = style_cfg.get("alignment", "left")
    if align == "center":
        paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    elif align == "right":
        paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.RIGHT
    elif align == "justify":
        paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY
    else:
        paragraph.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT

    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    paragraph.paragraph_format.line_spacing = style_cfg.get("line_spacing", 1.5)
    paragraph.paragraph_format.space_before = Pt(style_cfg.get("space_before", 0))
    paragraph.paragraph_format.space_after = Pt(style_cfg.get("space_after", 0))

    if style_cfg.get("first_line_indent_chars"):
        font_size = style_cfg.get("font_size", 12)
        paragraph.paragraph_format.first_line_indent = Pt(
            font_size * style_cfg.get("first_line_indent_chars", 0)
        )
    elif "first_line_indent" in style_cfg:
        paragraph.paragraph_format.first_line_indent = Pt(
            style_cfg.get("first_line_indent", 0)
        )


def ensure_document_base_style(
    doc, style_cfg, exclude_section_indices=None, exclude_header_footer_indices=None
):
    """
    doc: Document对象
    style_cfg: 样式配置
    exclude_section_indices: 要排除的section索引列表（从0开始），这些section不会被应用边距设置
    exclude_header_footer_indices: 要排除页眉页脚设置的section索引列表（从0开始），这些section不会应用页眉页脚距离设置
    """
    try:
        normal_style = doc.styles["Normal"]
        font = normal_style.font
        font.name = style_cfg.get("font_name", "微软雅黑")
        font.size = Pt(style_cfg.get("font_size", 12))
        color = tuple(style_cfg.get("color", (0, 0, 0)))
        font.color.rgb = RGBColor(*color)
        rPr = normal_style.element.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        font_name = style_cfg.get("font_name", "微软雅黑")
        rFonts.set(qn("w:eastAsia"), font_name)
        rFonts.set(qn("w:ascii"), font_name)
        rFonts.set(qn("w:hAnsi"), font_name)
    except KeyError:
        pass
    margins_cfg = style_cfg.get("page_margins_cm")
    if isinstance(margins_cfg, dict):
        exclude_set = set(exclude_section_indices) if exclude_section_indices else set()
        exclude_hf_set = (
            set(exclude_header_footer_indices)
            if exclude_header_footer_indices
            else set()
        )
        for idx, section in enumerate(doc.sections):
            # 如果这个section在排除列表中，跳过所有边距设置
            if idx in exclude_set:
                continue
            # 应用页面边距（上下左右）
            if margins_cfg.get("top") is not None:
                section.top_margin = Cm(margins_cfg["top"])
            if margins_cfg.get("bottom") is not None:
                section.bottom_margin = Cm(margins_cfg["bottom"])
            if margins_cfg.get("left") is not None:
                section.left_margin = Cm(margins_cfg["left"])
            if margins_cfg.get("right") is not None:
                section.right_margin = Cm(margins_cfg["right"])
            # 页眉页脚距离设置：如果这个section在排除列表中，跳过
            if idx not in exclude_hf_set:
                if margins_cfg.get("header") is not None:
                    section.header_distance = Cm(margins_cfg["header"])
                if margins_cfg.get("footer") is not None:
                    section.footer_distance = Cm(margins_cfg["footer"])
            if margins_cfg.get("gutter") is not None:
                section.gutter = Cm(margins_cfg["gutter"])


def apply_table_style(table, style_cfg, doc=None):
    table.autofit = True
    try:
        table.allow_autofit = True
    except AttributeError:
        pass
    tbl_pr = table._tbl.tblPr
    if tbl_pr is None:
        tbl_pr = parse_xml(f"<w:tblPr {nsdecls('w')}></w:tblPr>")
        table._tbl.insert(0, tbl_pr)

    jc = tbl_pr.find(qn("w:jc"))
    if jc is None:
        jc = parse_xml(f"<w:jc {nsdecls('w')} w:val='center'/>")
        tbl_pr.append(jc)
    else:
        jc.set(qn("w:val"), "center")

    align_with_doc = style_cfg.get("align_with_doc", False)
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is not None:
        tbl_pr.remove(tbl_w)
    if align_with_doc:
        tbl_w = parse_xml(f"<w:tblW {nsdecls('w')} w:type='pct' w:w='5000'/>")
        tbl_pr.append(tbl_w)

    tbl_grid = table._tbl.tblGrid
    if tbl_grid is not None:
        for grid_col in list(tbl_grid.findall(qn("w:gridCol"))):
            tbl_grid.remove(grid_col)

    table_font_cfg = {
        **style_cfg,
        "font_size": style_cfg.get("font_size", 10),
    }

    for row_idx, row in enumerate(table.rows):
        row.height_rule = WD_ROW_HEIGHT.AUTO
        row.height = None
        for cell in row.cells:
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is not None:
                tc_pr.remove(tc_w)
            else:
                min_width = Pt(style_cfg.get("min_cell_width_pt", 24))
                tc_w = parse_xml(
                    f"<w:tcW {nsdecls('w')} w:type='dxa' w:w='{int(min_width.pt * 20)}'/>"
                )
                tc_pr.append(tc_w)

            p = cell.paragraphs[0]
            if not p.runs:
                p.add_run("")

            p.alignment = {
                "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
                "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
                "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
            }.get(style_cfg.get("alignment", "center"), WD_PARAGRAPH_ALIGNMENT.CENTER)

            if row_idx == 0 and "header_fill" in style_cfg:
                rgb = tuple(style_cfg["header_fill"])
            else:
                rgb = tuple(style_cfg.get("cell_fill", (255, 255, 255)))
            shading_elm = parse_xml(
                r'<w:shd {} w:fill="{:02x}{:02x}{:02x}" />'.format(nsdecls("w"), *rgb)
            )
            cell._tc.get_or_add_tcPr().append(shading_elm)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            p.paragraph_format.line_spacing = style_cfg.get("line_spacing", 1.2)
            for run in p.runs:
                set_run_font(run, table_font_cfg)

    if "border_color" in style_cfg and "border_width" in style_cfg:
        rgb = tuple(style_cfg["border_color"])
        hex_color = "%02X%02X%02X" % rgb
        width_eighth_pt = style_cfg["border_width"]
        for row in table.rows:
            for cell in row.cells:
                tc_pr = cell._tc.get_or_add_tcPr()
                borders = ["top", "left", "bottom", "right", "insideH", "insideV"]
                for border in borders:
                    border_xml = f"""
                    <w:{border} w:val="single" w:sz="{width_eighth_pt * 8}" w:color="{hex_color}" w:space="0"/>
                    """
                    node = parse_xml(
                        f"<w:tcBorders {nsdecls('w')}>{border_xml}</w:tcBorders>"
                    )
                    tc_pr.append(node)


def insert_inline_runs(paragraph, content, docx_style):
    tokens = re.split(r"(\*\*.+?\*\*|\*.+?\*|`.+?`)", content)
    added = False
    for token in tokens:
        if token == "":
            continue
        bold = False
        italic = False
        run_text = token
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            run_text = token[2:-2]
            bold = True
        elif token.startswith("*") and token.endswith("*") and len(token) > 2:
            run_text = token[1:-1]
            italic = True
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            run_text = token[1:-1]
            italic = True
        run = paragraph.add_run(run_text)
        run.bold = bold
        run.italic = italic
        set_run_font(run, docx_style)
        added = True
    if not added:
        run = paragraph.add_run("")
        set_run_font(run, docx_style)


def load_image_source(src, base_path):
    parsed = urlparse(src)
    if parsed.scheme in ("http", "https"):
        try:
            resp = requests.get(src, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            return None
        return BytesIO(resp.content)

    if not os.path.isabs(src):
        candidate = os.path.join(base_path, src)
    else:
        candidate = src
    if not os.path.exists(candidate):
        return None
    return candidate


def insert_image(doc, image_info, img_style, base_path, docx_style):
    src = image_info.get("src")
    if not src:
        return
    caption_text = image_info.get("title") or image_info.get("alt") or ""
    paragraph = doc.add_paragraph()
    alignment = img_style.get("alignment", "center")
    paragraph.alignment = {
        "center": WD_PARAGRAPH_ALIGNMENT.CENTER,
        "left": WD_PARAGRAPH_ALIGNMENT.LEFT,
        "right": WD_PARAGRAPH_ALIGNMENT.RIGHT,
        "justify": WD_PARAGRAPH_ALIGNMENT.JUSTIFY,
    }.get(alignment, WD_PARAGRAPH_ALIGNMENT.CENTER)
    paragraph.paragraph_format.space_before = Pt(img_style.get("space_before", 6))
    paragraph.paragraph_format.space_after = Pt(
        0 if caption_text else img_style.get("space_after", 6)
    )
    picture_run = paragraph.add_run()
    image_source = load_image_source(src, base_path)
    if image_source is None:
        paragraph.add_run("[图片资源不可用]")
        return
    width_cm = img_style.get("max_width_cm")
    try:
        if isinstance(image_source, BytesIO):
            image_source.seek(0)
            if width_cm:
                picture_run.add_picture(image_source, width=Cm(width_cm))
            else:
                picture_run.add_picture(image_source)
        else:
            if width_cm:
                picture_run.add_picture(image_source, width=Cm(width_cm))
            else:
                picture_run.add_picture(image_source)
    except Exception:
        paragraph.add_run("[图片插入失败]")
        return
    finally:
        if isinstance(image_source, BytesIO):
            image_source.close()

    caption_cfg = img_style.get("caption", {})
    if caption_text:
        caption_para = doc.add_paragraph(caption_text)
        apply_paragraph_style(caption_para, {**docx_style, **caption_cfg})
        caption_para.paragraph_format.space_before = Pt(
            caption_cfg.get("space_before", 2)
        )
        caption_para.paragraph_format.space_after = Pt(
            caption_cfg.get("space_after", 10)
        )


def insert_list(doc, items, typ, docx_style):
    available_styles = {style.name for style in doc.styles}
    if typ == "ulist":
        preferred_styles = ["List Bullet", "列表项目符号", "项目符号", "List Paragraph"]
    else:
        preferred_styles = ["List Number", "列表编号", "编号", "List Paragraph"]
    resolved_style = next(
        (name for name in preferred_styles if name in available_styles), None
    )

    list_style_cfg = docx_style.copy()
    list_style_cfg.pop("first_line_indent_chars", None)
    list_style_cfg.pop("style_name", None)

    for index, text in enumerate(items):
        p = doc.add_paragraph()
        if resolved_style:
            try:
                p.style = resolved_style
            except (KeyError, ValueError):
                p.style = "Normal"
        else:
            p.style = "Normal"
            prefix = "• " if typ == "ulist" else f"{index + 1}. "
            prefix_run = p.add_run(prefix)
            set_run_font(prefix_run, docx_style)
        insert_inline_runs(p, text, docx_style)
        apply_paragraph_style(p, list_style_cfg)


def parse_md(md_content):
    lines = md_content.splitlines()
    output = []
    in_code_block = False
    code_lines = []
    in_table = False
    table_lines = []
    prev_was_blank = True

    for line in lines:
        line = line.rstrip()
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lines = []
            else:
                in_code_block = False
                output.append(("code_block", "\n".join(code_lines)))
                prev_was_blank = False
                code_lines = []
            continue
        if in_code_block:
            code_lines.append(line)
            continue

        if re.match(r"\s*\|.*\|\s*$", line):
            in_table = True
            table_lines.append(line)
            continue
        elif in_table and (not re.match(r"\s*\|.*\|\s*$", line)):
            output.append(("table", table_lines))
            prev_was_blank = False
            table_lines = []
            in_table = False

        m = re.match(r"^\s*(#{1,6})\s+(.+)$", line)
        if m:
            while output and output[-1][0] == "blank":
                output.pop()
            output.append(("heading", (len(m.group(1)), m.group(2).strip())))
            prev_was_blank = True
            continue

        if re.match(r"^\s*[-*+] (.+)$", line):
            output.append(("ulist", line.strip()[2:]))
            prev_was_blank = False
            continue

        if re.match(r"^\s*\d+\. (.+)$", line):
            output.append(("olist", line.strip().split(". ", 1)[1]))
            prev_was_blank = False
            continue

        if re.match(r"^\s*-{3,}\s*$", line):
            continue

        if line.strip() == "":
            if not prev_was_blank and output:
                output.append(("blank", None))
                prev_was_blank = True
            continue

        image_pattern = re.compile(
            r'!\[(.*?)\]\(((?:[^()]|\([^()]*\))+?)(?:\s+"(.*?)")?\)'
        )
        remaining = line
        any_image = False
        while True:
            match = image_pattern.search(remaining)
            if not match:
                break
            any_image = True
            alt_text = match.group(1).strip()
            src = match.group(2).strip()
            title = (match.group(3) or "").strip()
            before = remaining[: match.start()].strip()
            if before:
                output.append(("text", before))
            output.append(
                (
                    "image",
                    {
                        "alt": alt_text,
                        "src": src,
                        "title": title,
                    },
                )
            )
            remaining = remaining[match.end() :]
        if any_image:
            prev_was_blank = False
            trailing = remaining.strip()
            if trailing:
                output.append(("text", trailing))
            continue

        prev_was_blank = False
        output.append(("text", line.lstrip()))

    if in_table and table_lines:
        output.append(("table", table_lines))
        prev_was_blank = False
    return output


def insert_md_to_doc(
    doc, md_content, docx_style, table_style, img_style, base_path=None
):
    parsed = parse_md(md_content)
    list_buffer = []
    current_list_type = None
    last_output_type = None
    last_heading_level = None
    base_path = base_path or os.getcwd()

    for item in parsed:
        typ, content = item
        if typ in ("ulist", "olist"):
            if current_list_type is None:
                current_list_type = typ
            if typ != current_list_type:
                insert_list(doc, list_buffer, current_list_type, docx_style)
                list_buffer = [content]
                current_list_type = typ
            else:
                list_buffer.append(content)
        else:
            if list_buffer:
                insert_list(doc, list_buffer, current_list_type, docx_style)
                last_output_type = "list"
                last_heading_level = None
                list_buffer = []
                current_list_type = None

            if typ == "heading":
                level, text = content
                if (
                    level == 2
                    and any(p.text.strip() for p in doc.paragraphs)
                    and not (last_output_type == "heading" and last_heading_level == 1)
                ):
                    doc.add_page_break()
                p = doc.add_paragraph()
                run = p.add_run(text)
                run.bold = True
                style = docx_style.copy()
                style.pop("heading_styles", None)
                style.pop("first_line_indent_chars", None)
                base_font_size = docx_style.get("font_size", 12)
                default_font_size = max(base_font_size, max(12, 16 - level))
                style.update(
                    {
                        "font_size": default_font_size,
                        "space_before": 12,
                        "space_after": 6,
                        "alignment": "center" if level == 1 else "left",
                    }
                )
                heading_styles = docx_style.get("heading_styles", {})
                level_style = heading_styles.get(str(level), {})
                style.update(level_style)
                apply_paragraph_style(p, style)
                last_output_type = "heading"
                last_heading_level = level
            elif typ == "table":
                lines = content
                rows = [re.split(r"\s*\|\s*", line.strip())[1:-1] for line in lines]
                filtered_rows = []
                for row in rows:
                    if not row:
                        continue
                    if all(re.match(r"^:?-{1,}:?$", cell.strip()) for cell in row):
                        continue
                    filtered_rows.append(row)
                if not filtered_rows:
                    continue
                rows = filtered_rows
                table = doc.add_table(rows=len(rows), cols=len(rows[0]))
                for i, row in enumerate(rows):
                    for j, cell in enumerate(row):
                        target_cell = table.cell(i, j)
                        target_cell.text = ""
                        cell_paragraph = target_cell.paragraphs[0]
                        insert_inline_runs(cell_paragraph, cell.strip(), docx_style)
                apply_table_style(table, table_style, doc)
                last_output_type = "table"
                last_heading_level = None
            elif typ == "code_block":
                p = doc.add_paragraph(content)
                p.style = "Normal"
                run = p.runs[0]
                code_style = docx_style.copy()
                code_style.update({"color": (70, 80, 110), "style_name": "Normal"})
                set_run_font(run, code_style)
                run.font.highlight_color = None
                run.font.italic = True
                run.font.bold = False
                last_output_type = "code_block"
                last_heading_level = None
            elif typ == "text":
                p = doc.add_paragraph()
                p.style = "Normal"
                insert_inline_runs(p, content, docx_style)
                style = docx_style.copy()
                style.update({"first_line_indent_chars": 2, "style_name": "Normal"})
                apply_paragraph_style(p, style)
                last_output_type = "text"
                last_heading_level = None
            elif typ == "image":
                insert_image(doc, content, img_style, base_path, docx_style)
                last_output_type = "image"
                last_heading_level = None

    if list_buffer:
        insert_list(doc, list_buffer, current_list_type, docx_style)
        last_output_type = "list"
        last_heading_level = None


def find_section_indexes(doc):
    indexes = []
    cur_start = 0
    sectpr_path = f"./{{{W_NAMESPACE_URI}}}pPr/{{{W_NAMESPACE_URI}}}sectPr"
    for i, para in enumerate(doc.paragraphs):
        if para._p is not None:
            for elm in para._p.findall(sectpr_path):
                indexes.append((cur_start, i + 1))
                cur_start = i + 1
    indexes.append((cur_start, len(doc.paragraphs)))
    return indexes


def convert_md_to_docx(
    md_content, online_image_urls, local_image_paths, template_type, save_path
):
    """Convert markdown content to a Word document (.docx)."""
    # Load template style
    docx_style, table_style, img_style, template_path = load_template_style_from_json(
        template_type
    )

    if not template_path:
        return f"Error: Template type '{template_type}' not found."

    if not os.path.exists(template_path):
        return f"Error: Template file not found at '{template_path}'."

    # Append images to markdown content
    if online_image_urls:
        md_content += "\n\n"
        for url in online_image_urls:
            md_content += f"![Image]({url})\n"

    if local_image_paths:
        md_content += "\n\n"
        for path in local_image_paths:
            md_content += f"![Image]({path})\n"

    doc = Document(template_path)
    section_ranges = find_section_indexes(doc)

    if len(section_ranges) >= 3:
        para_coll = doc.paragraphs
        first_start, first_end = section_ranges[0]
        second_start, second_end = section_ranges[1]
        third_start, third_end = section_ranges[2]

        # Save footer elements
        footer_elements = []
        for idx in range(third_start, third_end):
            if idx < len(para_coll):
                para_elem = para_coll[idx]._p
                footer_elements.append(deepcopy(para_elem))

        # Remove 2nd and 3rd sections
        paras_to_remove = []
        for idx in range(third_start, third_end):
            if idx < len(para_coll):
                paras_to_remove.append(para_coll[idx]._p)
        for idx in range(second_start, second_end):
            if idx < len(para_coll):
                paras_to_remove.append(para_coll[idx]._p)

        for para_elem in paras_to_remove:
            parent = para_elem.getparent()
            if parent is not None:
                parent.remove(para_elem)

        # Insert markdown content
        base_path_for_images = os.path.dirname(os.path.abspath(template_path))

        # Apply base document style
        # Exclude first section (cover) and last section (footer) from margin changes if needed
        # But usually we want to apply style to the content section (which is the new 2nd section)
        # The original code didn't explicitly call ensure_document_base_style in the snippet,
        # but it's defined in reference code. Let's apply it.
        # Note: section indices might change after insertion, but here we are applying to existing sections
        # The middle section is where content goes.
        # Let's apply to all sections except first and last (if 3 sections)
        ensure_document_base_style(
            doc,
            docx_style,
            exclude_section_indices=[0],
            exclude_header_footer_indices=[0],
        )

        insert_md_to_doc(
            doc,
            md_content,
            docx_style,
            table_style,
            img_style,
            base_path=base_path_for_images,
        )

        # Re-insert footer elements
        body = doc.element.body
        for elem in footer_elements:
            body.append(elem)

    else:
        # If template doesn't have 3 sections, just append to end
        base_path_for_images = os.path.dirname(os.path.abspath(template_path))
        ensure_document_base_style(doc, docx_style)
        insert_md_to_doc(
            doc,
            md_content,
            docx_style,
            table_style,
            img_style,
            base_path=base_path_for_images,
        )

    # Save document
    doc.save(save_path)
    return f"Successfully converted markdown to docx at {save_path}"


def _find_chinese_font() -> str:
    """查找系统中可用的中文字体文件路径，跨平台支持 Windows / Linux / macOS。"""
    candidates = []
    if os.name == "nt":
        win_fonts = "C:/Windows/Fonts"
        candidates = [
            os.path.join(win_fonts, "simhei.ttf"),  # 黑体
            os.path.join(win_fonts, "simsun.ttc"),  # 宋体
            os.path.join(win_fonts, "msyh.ttc"),  # 微软雅黑
            os.path.join(win_fonts, "simfang.ttf"),  # 仿宋
            os.path.join(win_fonts, "simkai.ttf"),  # 楷体
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/arphic/uming.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/Library/Fonts/Arial Unicode MS.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def _register_font(font_name: str, font_path: str) -> bool:
    """向 ReportLab 和 xhtml2pdf 注册单个字体，返回是否成功。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping
    from xhtml2pdf import default as pisa_default

    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            addMapping(font_name, 0, 0, font_name)
            addMapping(font_name, 1, 0, font_name)
            addMapping(font_name, 0, 1, font_name)
            addMapping(font_name, 1, 1, font_name)
        pisa_default.DEFAULT_FONT[font_name.lower()] = font_name
        return True
    except Exception as e:
        logger.error("注册字体 {} 失败: {}", font_name, e)
        return False


def _register_chinese_fonts() -> dict:
    """
    注册黑体、仿宋等中文字体，返回字体名称映射字典。
    键为逻辑名称（heiti/fangsong/fallback），值为 CSS font-family 字符串。
    """
    if os.name != "nt":
        return {
            "heiti": "sans-serif",
            "fangsong": "sans-serif",
            "fallback": "sans-serif",
        }

    win_fonts = "C:/Windows/Fonts"
    # 字体文件映射：逻辑名 -> (CSS名称, 文件路径列表)
    font_map = {
        "heiti": ("HeiTi", ["simhei.ttf"]),
        "fangsong": ("FangSong", ["simfang.ttf"]),
        "fallback": ("FallbackCN", ["msyh.ttc", "simsun.ttc"]),
    }
    result = {}
    for key, (css_name, files) in font_map.items():
        registered = False
        for fname in files:
            fpath = os.path.join(win_fonts, fname)
            if os.path.exists(fpath) and _register_font(css_name, fpath):
                result[key] = f"'{css_name}', sans-serif"
                registered = True
                break
        if not registered:
            result[key] = "sans-serif"
    return result


def _build_heading_css(level: int, style: dict, font_map: dict) -> str:
    """根据模板中单个标题级别的配置，生成对应的 CSS 规则字符串。"""
    align_map = {
        "center": "center",
        "left": "left",
        "right": "right",
        "justify": "justify",
    }
    font_name_cn = style.get("font_name", "")
    # 黑体 -> heiti，仿宋 -> fangsong，其余用 fallback
    if "黑" in font_name_cn:
        font_family = font_map.get("heiti", "sans-serif")
    elif "仿" in font_name_cn or "宋" in font_name_cn:
        font_family = font_map.get("fangsong", "sans-serif")
    else:
        font_family = font_map.get("fallback", "sans-serif")

    font_size = style.get("font_size", 16)
    alignment = align_map.get(style.get("alignment", "left"), "left")
    space_before = style.get("space_before", 12)
    space_after = style.get("space_after", 6)

    return (
        f"h{level} {{\n"
        f"  font-family: {font_family};\n"
        f"  font-size: {font_size}pt;\n"
        f"  text-align: {alignment};\n"
        f"  margin-top: {space_before}pt;\n"
        f"  margin-bottom: {space_after}pt;\n"
        f"  word-wrap: break-word;\n"
        f"  overflow-wrap: break-word;\n"
        f"}}\n"
    )


def convert_md_to_pdf(
    md_content: str,
    online_image_urls: list[str],
    local_image_paths: list[str],
    template_type: str,
    save_path: str,
) -> str:
    """将 Markdown 内容转换为 PDF 文件。"""
    try:
        import markdown
        from xhtml2pdf import pisa

        # 1. 加载模板样式配置
        docx_style, table_style, img_style, template_path = (
            load_template_style_from_json(template_type)
        )

        # 2. 追加图片到 Markdown 内容末尾
        for url in online_image_urls or []:
            md_content += f"\n\n![Image]({url})\n"
        for path in local_image_paths or []:
            md_content += f"\n\n![Image]({path})\n"

        # 3. Markdown -> HTML
        html_content = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "codehilite", "nl2br", "sane_lists"],
        )

        # 4. 注册中文字体，获取字体名映射
        font_map = _register_chinese_fonts()

        # 5. 从模板读取正文样式参数
        body_font_name_cn = docx_style.get("font_name", "")
        if "黑" in body_font_name_cn:
            body_font = font_map.get("heiti", "sans-serif")
        elif "仿" in body_font_name_cn or "宋" in body_font_name_cn:
            body_font = font_map.get("fangsong", "sans-serif")
        else:
            body_font = font_map.get("fallback", "sans-serif")

        font_size = docx_style.get("font_size", 12)
        line_spacing = docx_style.get("line_spacing", 1.5)

        # 6. 页面边距（cm -> mm）
        margins = docx_style.get("page_margins_cm") or {}
        margin_top = (margins.get("top") or 2.54) * 10
        margin_bottom = (margins.get("bottom") or 2.54) * 10
        margin_left = (margins.get("left") or 3.18) * 10
        margin_right = (margins.get("right") or 3.18) * 10
        footer_height = 15  # 页脚区域高度 mm

        # 7. 表格样式颜色
        tbl_border = table_style.get("border_color", [0, 0, 0])
        tbl_border_hex = (
            "#{:02x}{:02x}{:02x}".format(*tbl_border)
            if len(tbl_border) == 3
            else "#000000"
        )
        tbl_header = table_style.get("header_fill", [211, 211, 211])
        tbl_header_hex = (
            "#{:02x}{:02x}{:02x}".format(*tbl_header)
            if len(tbl_header) == 3
            else "#d3d3d3"
        )

        # 8. 按模板 heading_styles 生成各级标题 CSS
        heading_styles = docx_style.get("heading_styles", {})
        heading_css = ""
        for level in range(1, 7):
            level_cfg = heading_styles.get(str(level), {})
            if not level_cfg:
                # 无配置时给默认值，字号随级别递减
                level_cfg = {
                    "font_size": max(12, 22 - (level - 1) * 2),
                    "alignment": "center" if level == 1 else "left",
                }
            heading_css += _build_heading_css(level, level_cfg, font_map)

        # 9. 组装完整 CSS（含页脚页码）
        css_string = f"""
@page {{
    size: A4;
    margin: {margin_top}mm {margin_right}mm {margin_bottom + footer_height}mm {margin_left}mm;
    @frame footer {{
        -pdf-frame-content: footer-content;
        bottom: {footer_height - 2}mm;
        margin-left: {margin_left}mm;
        margin-right: {margin_right}mm;
        height: {footer_height}mm;
    }}
}}
body {{
    font-family: {body_font};
    font-size: {font_size}pt;
    line-height: {line_spacing};
    color: #000;
    word-wrap: break-word;
    overflow-wrap: break-word;
}}
{heading_css}
p {{
    margin-top: 0;
    margin-bottom: 6pt;
    word-wrap: break-word;
    overflow-wrap: break-word;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1em;
}}
th, td {{
    border: 1px solid {tbl_border_hex};
    padding: 4pt 6pt;
    text-align: left;
    word-wrap: break-word;
    overflow-wrap: break-word;
}}
th {{
    background-color: {tbl_header_hex};
    font-weight: bold;
}}
img {{
    max-width: 100%;
    height: auto;
    display: block;
    margin: 6pt auto;
}}
pre, code {{
    font-family: monospace;
    font-size: 9pt;
    background-color: #f5f5f5;
    word-wrap: break-word;
    overflow-wrap: break-word;
}}
pre {{ padding: 6pt; margin-bottom: 6pt; }}
#footer-content {{
    text-align: center;
    font-size: 9pt;
    color: #666;
    border-top: 0.5pt solid #ccc;
    padding-top: 3pt;
}}
"""

        # 10. 组装完整 HTML，页脚使用 pdf:pagenumber / pdf:pagecount
        full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{css_string}</style>
</head>
<body>
{html_content}
<div id="footer-content">
  <pdf:pagenumber> / <pdf:pagecount>
</div>
</body>
</html>"""

        # 11. 写入 PDF 文件
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

        def _link_callback(uri, rel):
            """处理本地图片路径，将 file:/// 转换为系统路径。"""
            if uri.startswith("file:///"):
                local_path = uri[8:].replace("/", os.sep)
                if os.path.exists(local_path):
                    return local_path
            return uri

        with open(save_path, "wb") as dest_file:
            pisa_status = pisa.CreatePDF(
                full_html.encode("utf-8"),
                dest_file,
                encoding="utf-8",
                link_callback=_link_callback,
            )

        if pisa_status.err:
            raise Exception(f"xhtml2pdf 生成失败，错误码: {pisa_status.err}")

        return f"Successfully converted markdown to pdf at {save_path}"

    except Exception as e:
        import traceback

        traceback.print_exc()
        raise Exception(f"Error converting markdown to pdf: {str(e)}")
