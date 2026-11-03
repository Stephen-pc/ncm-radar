"""网易云 weapi 加密：AES-128-CBC 两轮 + RSA。"""
import base64
import json
import random
import string

from Crypto.Cipher import AES

_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)
_PUBKEY = "010001"
_NONCE = "0CoJUm6Qyw8W8jud"
_IV = "0102030405060708"


def _pad(text: str) -> str:
    n = 16 - len(text) % 16
    return text + chr(n) * n


def _aes(text: str, key: str) -> str:
    cipher = AES.new(key.encode(), AES.MODE_CBC, _IV.encode())
    return base64.b64encode(cipher.encrypt(_pad(text).encode())).decode()


def _rsa(text: str) -> str:
    raw = int(text[::-1].encode().hex(), 16)
    return format(pow(raw, int(_PUBKEY, 16), int(_MODULUS, 16)), "x").zfill(256)


def encrypt(payload: dict) -> dict:
    """把明文字典转成 {params, encSecKey}。"""
    secret = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    first = _aes(json.dumps(payload), _NONCE)
    return {"params": _aes(first, secret), "encSecKey": _rsa(secret)}
