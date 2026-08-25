# -*- coding: utf-8 -*-
"""新点(Epoint)框架 SM2 请求加密 + AES 响应解密。

前端约定（见站点 sm2Util.js / biz_common.js）：

- 请求体先包一层：``{"params": <inner>, "token": "<token>"}``，整体做 base64，
  再用站点下发的 SM2 公钥加密（C1C3C2 模式），最后十六进制拼接 ``"04" + hex(cipher)``。
- 请求头带 ``encrypt: 1``。
- 响应为 ``base64(AES-CBC 密文)``，用固定 key/iv 解密（PKCS7 填充）。
"""
from __future__ import absolute_import

import base64
import json

try:
    from urllib.parse import unquote
except ImportError:  # pragma: no cover
    from urllib import unquote

from gmssl import sm2
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


class EpointCrypto(object):
    def __init__(self, public_key, aes_key, aes_iv, token="Epoint_WebSerivce_**##0601", sm2_mode=0):
        # type: (str, str, str, str, int) -> None
        self.public_key = public_key
        self.aes_key = aes_key.encode("utf-8")
        self.aes_iv = aes_iv.encode("utf-8")
        self.token = token
        self.sm2_mode = sm2_mode

    def encrypt(self, inner):
        # type: (object) -> str
        """加密内层请求体，返回可直接发送的请求 body 字符串。"""
        if isinstance(inner, str):
            inner = json.loads(inner)
        wrapped = json.dumps({"params": inner, "token": self.token}, ensure_ascii=False)
        b64 = base64.b64encode(wrapped.encode("utf-8")).decode("ascii")
        crypt = sm2.CryptSM2(public_key=self.public_key, private_key="", mode=self.sm2_mode)
        cipher = crypt.encrypt(b64.encode("ascii"))
        return "04" + cipher.hex()

    def decrypt(self, text):
        # type: (str) -> str
        """解密响应文本，返回明文字符串。"""
        if not text:
            return ""
        cipher_bytes = base64.b64decode(unquote(text))
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_iv)
        plain = cipher.decrypt(cipher_bytes)
        return unpad(plain, AES.block_size).decode("utf-8", errors="replace")
