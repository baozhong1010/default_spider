# -*- coding: utf-8 -*-
"""可选的请求/响应加解密钩子。

站点配置里通过 ``crypto`` 段启用。每个实现类需要提供两个方法：

- ``encrypt(inner)``: 接收内层请求体（dict 或 JSON 字符串），返回可直接作为 HTTP body 的字符串。
- ``decrypt(text)``: 接收加密的响应文本，返回解密后的明文字符串。
"""
from __future__ import absolute_import


def create_crypto(crypto_cfg):
    # type: (object) -> object
    if crypto_cfg is None or not getattr(crypto_cfg, "enabled", False):
        return None

    module = getattr(crypto_cfg, "module", "epoint")

    if module == "epoint":
        from .epoint import EpointCrypto
        cls = EpointCrypto
    else:
        raise ValueError("Unknown crypto module: %s" % module)

    return cls(
        public_key=crypto_cfg.public_key,
        aes_key=crypto_cfg.aes_key,
        aes_iv=crypto_cfg.aes_iv,
        token=getattr(crypto_cfg, "token", "Epoint_WebSerivce_**##0601"),
        sm2_mode=getattr(crypto_cfg, "sm2_mode", 0),
    )
