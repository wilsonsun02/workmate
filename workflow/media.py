import os
import base64
import requests
import json
import time
from io import BytesIO
from http import HTTPStatus
from dotenv import load_dotenv

load_dotenv()

from loguru import logger


def resolve_image_template_path(template_type: int) -> str | None:
    """统一解析图片模板路径，优先从 TemplateCache 获取，fallback 到本地硬编码映射。

    :param template_type: 模板类型编号（2-5 为内置模板）
    :return: 模板文件本地路径，未找到返回 None
    """
    try:
        from workflow.template_cache import get_template_cache

        cache = get_template_cache()
        if cache:
            template = cache.get_template_by_type_sync(
                str(template_type), category="image"
            )
            if template and template.get("local_file_path"):
                return template["local_file_path"]
    except Exception as e:
        logger.debug("TemplateCache 获取图片模板失败，fallback 到本地文件: {}", e)

    image_template_dir = os.getenv("IMAGE_TEMPLATE_DIR", "template/image-template")
    fallback_paths = {
        2: os.path.join(image_template_dir, "广西铝产品仓储交易中心模板.png"),
        3: os.path.join(image_template_dir, "吉利科技集团模板.png"),
        4: os.path.join(image_template_dir, "科技感模板.png"),
        5: os.path.join(image_template_dir, "中央财经大学模板.png"),
    }
    path = fallback_paths.get(template_type)
    if path and os.path.exists(path):
        return path
    return None


