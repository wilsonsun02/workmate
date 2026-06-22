import os
from typing import Optional, Tuple

import oss2

from admin_api.services.env_file_service import EnvFileService


class OssService:
    @staticmethod
    def _load_env_config() -> dict:
        return EnvFileService.get_effective_values()

    @staticmethod
    def _get_value(cfg: dict, key: str, default: str = "") -> str:
        val = cfg.get(key)
        if val is None or val == "":
            val = os.getenv(key, default)
        return str(val) if val is not None else default

    @staticmethod
    def _build_auth(cfg: dict):
        mode = OssService._get_value(cfg, "OSS_AUTH_MODE", "aksk").lower()
        key_id = OssService._get_value(cfg, "OSS_ACCESS_KEY_ID")
        key_secret = OssService._get_value(cfg, "OSS_ACCESS_KEY_SECRET")
        if mode == "sts":
            sts_token = OssService._get_value(cfg, "OSS_STS_TOKEN")
            if not (key_id and key_secret and sts_token):
                raise ValueError("Missing OSS STS credentials")
            return oss2.StsAuth(key_id, key_secret, sts_token), mode
        if not (key_id and key_secret):
            raise ValueError("Missing OSS AK/SK credentials")
        return oss2.Auth(key_id, key_secret), "aksk"

    @staticmethod
    def _build_bucket() -> Tuple[oss2.Bucket, str]:
        cfg = OssService._load_env_config()
        endpoint = OssService._get_value(cfg, "OSS_ENDPOINT")
        bucket_name = OssService._get_value(cfg, "OSS_BUCKET")
        if not endpoint or not bucket_name:
            raise ValueError("Missing OSS endpoint or bucket")
        auth, mode = OssService._build_auth(cfg)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        return bucket, mode

    @staticmethod
    def upload_file(local_path: str, object_key: str) -> dict:
        bucket, mode = OssService._build_bucket()
        result = bucket.put_object_from_file(object_key, local_path)
        return {
            "status": result.status,
            "request_id": result.request_id,
            "auth_mode": mode,
        }

    @staticmethod
    def generate_presigned_get_url(object_key: str, expires: int = 600) -> str:
        bucket, _ = OssService._build_bucket()
        return bucket.sign_url("GET", object_key, expires, slash_safe=True)

    @staticmethod
    def object_exists(object_key: str) -> bool:
        bucket, _ = OssService._build_bucket()
        return bucket.object_exists(object_key)

    @staticmethod
    def normalize_object_key(
        skill_name: str, version: str, file_name: Optional[str] = None
    ) -> str:
        safe_skill = skill_name.strip().replace("\\", "/").strip("/")
        safe_version = str(version).strip().replace("/", "_")
        if file_name:
            suffix = file_name.strip().replace("\\", "/").split("/")[-1]
            return f"skills/{safe_skill}/{suffix}"
        return f"skills/{safe_skill}/{safe_version}.zip"
