"""Media generation tools.

This module contains tools for generating and processing images, audio, video, and PPT files.
"""

import os
import sys
import json
from fastmcp import Context
from ..context import mcp
from ..doc_converter import convert_md_to_docx, convert_md_to_pdf
from ..paths import app_base_dir

from loguru import logger

_ROOT_DIR = app_base_dir()
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

ENABLE_MEDIA_TOOLS = os.environ.get("MCP_ENABLE_MEDIA_TOOLS", "true").lower() == "true"


def register_tool(*args, **kwargs):
    """条件注册装饰器，由环境变量控制是否暴露工具"""
    if ENABLE_MEDIA_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


def _get_video_manager():
    from workflow.media import VideoManager

    return VideoManager()


def _get_audio_manager():
    from workflow.media import AudioManager

    return AudioManager()


def _get_image_manager():
    from workflow.media import ImageManager

    return ImageManager()


def _get_ppt_image_manager():
    from workflow.media import PPTImageManager

    return PPTImageManager()


def _get_ppt_manager():
    from workflow.media import PPTManager

    return PPTManager()


# ─────────────────────────── 视频工具 ───────────────────────────


@register_tool()
async def submit_video_task(
    prompt: str,
    first_frame_image: str = None,
    last_frame_image: str = None,
    duration: int = 6,
    ctx: Context = None,
) -> str:
    """Submit a video generation task to MiniMax-Hailuo-2.3-Fast and return the task ID immediately.

    Video generation is asynchronous and typically takes several minutes. Use
    query_video_task to poll the status and download the result when ready.

    Args:
        prompt: Text description of the video content.
        first_frame_image: Optional URL of the first frame image for image-to-video.
        last_frame_image: Optional URL of the last frame image (first+last frame mode).
        duration: Video duration in seconds, 6 or 10. Default is 6.
        ctx: MCP context.

    Returns:
        The task_id string on success, or an error message.
    """
    try:
        manager = _get_video_manager()
        task_id = manager.submit_video_task(
            prompt, first_frame_image, last_frame_image, duration
        )
        return task_id
    except Exception as e:
        return f"Error submitting video task: {str(e)}"


@register_tool()
async def query_video_task(
    task_id: str, save_path: str = None, ctx: Context = None
) -> str:
    """Query the status of a video generation task and optionally download the result.

    Call this tool after submit_video_task. When status is "Success" and save_path
    is provided, the video is automatically downloaded to the local path.

    Args:
        task_id: The task ID returned by submit_video_task.
        save_path: Optional local path to save the video (.mp4) when the task succeeds.
        ctx: MCP context.

    Returns:
        JSON string with keys: task_id, status (Preparing/Processing/Success/Fail/Error),
        file_id, download_url, local_path (if downloaded), error (if failed).
    """
    try:
        manager = _get_video_manager()
        result = manager.query_video_task(task_id, save_path)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error querying video task: {str(e)}"


@register_tool()
async def add_subtitle_and_audio(
    video_path: str, audio_path: str, subtitle: str, save_path: str, ctx: Context = None
) -> str:
    """Composite a video with an audio track and a subtitle overlay.

    The audio is automatically speed-adjusted or padded with silence to match
    the video duration. The subtitle is rendered at the bottom of the frame.

    Args:
        video_path: Local path of the source video file.
        audio_path: Local path of the audio file to overlay.
        subtitle: Subtitle text to render on the video.
        save_path: Local path to save the composited video.
        ctx: MCP context.

    Returns:
        The local path of the composited video, or an error message.
    """
    try:
        manager = _get_video_manager()
        return manager.add_subtitle_and_audio(
            video_path, audio_path, subtitle, save_path
        )
    except Exception as e:
        return f"Error compositing video: {str(e)}"


@register_tool()
async def merge_videos(
    video_paths: list[str], save_path: str, ctx: Context = None
) -> str:
    """Merge multiple video clips into a single video using FFmpeg.

    Args:
        video_paths: Ordered list of local video file paths to concatenate.
        save_path: Local path to save the merged video.
        ctx: MCP context.

    Returns:
        The local path of the merged video, or an error message.
    """
    try:
        manager = _get_video_manager()
        return manager.merge_videos(video_paths, save_path)
    except Exception as e:
        return f"Error merging videos: {str(e)}"


# ─────────────────────────── 音频工具 ───────────────────────────


