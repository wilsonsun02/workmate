import base64
import hashlib
import struct
from Crypto.Cipher import AES
from defusedxml.ElementTree import fromstring


class WeChatCrypto:
    """企业微信消息加解密"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def decrypt(
        self, msg_signature: str, timestamp: str, nonce: str, encrypt_msg: str
    ) -> dict:
        """解密消息"""
        # 1. 验证签名
        signature = self._generate_signature(timestamp, nonce, encrypt_msg)
        if signature != msg_signature:
            raise ValueError("签名验证失败")

        # 2. AES解密
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        decrypted = cipher.decrypt(base64.b64decode(encrypt_msg))

        # 3. 去除PKCS7填充
        pad = decrypted[-1]
        content = decrypted[16:-pad]

        # 4. 提取消息内容
        xml_len = struct.unpack("!I", content[:4])[0]
        xml_content = content[4 : 4 + xml_len].decode("utf-8")
        from_corp_id = content[4 + xml_len :].decode("utf-8")

        if from_corp_id != self.corp_id:
            raise ValueError("CorpID 校验失败")

        # 5. 解析XML (使用 defusedxml 防御 XXE)
        root = fromstring(xml_content)
        return {child.tag: child.text for child in root}

    def _generate_signature(self, timestamp: str, nonce: str, encrypt_msg: str) -> str:
        """生成签名"""
        sort_list = sorted([self.token, timestamp, nonce, encrypt_msg])
        sha1 = hashlib.sha1()
        sha1.update("".join(sort_list).encode("utf-8"))
        return sha1.hexdigest()