class VideoManager:
    """
    视频处理工具类。
    视频生成使用 MiniMax-Hailuo-2.3-Fast 模型（与原项目 serve.py 保持一致）。
    """

    def __init__(self):
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY")
        if not self.minimax_api_key:
            raise ValueError("未在环境变量中找到 MINIMAX_API_KEY")
        self.domain = os.getenv("MINIMAX_DOMAIN", "https://api.minimaxi.com")
        self.headers = {
            "Authorization": f"Bearer {self.minimax_api_key}",
            "Content-Type": "application/json",
        }

    def _import_moviepy(self):
        """懒加载 moviepy，避免未安装时影响模块导入"""
        from moviepy import (
            VideoFileClip,
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            CompositeAudioClip,
            vfx,
            afx,
        )

        return (
            VideoFileClip,
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            CompositeAudioClip,
            vfx,
            afx,
        )

    def submit_video_task(
        self,
        prompt: str,
        first_frame_image: str = None,
        last_frame_image: str = None,
        duration: int = 6,
    ) -> str:
        """
        提交视频生成任务（异步），立即返回 task_id。
        参考原项目 serve.py submit_video_task 接口实现。

        :param prompt: 视频生成提示词
        :param first_frame_image: 可选的首帧图片 URL（图生视频）
        :param last_frame_image: 可选的尾帧图片 URL（首尾帧模式）
        :param duration: 视频时长（秒），可选 6 或 10
        :return: 任务 ID（task_id）
        """
        payload = {
            "model": os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-2.3-Fast"),
            "prompt": prompt,
            "duration": duration,
            "resolution": "768P",
        }

        if first_frame_image:
            payload["first_frame_image"] = first_frame_image
        if last_frame_image:
            payload["last_frame_image"] = last_frame_image

        resp = requests.post(
            f"{self.domain}/v1/video_generation", headers=self.headers, json=payload
        ).json()

        task_id = resp.get("task_id")
        if not task_id:
            raise ValueError(f"提交视频任务失败: {resp}")
        return task_id

    def query_video_task(self, task_id: str, save_path: str = None) -> dict:
        """
        查询视频生成任务状态。若任务成功且提供了 save_path，则自动下载视频到本地。

        :param task_id: 由 submit_video_task 返回的任务 ID
        :param save_path: 可选，视频保存的本地路径；不传则只返回状态
        :return: 包含 status、file_id、download_url、local_path 的字典
        """
        status_resp = requests.get(
            f"{self.domain}/v1/query/video_generation",
            headers=self.headers,
            params={"task_id": task_id},
        ).json()

        status = status_resp.get("status")
        result = {"task_id": task_id, "status": status}

        if status == "Success":
            file_id = status_resp.get("file_id")
            result["file_id"] = file_id

            file_info = requests.get(
                f"{self.domain}/v1/files/retrieve",
                headers=self.headers,
                params={"file_id": file_id},
            ).json()
            download_url = file_info.get("file", {}).get("download_url")
            result["download_url"] = download_url

            if save_path and download_url:
                video_bytes = requests.get(download_url).content
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(video_bytes)
                result["local_path"] = save_path

        elif status in ("Fail", "Error"):
            result["error"] = status_resp.get("message", "任务失败")

        return result

    def add_subtitle_and_audio(
        self, video_path: str, audio_path: str, subtitle: str, save_path: str
    ) -> str:
        """
        将视频、音频和字幕进行合成

        :param video_path: 原始视频本地路径
        :param audio_path: 音频本地路径
        :param subtitle: 字幕文本
        :param save_path: 合成后视频的保存路径
        :return: 合成后视频的本地路径
        """
        try:
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont

            (
                VideoFileClip,
                AudioFileClip,
                CompositeVideoClip,
                ImageClip,
                CompositeAudioClip,
                vfx,
                afx,
            ) = self._import_moviepy()

            video = VideoFileClip(video_path)
            v_dur = video.duration
            audio = AudioFileClip(audio_path)

            audio_safe = audio.subclipped(0, max(0, audio.duration - 0.2))
            audio_safe = audio_safe.with_effects([afx.AudioFadeOut(0.2)])

            if audio_safe.duration > v_dur:
                speed_factor = audio_safe.duration / v_dur
                audio_final = audio_safe.with_effects([vfx.MultiplySpeed(speed_factor)])
            else:
                audio_final = CompositeAudioClip(
                    [audio_safe.with_start(0)]
                ).with_duration(v_dur)

            audio_final = audio_final.with_duration(v_dur)
            video_with_audio = video.with_audio(audio_final)

            base_font_size = 32
            max_w = int(video.w * 0.9)
            font_path = (
                "C:/Windows/Fonts/simhei.ttf"
                if os.name == "nt"
                else "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
            )

            subtitle = str(subtitle).replace("\n", "").replace("\r", "").strip()

            current_font_size = base_font_size
            try:
                font = ImageFont.truetype(font_path, current_font_size)
            except IOError:
                font = ImageFont.load_default()

            while font.getlength(subtitle) > max_w and current_font_size > 18:
                current_font_size -= 2
                try:
                    font = ImageFont.truetype(font_path, current_font_size)
                except IOError:
                    break

            text_w = font.getlength(subtitle)
            text_h = current_font_size

            sub_canvas_h = text_h + 20
            sub_img = Image.new("RGBA", (video.w, sub_canvas_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(sub_img)

            bg_padding = 20
            bg_x1 = (video.w - text_w) // 2 - bg_padding
            bg_x2 = (video.w + text_w) // 2 + bg_padding
            draw.rectangle([bg_x1, 0, bg_x2, sub_canvas_h], fill=(0, 0, 0, 160))
            draw.text(
                ((video.w - text_w) // 2, 8),
                subtitle,
                font=font,
                fill=(255, 255, 255, 255),
            )

            bottom_margin = 40
            txt_clip = (
                ImageClip(np.array(sub_img))
                .with_duration(v_dur)
                .with_position(("center", video.h - sub_canvas_h - bottom_margin))
                .with_start(0)
            )

            result_video = CompositeVideoClip(
                [video_with_audio, txt_clip], size=video.size
            ).with_duration(v_dur)

            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            result_video.write_videofile(
                save_path,
                codec="libx264",
                audio_codec="aac",
                fps=24,
                logger=None,
                remove_temp=True,
            )

            result_video.close()
            video.close()
            audio.close()
            txt_clip.close()

            return save_path

        except Exception as e:
            logger.info(f"合成视频字幕音频失败: {str(e)}")
            raise

    def merge_videos(self, video_paths: list, save_path: str) -> str:
        """
        使用 FFmpeg 将多个视频片段无损拼接

        :param video_paths: 视频片段本地路径列表
        :param save_path: 最终合并视频的保存路径
        :return: 合并后视频的本地路径
        """
        if not video_paths:
            raise ValueError("视频路径列表为空")

        list_file = "concat_list.txt"
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for path in video_paths:
                    abs_path = os.path.abspath(path).replace("\\", "/")
                    f.write(f"file '{abs_path}'\n")

            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            cmd = f'ffmpeg -f concat -safe 0 -i {list_file} -c:v copy -c:a aac -b:a 192k -ar 44100 -y "{save_path}"'
            exit_code = os.system(cmd)

            if exit_code == 0:
                return save_path
            else:
                raise RuntimeError(f"FFmpeg 拼接失败，退出码: {exit_code}")

        except Exception as e:
            logger.info(f"合并视频失败: {str(e)}")
            raise
        finally:
            if os.path.exists(list_file):
                try:
                    os.remove(list_file)
                except Exception:
                    pass


class AudioManager:
    """
    音频处理工具类，负责文本转语音(TTS)和语音转文本(ASR)。
    TTS 使用 MiniMax speech-2.6-turbo（与原项目 serve.py 保持一致）。
    ASR 使用 DashScope qwen3-asr-flash-filetrans。
    """

    def __init__(self):
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY")
        self.dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
        self.domain = os.getenv("MINIMAX_DOMAIN", "https://api.minimaxi.com")
        self.minimax_headers = {
            "Authorization": f"Bearer {self.minimax_api_key}",
            "Content-Type": "application/json",
        }

    def generate_audio(
        self, text: str, save_path: str, voice_id: str = "audiobook_male_1"
    ) -> str:
        """
        文本转语音 (TTS)，使用 MiniMax speech-2.6-turbo 模型。
        参考原项目 serve.py submit_audio_task 接口实现。

        :param text: 需要转换的文本
        :param save_path: 音频保存的本地路径 (.mp3)
        :param voice_id: 发音人 ID，默认 "audiobook_male_1"
        :return: 生成的音频本地路径
        """
        if not self.minimax_api_key:
            raise ValueError("未在环境变量中找到 MINIMAX_API_KEY")

        payload = {
            "model": os.getenv("MINIMAX_TTS_MODEL", "speech-2.6-turbo"),
            "text": text,
            "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0},
            "audio_setting": {"format": "mp3", "audio_sample_rate": 32000},
        }

        try:
            resp = requests.post(
                f"{self.domain}/v1/t2a_async_v2",
                headers=self.minimax_headers,
                json=payload,
            ).json()

            task_id = resp.get("task_id")
            if not task_id:
                raise ValueError(f"提交TTS任务失败: {resp}")

            # 轮询任务状态
            while True:
                status_resp = requests.get(
                    f"{self.domain}/v1/query/t2a_async_query_v2",
                    headers=self.minimax_headers,
                    params={"task_id": task_id},
                ).json()

                status = status_resp.get("status")

                if status == "Success":
                    file_id = status_resp.get("file_id")
                    file_info = requests.get(
                        f"{self.domain}/v1/files/retrieve",
                        headers=self.minimax_headers,
                        params={"file_id": file_id},
                    ).json()
                    download_url = file_info.get("file", {}).get("download_url")
                    if not download_url:
                        raise ValueError("TTS任务成功但未获取到下载链接")

                    audio_bytes = requests.get(download_url).content
                    os.makedirs(
                        os.path.dirname(os.path.abspath(save_path)), exist_ok=True
                    )
                    with open(save_path, "wb") as f:
                        f.write(audio_bytes)
                    return save_path

                elif status in ("Fail", "Error"):
                    raise ValueError(f"TTS任务失败，状态: {status}")

                time.sleep(3)

        except Exception as e:
            logger.info(f"生成音频失败: {str(e)}")
            raise

    def _format_time(self, ms: int) -> str:
        """将毫秒转换为 HH:MM:SS 格式"""
        if ms is None:
            return "00:00:00"
        seconds = int((ms / 1000) % 60)
        minutes = int((ms / (1000 * 60)) % 60)
        hours = int((ms / (1000 * 60 * 60)) % 24)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def extract_audio_text(self, audio_path_or_url: str) -> list:
        """
        语音转文本 (ASR)，使用 DashScope qwen3-asr-flash-filetrans 模型。
        支持本地文件路径和公开访问 URL。

        :param audio_path_or_url: 音频文件的本地路径或公开访问 URL
        :return: 包含时间戳和文本的字典列表
        """
        if not self.dashscope_api_key:
            raise ValueError("未在环境变量中找到 DASHSCOPE_API_KEY")

        try:
            import dashscope
            from dashscope import Files
            from dashscope.audio.qwen_asr import QwenTranscription

            dashscope.api_key = self.dashscope_api_key

            # 判断是本地文件还是 URL
            if os.path.exists(audio_path_or_url):
                # 本地文件，先上传到 DashScope
                logger.info(f"检测到本地文件，正在上传: {audio_path_or_url}")

                # 上传文件
                upload_response = Files.upload(
                    file_path=audio_path_or_url, purpose="file-extract"
                )

                if upload_response.status_code != HTTPStatus.OK:
                    raise ValueError(f"上传文件失败: {upload_response.message}")

                uploaded_files = upload_response.output.get("uploaded_files", [])
                if not uploaded_files:
                    raise ValueError("文件上传成功但没有返回文件信息")

                file_id = uploaded_files[0].get("file_id")
                logger.info(f"文件上传成功，File ID: {file_id}")

                # 获取文件信息以获取公开URL
                file_info = Files.get(file_id=file_id)
                if file_info.status_code != HTTPStatus.OK:
                    raise ValueError(f"获取文件信息失败: {file_info.message}")

                file_url = file_info.output.get("url")
                logger.info(f"文件 URL: {file_url}")

                # 使用文件URL提交ASR任务
                task_response = QwenTranscription.async_call(
                    model="qwen3-asr-flash-filetrans", file_url=file_url
                )
            else:
                # 已经是 URL
                task_response = QwenTranscription.async_call(
                    model="qwen3-asr-flash-filetrans", file_url=audio_path_or_url
                )

            if task_response.status_code != HTTPStatus.OK:
                raise ValueError(f"提交ASR任务失败: {task_response.message}")

            task_id = task_response.output.task_id

            while True:
                task_result = QwenTranscription.wait(task=task_id)
                if task_result.status_code == HTTPStatus.OK:
                    output = task_result.output
                    status = output.get("task_status")

                    if status == "SUCCEEDED":
                        json_url = output.get("result", {}).get("transcription_url")
                        if json_url:
                            data = requests.get(json_url).json()
                            transcripts = data.get("transcripts", [])
                            if transcripts:
                                raw_segments = transcripts[0].get("sentences", [])
                                return [
                                    {
                                        "text": seg.get("text", ""),
                                        "begin_time": self._format_time(
                                            seg.get("begin_time")
                                        ),
                                        "end_time": self._format_time(
                                            seg.get("end_time")
                                        ),
                                        "emotion": seg.get("emotion", "neutral"),
                                    }
                                    for seg in raw_segments
                                ]
                            return []

                    elif status in ["FAILED", "CANCELED"]:
                        raise ValueError(f"ASR任务失败，状态: {status}")

                time.sleep(2)

        except Exception as e:
            logger.info(f"提取音频文本失败: {str(e)}")
            raise


def _encode_image_to_base64_from_path(image_path: str) -> str:
    """将本地图片文件转换为 Base64 编码字符串"""
    from PIL import Image

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    with Image.open(image_path) as img:
        buffered = BytesIO()
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img.save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _encode_image_to_base64_from_pil(img) -> str:
    """将 PIL Image 对象转换为 Base64 编码字符串"""
    buffered = BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(buffered, format="JPEG", quality=95)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def _save_base64_image(image_data_url: str, save_path: str) -> str:
    """将 data URI 格式的 base64 图片数据解码并保存到本地"""
    if "," in image_data_url:
        base64_data = image_data_url.split(",")[1]
    else:
        base64_data = image_data_url
    image_bytes = base64.b64decode(base64_data)
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(image_bytes)
    return save_path


_RATIO_SIZE_MAP = {
    "1:1": "1280*1280",
    "16:9": "1728*960",
    "9:16": "960*1728",
    "4:3": "1568*1056",
    "3:4": "1056*1568",
    "3:2": "1472*1088",
    "2:3": "1088*1472",
}


def _get_image_provider() -> str:
    """获取图片生成模型供应商（gemini / wan），默认 gemini"""
    return os.getenv("IMAGE_PROVIDER", "gemini").lower()


def _build_gemini_image_llm():
    """
    构建 Gemini 图片生成模型实例。
    使用 gemini-3-pro-image-preview（与原项目 model.py image_llm 保持一致）。
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=os.getenv("IMAGE_LLM_MODEL", "gemini-3-pro-image-preview"),
        temperature=1,
        api_key=os.getenv("GOOGLE_API_KEY"),
        image_config={
            "image_size": "4K",
        },
    )


class WanImageGenerator:
    """
    万相(wan)图片生成与修改工具类。
    使用 DashScope wan2.7-image-pro 模型，支持文本+多图输入。
    可完全替代 Gemini 的 generate_image / modify_image / generate_ppt_image 功能。
    """

    DASHSCOPE_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("未在环境变量中找到 DASHSCOPE_API_KEY")
        self.model = os.getenv("WAN_IMAGE_MODEL", "wan2.7-image-pro")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _load_image_for_wan(self, image_path_or_url: str) -> str:
        """
        加载图片为万相 API 格式。
        网络URL直接传入，本地文件转为 data:image/jpeg;base64,{b64} 格式。
        """
        if image_path_or_url.startswith("http"):
            return image_path_or_url
        b64 = _encode_image_to_base64_from_path(image_path_or_url)
        return f"data:image/jpeg;base64,{b64}"

    def _build_content(self, images: list, text: str) -> list:
        """
        构建万相 API content 数组。

        万相 API 约束：content 中恰好只能有 1 个 text 项，可以有多个 image 项。
        推荐顺序：image 项先放，text 项最后放。

        :param images: 图片 URL 或 base64 data URI 列表
        :param text: 合并后的完整提示词文本（必须为单个字符串）
        :return: 符合万相 API 格式的 content 列表
        """
        content = []
        for img in images:
            content.append({"image": img})
        content.append({"text": text})
        return content

    def _call_api(self, images: list, text: str, size: str = "1728*960") -> str:
        """
        调用万相 DashScope 同步 API，返回生成图片的 URL。

        :param images: 输入图片 URL 或 base64 data URI 列表
        :param text: 合并后的完整提示词文本（恰好 1 个 text 项）
        :param size: 图片像素尺寸，如 "1728*960"
        :return: 生成图片的 URL
        """
        content = self._build_content(images, text)
        payload = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"size": size, "n": 1},
        }

        resp = requests.post(self.DASHSCOPE_API_URL, headers=self.headers, json=payload)
        result = resp.json()

        choices = result.get("output", {}).get("choices", [])
        if not choices:
            error_msg = result.get("message", result.get("code", "未知错误"))
            raise ValueError(f"万相 API 调用失败: {error_msg}")

        message_content = choices[0].get("message", {}).get("content", [])
        for item in message_content:
            if item.get("type") == "image":
                return item.get("image")

        raise ValueError("万相 API 返回结果中未找到图片数据")

    def _download_and_save(self, image_url: str, save_path: str) -> str:
        """下载万相生成的图片并保存到本地"""
        image_bytes = requests.get(image_url).content
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        logger.info(f"万相图片已保存到: {save_path}")
        return save_path

    def _resolve_size(self, ratio: str = "16:9") -> str:
        """将比例字符串映射为万相支持的像素尺寸"""
        return _RATIO_SIZE_MAP.get(ratio, "1728x960")

    def generate_image(
        self, prompt: str, save_path: str, reference_image_path: str = None
    ) -> str:
        """
        文生图或图生图（可选参考图）。

        :param prompt: 图片生成提示词
        :param save_path: 生成图片的本地保存路径
        :param reference_image_path: 可选的参考图片本地路径或 URL
        :return: 生成图片的本地路径
        """
        images = []
        text = prompt

        if reference_image_path:
            images.append(self._load_image_for_wan(reference_image_path))
            text = f"请参考以下图片的风格和布局：\n{prompt}"

        image_url = self._call_api(images, text, size=self._resolve_size("16:9"))
        return self._download_and_save(image_url, save_path)

    def modify_image(self, image_path: str, requirement: str, save_path: str) -> str:
        """
        根据需求修改现有图片，保持原始风格和配色。

        :param image_path: 需要修改的原始图片本地路径或 URL
        :param requirement: 修改需求描述
        :param save_path: 修改后图片的本地保存路径
        :return: 修改后图片的本地路径
        """
        images = [self._load_image_for_wan(image_path)]
        text = (
            f"请仔细观察原始图片，根据以下需求修改图片内容：\n{requirement}\n\n"
            "要求：保持原始图片的配色、视觉风格和布局结构，确保文字清晰锐利。"
        )

        image_url = self._call_api(images, text, size="2K")
        return self._download_and_save(image_url, save_path)

    def generate_ppt_image(
        self,
        page_title: str,
        page_content: str,
        save_path: str,
        page_type: str = "PPT页面图",
        page_data: str = None,
        requirement: str = "",
        template_type: int = 2,
        template_url: str = None,
        template_content: str = "",
        material_urls: list = None,
        ratio: str = "16:9",
    ) -> str:
        """
        PPT图片生成，支持模板图片和素材图片输入。

        :param page_title: 图片标题
        :param page_content: 图片文字内容
        :param save_path: 生成图片的本地保存路径
        :param page_type: 图片类型
        :param page_data: 时间序列数据
        :param requirement: 额外绘制要求
        :param template_type: 模板类型编号
        :param template_url: 自定义模板图片 URL
        :param template_content: 模板文字描述
        :param material_urls: 素材图片 URL 列表
        :param ratio: 图片比例，默认 "16:9"
        :return: 生成图片的本地路径
        """
        images = []

        # 模板图片
        image_template = resolve_image_template_path(template_type) or template_url

        # 构建文字描述前缀（模板和素材的说明都合并到 text 中）
        text_prefix_parts = []

        if image_template:
            images.append(self._load_image_for_wan(image_template))
            text_prefix_parts.append("下面这张图是模板图片，绘图时参考以下模板图片。")

        # 素材图片
        if material_urls:
            text_prefix_parts.append(
                "下面这些图是素材图片，绘图时请将以下素材图内容添加到生成的图片上。"
            )
            for m_url in material_urls:
                images.append(self._load_image_for_wan(m_url))

        # 提示词（与 Gemini 版保持一致）
        prompt_text = f"""
你是一位专家级UI UX演示设计师，专注于生成设计各种类型的图片（包括宣传页、展示图、PPT页面等）。参考以上图片模板的风格，按照以下要求生成一张{page_type}图片。
{page_type}图片的要求如下：

1. ***{page_type}图片标题为：***
{page_title or "无"}

2. ***{page_type}图片文字为：***
{page_content or "无"}

3. ***时间序列的数据为：***
{page_data or "无"}

4. ***模板图片的文字描述为：***
{template_content or "无"}

5. ***用户需求如下：***
{requirement or "无"}

6. ***设计要求如下：***
- {ratio}比例，图片上的中文字请不要出现乱码，要求文字清晰锐利。
- 配色和设计语言和模板图片严格相似。
- 只参考模板图片的布局结构、视觉风格、配色、排版细节、视觉引导。禁止出现模板中的文字。
- 请仔细阅读"时间序列的数据"，根据数据内容在图片上绘制折线图、柱状图、饼状图等图形。
- 根据内容自动设计最完美的构图，不重不漏地渲染"页面描述"中的文本。
- 将素材图片的内容全部插入到最合适的位置中，不要遗漏任何素材图片的内容。
- 如非必要，禁止出现 markdown 格式符号（如 # 和 * 等）。
- 标题请严格按照图片标题文字来生成，不要修改标题的文字内容。
- 如果"图片标题"为空，请在生成图片中不要添加图片标题信息。

请基于以上要求生成图片。
"""

        # 合并所有文字为单个 text 项
        text = "\n".join(text_prefix_parts) + prompt_text

        image_url = self._call_api(images, text, size=self._resolve_size(ratio))
        return self._download_and_save(image_url, save_path)


class ImageManager:
    """
    通用图片生成与修改工具类。
    根据 IMAGE_PROVIDER 环境变量选择 Gemini 或万相(wan)模型。
    默认使用 Gemini gemini-3-pro-image-preview，可切换为万相 wan2.7-image-pro。
    """

    def __init__(self):
        provider = _get_image_provider()
        if provider == "wan":
            self._provider = "wan"
            self._wan = WanImageGenerator()
        else:
            self._provider = "gemini"
            self.llm = _build_gemini_image_llm()

    def _build_image_content(self, image_path_or_url: str, label: str = None) -> list:
        """
        构建图片消息内容块，支持本地路径和网络 URL。

        :param image_path_or_url: 本地图片路径或网络 URL
        :param label: 可选的说明文字
        :return: 消息内容块列表
        """
        from langchain_core.messages import HumanMessage  # noqa: F401

        content_blocks = []
        if label:
            content_blocks.append({"type": "text", "text": label})

        if image_path_or_url.startswith("http"):
            from PIL import Image as PILImage

            resp = requests.get(image_path_or_url)
            img = PILImage.open(BytesIO(resp.content))
            b64 = _encode_image_to_base64_from_pil(img)
        else:
            b64 = _encode_image_to_base64_from_path(image_path_or_url)

        content_blocks.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        )
        return content_blocks

    def generate_image(
        self, prompt: str, save_path: str, reference_image_path: str = None
    ) -> str:
        """
        根据提示词生成图片（可选参考图），画面为4K分辨率。

        :param prompt: 图片生成提示词
        :param save_path: 生成图片的本地保存路径
        :param reference_image_path: 可选的参考图片本地路径或 URL
        :return: 生成图片的本地路径
        """
        if self._provider == "wan":
            return self._wan.generate_image(prompt, save_path, reference_image_path)

        from langchain_core.messages import HumanMessage

        content = []

        if reference_image_path:
            content += self._build_image_content(
                reference_image_path, "请参考以下图片的风格和布局："
            )

        content.append({"type": "text", "text": prompt})
        messages = [HumanMessage(content=content)]

        try:
            response = self.llm.invoke(messages)
            if hasattr(response, "content") and isinstance(response.content, list):
                for item in response.content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return _save_base64_image(item["image_url"]["url"], save_path)
            raise ValueError("模型返回结果中未找到图片数据")
        except Exception as e:
            logger.info(f"生成图片失败: {str(e)}")
            raise

    def modify_image(self, image_path: str, requirement: str, save_path: str) -> str:
        """
        根据需求修改现有图片，保持原始风格和配色。

        :param image_path: 需要修改的原始图片本地路径或 URL
        :param requirement: 修改需求描述
        :param save_path: 修改后图片的本地保存路径
        :return: 修改后图片的本地路径
        """
        if self._provider == "wan":
            return self._wan.modify_image(image_path, requirement, save_path)

        from langchain_core.messages import HumanMessage

        content = self._build_image_content(image_path, "以下是需要修改的原始图片：")
        content.append(
            {
                "type": "text",
                "text": (
                    f"请仔细观察原始图片，根据以下需求修改图片内容：\n{requirement}\n\n"
                    "要求：保持原始图片的分辨率、配色、视觉风格和布局结构，确保文字清晰锐利。"
                ),
            }
        )
        messages = [HumanMessage(content=content)]

        try:
            response = self.llm.invoke(messages)
            if hasattr(response, "content") and isinstance(response.content, list):
                for item in response.content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return _save_base64_image(item["image_url"]["url"], save_path)
            raise ValueError("模型返回结果中未找到图片数据")
        except Exception as e:
            logger.info(f"修改图片失败: {str(e)}")
            raise


class PPTImageManager:
    """
    PPT 图片生成工具类。
    根据 IMAGE_PROVIDER 环境变量选择 Gemini 或万相(wan)模型。
    支持模板、素材图片和数据图表。
    """

    def __init__(self):
        provider = _get_image_provider()
        if provider == "wan":
            self._provider = "wan"
            self._wan = WanImageGenerator()
        else:
            self._provider = "gemini"
            self.llm = _build_gemini_image_llm()

    def _load_image_as_base64(self, image_path_or_url: str) -> str:
        """加载本地或网络图片并转为 base64"""
        if image_path_or_url.startswith("http"):
            resp = requests.get(image_path_or_url)
            from PIL import Image as PILImage

            img = PILImage.open(BytesIO(resp.content))
            return _encode_image_to_base64_from_pil(img)
        return _encode_image_to_base64_from_path(image_path_or_url)

    def generate_ppt_image(
        self,
        page_title: str,
        page_content: str,
        save_path: str,
        page_type: str = "PPT页面图",
        page_data: str = None,
        requirement: str = "",
        template_type: int = 2,
        template_url: str = None,
        template_content: str = "",
        material_urls: list = None,
        ratio: str = "16:9",
    ) -> str:
        """
        根据标题和内容生成 PPT 图片，支持模板和素材图片。

        :param page_title: 图片标题
        :param page_content: 图片文字内容
        :param save_path: 生成图片的本地保存路径
        :param page_type: 图片类型（PPT页面图、宣传图等）
        :param page_data: 时间序列数据（用于绘制图表）
        :param requirement: 额外的绘制要求
        :param template_type: 模板类型（2-5 为内置模板，0 为自定义，1 为文字描述）
        :param template_url: 自定义模板图片 URL（template_type=0 时使用）
        :param template_content: 模板文字描述（template_type=1 时使用）
        :param material_urls: 素材图片 URL 列表
        :param ratio: 图片比例，默认 "16:9"
        :return: 生成图片的本地路径
        """
        if self._provider == "wan":
            return self._wan.generate_ppt_image(
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

        from langchain_core.messages import HumanMessage

        image_template = resolve_image_template_path(template_type) or template_url

        image_style = []

        if image_template:
            b64 = self._load_image_as_base64(image_template)
            image_style.append(
                {
                    "type": "text",
                    "text": "下面这张图是模板图片，绘图时参考以下模板图片。",
                }
            )
            image_style.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }
            )

        if material_urls:
            image_style.append(
                {
                    "type": "text",
                    "text": "下面这些图是素材图片，绘图时请将以下素材图内容添加到生成的图片上。",
                }
            )
            for m_url in material_urls:
                b64 = self._load_image_as_base64(m_url)
                image_style.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    }
                )

        prompt_text = f"""
你是一位专家级UI UX演示设计师，专注于生成设计各种类型的图片（包括宣传页、展示图、PPT页面等）。参考以上图片模板的风格，按照以下要求生成一张{page_type}图片。
{page_type}图片的要求如下：

1. ***{page_type}图片标题为：***
{page_title or "无"}

2. ***{page_type}图片文字为：***
{page_content or "无"}

3. ***时间序列的数据为：***
{page_data or "无"}

4. ***模板图片的文字描述为：***
{template_content or "无"}

5. ***用户需求如下：***
{requirement or "无"}

6. ***设计要求如下：***
- 画面为4K分辨率，{ratio}比例，图片上的中文字请不要出现乱码，要求文字清晰锐利。
- 配色和设计语言和模板图片严格相似。
- 只参考模板图片的布局结构、视觉风格、配色、排版细节、视觉引导。禁止出现模板中的文字。
- 请仔细阅读"时间序列的数据"，根据数据内容在图片上绘制折线图、柱状图、饼状图等图形。
- 根据内容自动设计最完美的构图，不重不漏地渲染"页面描述"中的文本。
- 将素材图片的内容全部插入到最合适的位置中，不要遗漏任何素材图片的内容。
- 如非必要，禁止出现 markdown 格式符号（如 # 和 * 等）。
- 标题请严格按照图片标题文字来生成，不要修改标题的文字内容。
- 如果"图片标题"为空，请在生成图片中不要添加图片标题信息。

请基于以上要求生成图片。
"""

        messages = [
            HumanMessage(content=[*image_style, {"type": "text", "text": prompt_text}])
        ]

        try:
            response = self.llm.invoke(messages)
            if hasattr(response, "content") and isinstance(response.content, list):
                for item in response.content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return _save_base64_image(item["image_url"]["url"], save_path)
            raise ValueError("模型返回结果中未找到图片数据")
        except Exception as e:
            logger.info(f"生成PPT图片失败: {str(e)}")
            raise


class PPTManager:
    """
    PPT 处理工具类，负责 PPT 大纲生成和 PPTX 文件创建。
    模型由 LLM_PROVIDER 决定，与主模型共用配置。
    """

    def __init__(self):
        from langchain_core.messages import HumanMessage
        from workflow.model import (
            get_ppt_outline_prompt,
            get_ppt_page_expand_prompt,
            create_text_llm_instance,
        )

        self._HumanMessage = HumanMessage
        self.llm = create_text_llm_instance()
        # 从 model.py 动态加载提示词
        self._OUTLINE_PROMPT = get_ppt_outline_prompt()
        self._PAGE_EXPAND_PROMPT = get_ppt_page_expand_prompt()

    def generate_ppt_outline(self, topic: str, requirement: str = "") -> dict:
        """
        调用 LLM 生成结构化的 PPT 大纲

        :param topic: PPT 主题描述
        :param requirement: 额外的生成要求
        :return: 包含 title 和 outline 的字典
        """
        prompt = self._OUTLINE_PROMPT.format(
            topic=topic, requirement=requirement if requirement else "无"
        )

        try:
            response = self.llm.invoke([self._HumanMessage(content=prompt)])
            content = response.content.strip()

            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            result = json.loads(content)
            return result

        except Exception as e:
            logger.info(f"生成PPT大纲失败: {str(e)}")
            raise

    def _convert_outline_format(self, result: dict, topic: str) -> dict:
        """
        将新的扁平化大纲格式转换为嵌套结构

        新格式: {"outline": [{"page_title": "...", "page_description": "..."}]}
        目标格式: {"title": "...", "outline": [{"part": "...", "pages": [{"title": "...", "points": [...]}]}]}
        """
        pages = result.get("outline", [])
        converted_outline = []

        for i, page in enumerate(pages):
            page_title = page.get("page_title", f"页面{i + 1}")
            page_description = page.get("page_description", "")

            points = self._parse_description_to_points(page_description)

            converted_outline.append(
                {
                    "part": f"第{i + 1}部分",
                    "pages": [{"title": page_title, "points": points}],
                }
            )

        return {"title": topic, "outline": converted_outline}

    def _parse_description_to_points(self, description: str) -> list:
        """
        将页面描述文本解析为要点列表
        """
        if not description:
            return []

        lines = description.split("\n")
        points = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("-") or line.startswith("•"):
                point = line.lstrip("-•").strip()
                if point:
                    points.append(point)
            elif line[0].isdigit() and ". " in line:
                point = line.split(". ", 1)[1].strip() if ". " in line else line
                if point:
                    points.append(point)
            else:
                if line:
                    points.append(line)

        return points

    def _normalize_outline_format(self, outline: dict) -> dict:
        """
        规范化大纲格式，确保为嵌套结构

        如果是扁平化结构（包含 page_title），则转换为嵌套结构
        否则直接返回（已经是嵌套结构或没有页面）
        """
        pages = outline.get("outline", [])
        if not pages:
            return outline

        first_page = pages[0]
        if "page_title" in first_page:
            topic = outline.get("title", "演示文稿")
            return self._convert_outline_format(outline, topic)

        return outline

    def _expand_page_content(self, title: str, points: list, topic: str) -> str:
        """调用 LLM 将页面要点扩展为详细文字内容"""
        prompt = self._PAGE_EXPAND_PROMPT.format(
            title=title, points="\n".join([f"- {p}" for p in points]), topic=topic
        )

        try:
            response = self.llm.invoke([self._HumanMessage(content=prompt)])
            content = response.content.strip()

            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            page_data = json.loads(content)
            return page_data.get("page_content", "\n".join(points))

        except Exception:
            return "\n".join([f"• {p}" for p in points])

    def create_ppt_file(
        self, outline: dict, save_path: str, expand_content: bool = True
    ) -> str:
        """
        根据大纲内容生成本地 .pptx 文件

        :param outline: generate_ppt_outline 返回的大纲字典（扁平化结构或嵌套结构）
        :param save_path: PPTX 文件的本地保存路径
        :param expand_content: 是否调用 LLM 扩展每页内容，默认 True
        :return: 生成的 PPTX 文件本地路径
        """
        outline = self._normalize_outline_format(outline)

        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation()
        prs.slide_width = Inches(13.33)
        prs.slide_height = Inches(7.5)

        ppt_title = outline.get("title", "演示文稿")
        outline_parts = outline.get("outline", [])

        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = ppt_title
        if slide.placeholders[1]:
            slide.placeholders[1].text = "AI 自动生成"

        for part in outline_parts:
            part_title = part.get("part", "")
            pages = part.get("pages", [])

            section_slide = prs.slides.add_slide(prs.slide_layouts[2])
            section_slide.shapes.title.text = part_title

            for page in pages:
                page_title = page.get("title", "")
                points = page.get("points", [])

                if expand_content and points:
                    page_content = self._expand_page_content(
                        page_title, points, ppt_title
                    )
                else:
                    page_content = "\n".join([f"• {p}" for p in points])

                content_slide = prs.slides.add_slide(prs.slide_layouts[1])
                content_slide.shapes.title.text = page_title

                if content_slide.placeholders[1]:
                    tf = content_slide.placeholders[1].text_frame
                    tf.word_wrap = True
                    tf.text = page_content

        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        prs.save(save_path)
        return save_path