@register_tool()
async def generate_audio(
    text: str, save_path: str, voice_id: str = "audiobook_male_1", ctx: Context = None
) -> str:
    """Convert text to speech (TTS) using MiniMax speech-2.6-turbo model.

    Args:
        text: The text content to synthesize.
        save_path: Local path to save the generated audio file (.mp3).
        voice_id: Voice ID to use, default is "audiobook_male_1".
        ctx: MCP context.

    Returns:
        The local path of the saved audio file, or an error message.
    """
    try:
        manager = _get_audio_manager()
        return manager.generate_audio(text, save_path, voice_id)
    except Exception as e:
        return f"Error generating audio: {str(e)}"


@register_tool()
async def extract_audio_text(audio_path_or_url: str, ctx: Context = None) -> str:
    """Transcribe audio to text with timestamps using DashScope ASR.

    Uses qwen3-asr-flash-filetrans model. Supports both local file paths
    and public URLs.

    Args:
        audio_path_or_url: Local path or publicly accessible URL of the audio file.
        ctx: MCP context.

    Returns:
        JSON string of a list of segments, each with keys: text, begin_time,
        end_time, emotion. Returns an error message string on failure.
    """
    try:
        manager = _get_audio_manager()
        result = manager.extract_audio_text(audio_path_or_url)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error extracting audio text: {str(e)}"


# ─────────────────────────── 图片工具（通用/视频场景） ───────────────────────────


@register_tool()
async def generate_image(
    prompt: str, save_path: str, reference_image_path: str = None, ctx: Context = None
) -> str:
    """Generate an image from a text prompt using Gemini or Wan(wan2.7) model.

    The model is determined by IMAGE_PROVIDER env var (gemini/wan, default gemini).
    Suitable for generating video frame images and general-purpose images.
    Optionally accepts a reference image to guide the visual style.

    Args:
        prompt: Text description of the image to generate.
        save_path: Local path to save the generated image.
        reference_image_path: Optional local path or URL of a reference image.
        ctx: MCP context.

    Returns:
        The local path of the saved image, or an error message.
    """
    try:
        manager = _get_image_manager()
        return manager.generate_image(prompt, save_path, reference_image_path)
    except Exception as e:
        return f"Error generating image: {str(e)}"


@register_tool()
async def modify_image(
    image_path: str, requirement: str, save_path: str, ctx: Context = None
) -> str:
    """Modify an existing image according to a text requirement using Gemini or Wan model.

    The model is determined by IMAGE_PROVIDER env var (gemini/wan, default gemini).
    The original image style, color scheme, and layout are preserved.

    Args:
        image_path: Local path or URL of the source image to modify.
        requirement: Text description of the desired modifications.
        save_path: Local path to save the modified image.
        ctx: MCP context.

    Returns:
        The local path of the modified image, or an error message.
    """
    try:
        manager = _get_image_manager()
        return manager.modify_image(image_path, requirement, save_path)
    except Exception as e:
        return f"Error modifying image: {str(e)}"


# ─────────────────────────── 模板查询工具 ───────────────────────────


@register_tool()
async def list_templates(category: str = "", ctx: Context = None) -> str:
    """List available templates managed by the admin panel.

    Call this tool BEFORE generate_ppt_image or md_2_word/md_2_pdf to discover
    the valid template_type values. Templates are dynamically managed via the
    admin panel and may change at any time.

    Args:
        category: Template category filter. Use "image" for PPT/image templates,
                  "report" for Word/PDF report templates, "video" for video templates.
                  Empty string returns all categories.
        ctx: MCP context.

    Returns:
        JSON string of template list. Each item contains:
        template_key, template_name, template_type (the value to pass as
        template_type parameter), category_key, category_name, description.
    """
    try:
        from workflow.template_cache import get_template_cache

        cache = get_template_cache()
        if not cache:
            return json.dumps([], ensure_ascii=False)

        if category:
            templates = cache.get_templates_by_category(category)
        else:
            templates = cache.get_all_templates()

        result = []
        for tpl in templates:
            result.append(
                {
                    "template_key": tpl.get("template_key", ""),
                    "template_name": tpl.get("template_name", ""),
                    "template_type": tpl.get("template_type", ""),
                    "category_key": tpl.get("category_key", ""),
                    "category_name": tpl.get("category_name", ""),
                    "description": tpl.get("description", ""),
                }
            )

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error listing templates: {str(e)}"


# ─────────────────────────── PPT 图片工具（PPT 专用场景） ───────────────────────────


@register_tool()
async def generate_ppt_image(
    page_title: str,
    page_content: str,
    save_path: str,
    page_type: str = "PPT页面图",
    page_data: str = None,
    requirement: str = "",
    template_type: int = 2,
    template_url: str = None,
    template_content: str = "",
    material_urls: list[str] = None,
    ratio: str = "16:9",
    ctx: Context = None,
) -> str:
    """Generate a PPT slide image using Gemini or Wan model with template and material support.

    The model is determined by IMAGE_PROVIDER env var (gemini/wan, default gemini).
    This tool is specifically designed for PPT image generation. It supports
    built-in templates, custom template images, material images, and data charts.
    Refer to generate_image_mcp.py generate_image_tool for the original implementation.

    IMPORTANT: Template types are dynamically managed via the admin panel. Call
    list_templates(category="image") first to discover available template_type values
    and their names. Do NOT guess or hardcode template_type values.

    Args:
        page_title: Title of the slide image.
        page_content: Text content of the slide.
        save_path: Local path to save the generated image.
        page_type: Type of image, e.g. "PPT页面图", "宣传图", "大屏展示图". Default "PPT页面图".
        page_data: Time-series data string for chart rendering (optional).
        requirement: Additional drawing requirements (optional).
        template_type: Template type number from list_templates. Call list_templates(category="image")
                       to get valid values. Special values: 0=custom URL (use template_url), 1=text
                       description (use template_content).
        template_url: Custom template image URL (used when template_type=0).
        template_content: Text description of the template (used when template_type=1).
        material_urls: List of material image URLs to embed in the generated image.
        ratio: Image aspect ratio, default "16:9". Use "9:16" for portrait.
        ctx: MCP context.

    Returns:
        The local path of the saved image, or an error message.
    """
    try:
        manager = _get_ppt_image_manager()
        return manager.generate_ppt_image(
            page_title=page_title,
            page_content=page_content,
            save_path=save_path,
            page_type=page_type,
            page_data=page_data,
            requirement=requirement,
            template_type=template_type,
            template_url=template_url,
            template_content=template_content,
            material_urls=material_urls,
            ratio=ratio,
        )
    except Exception as e:
        return f"Error generating PPT image: {str(e)}"


# ─────────────────────────── PPT 文件工具 ───────────────────────────


@register_tool()
async def generate_ppt_outline(
    topic: str, requirement: str = "", ctx: Context = None
) -> str:
    """Generate a structured PPT outline using DashScope qwen3-next-80b-a3b-instruct model.

    Args:
        topic: The main topic or theme of the presentation.
        requirement: Optional additional requirements or constraints.
        ctx: MCP context.

    Returns:
        JSON string of the outline with keys: title (str) and outline (list of
        parts, each with part title and pages). Returns an error message on failure.
    """
    try:
        manager = _get_ppt_manager()
        result = manager.generate_ppt_outline(topic, requirement)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error generating PPT outline: {str(e)}"


@register_tool()
async def create_ppt_file(
    outline_json: str, save_path: str, expand_content: bool = True, ctx: Context = None
) -> str:
    """Create a .pptx file from a structured outline.

    Args:
        outline_json: JSON string of the outline produced by generate_ppt_outline.
        save_path: Local path to save the generated .pptx file.
        expand_content: Whether to call the LLM to expand bullet points into
                        detailed paragraph text. Default is True.
        ctx: MCP context.

    Returns:
        The local path of the saved .pptx file, or an error message.
    """
    try:
        outline = json.loads(outline_json)
        manager = _get_ppt_manager()
        return manager.create_ppt_file(outline, save_path, expand_content)
    except json.JSONDecodeError as e:
        return f"Error parsing outline JSON: {str(e)}"
    except Exception as e:
        return f"Error creating PPT file: {str(e)}"


@register_tool()
async def create_ppt_from_images(
    image_paths: list[str], save_path: str, ctx: Context = None
) -> str:
    """Create a .pptx file from a list of local images.

    Args:
        image_paths: List of local image file paths to include in the PPT.
                     Each image will be added as a separate slide.
        save_path: Local path to save the generated .pptx file.
                   Should end with .pptx (e.g., "D:/output/presentation.pptx").
        ctx: MCP context.

    Returns:
        The local path of the saved .pptx file, or an error message.
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches

        if not image_paths:
            return "Error: No image paths provided"

        if not save_path.lower().endswith(".pptx"):
            return "Error: save_path must end with .pptx"

        prs = Presentation()
        prs.slide_width = Inches(10)
        prs.slide_height = Inches(5.625)

        for image_path in image_paths:
            if not os.path.exists(image_path):
                logger.info("Warning: Image not found, skipping: {}", image_path)
                continue

            try:
                blank_slide_layout = prs.slide_layouts[6]
                slide = prs.slides.add_slide(blank_slide_layout)

                slide.shapes.add_picture(
                    image_path,
                    left=Inches(0),
                    top=Inches(0),
                    width=prs.slide_width,
                    height=prs.slide_height,
                )
            except Exception as img_error:
                logger.info(
                    "Warning: Failed to add image {}: {}", image_path, img_error
                )
                continue

        if len(prs.slides) == 0:
            return "Error: No valid images were added to the PPT"

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        prs.save(save_path)

        return save_path

    except ImportError:
        return "Error: python-pptx library is required. Install with: pip install python-pptx"
    except Exception as e:
        return f"Error creating PPT from images: {str(e)}"


# ─────────────────────────── 文档转换工具 ───────────────────────────


@register_tool()
async def md_2_word(
    md_content: str,
    md_file_path: str = "",
    online_image_urls: list[str] = None,
    local_image_paths: list[str] = None,
    template_type: str = "",
    save_path: str = "",
    ctx: Context = None,
) -> str:
    """Convert markdown content to a Word document (.docx).

    Note:
        优先使用 md_file_path 指定的 .md 文件来生成 Word 文档；
        md_content 作为补充内容（存在时合并到文件内容末尾）。

    IMPORTANT: Template types are dynamically managed via the admin panel. Call
    list_templates(category="report") first to discover available template_type values
    and their names. Do NOT guess or hardcode template_type values.

    Args:
        md_content: The markdown content to convert. Can be empty if md_file_path is provided.
        md_file_path: Optional local path to a .md file whose content will be merged with md_content.
        online_image_urls: List of online image URLs to include.
        local_image_paths: List of local image paths to include.
        template_type: Template type number or name from list_templates. Call
                       list_templates(category="report") to get valid values.
        save_path: The path to save the generated .docx file.
        ctx: MCP context.

    Returns:
        Success message or error message.
    """
    if online_image_urls is None:
        online_image_urls = []
    if local_image_paths is None:
        local_image_paths = []

    try:
        # ── 如果提供了 .md 文件路径，读取内容并与 md_content 合并 ──
        if md_file_path:
            if not os.path.exists(md_file_path):
                return f"Error: md file not found at '{md_file_path}'"
            if not md_file_path.lower().endswith(".md"):
                return f"Error: file must be a .md file: '{md_file_path}'"
            with open(md_file_path, "r", encoding="utf-8") as f:
                file_content = f.read()
            if md_content.strip():
                md_content = md_content.strip() + "\n\n" + file_content
            else:
                md_content = file_content

        # ── 校验：md_content 和 md_file_path 不能同时为空 ──
        if not md_content.strip():
            return "Error: either md_content or md_file_path must be provided"

        return convert_md_to_docx(
            md_content, online_image_urls, local_image_paths, template_type, save_path
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        return f"Error converting markdown to docx: {str(e)}"


@register_tool()
async def md_2_pdf(
    md_content: str,
    md_file_path: str = "",
    online_image_urls: list[str] = None,
    local_image_paths: list[str] = None,
    template_type: str = "",
    save_path: str = "",
    ctx: Context = None,
) -> str:
    """Convert markdown content to a PDF document (.pdf).

    Note:
        优先使用 md_file_path 指定的 .md 文件来生成 PDF 文档；
        md_content 作为补充内容（存在时合并到文件内容末尾）。

    IMPORTANT: Template types are dynamically managed via the admin panel. Call
    list_templates(category="report") first to discover available template_type values
    and their names. Do NOT guess or hardcode template_type values.

    Args:
        md_content: The markdown content to convert. Can be empty if md_file_path is provided.
        md_file_path: Optional local path to a .md file whose content will be merged with md_content.
        online_image_urls: List of online image URLs to include.
        local_image_paths: List of local image paths to include.
        template_type: Template type number or name from list_templates. Call
                       list_templates(category="report") to get valid values.
        save_path: The path to save the generated .pdf file.
        ctx: MCP context.

    Returns:
        Success message or error message.
    """
    if online_image_urls is None:
        online_image_urls = []
    if local_image_paths is None:
        local_image_paths = []

    try:
        # ── 如果提供了 .md 文件路径，读取内容并与 md_content 合并 ──
        if md_file_path:
            if not os.path.exists(md_file_path):
                return f"Error: md file not found at '{md_file_path}'"
            if not md_file_path.lower().endswith(".md"):
                return f"Error: file must be a .md file: '{md_file_path}'"
            with open(md_file_path, "r", encoding="utf-8") as f:
                file_content = f.read()
            if md_content.strip():
                md_content = md_content.strip() + "\n\n" + file_content
            else:
                md_content = file_content

        # ── 校验：md_content 和 md_file_path 不能同时为空 ──
        if not md_content.strip():
            return "Error: either md_content or md_file_path must be provided"

        return convert_md_to_pdf(
            md_content, online_image_urls, local_image_paths, template_type, save_path
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        return f"Error converting markdown to pdf: {str(e)}"
