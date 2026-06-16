import base64

import pyaes

from api.config import GlobalConst as gc


def pkcs7_unpadding(string):
    return string[0 : -ord(string[-1])]


def pkcs7_padding(s, block_size=16):
    bs = block_size
    return s + (bs - len(s) % bs) * chr(bs - len(s) % bs).encode()


def split_to_data_blocks(byte_str, block_size=16):
    length = len(byte_str)
    j, y = divmod(length, block_size)
    blocks = []
    shenyu = j * block_size
    for i in range(j):
        start = i * block_size
        end = (i + 1) * block_size
        blocks.append(byte_str[start:end])
    stext = byte_str[shenyu:]
    if stext:
        blocks.append(stext)
    return blocks


class AESCipher:
    """AES-CBC cipher for the Chaoxing passport login (passport2.chaoxing.com/fanyalogin).

    SECURITY NOTE (audit F44): both the key and the IV are the SAME hardcoded
    constant (gc.AESKey = "u2oh6Vu^HWe4_AES"). Reusing the key as a static IV is a
    cryptographic anti-pattern (ciphertext is deterministic, so equal plaintexts
    encrypt identically, leaking equality).

    This is, however, an INTEROPERABILITY REQUIREMENT, not a free design choice:
    the key and the IV==key construction are dictated by Chaoxing's frontend login
    JavaScript. The encrypted username/password must decrypt correctly on
    Chaoxing's server, so rotating the key or introducing a per-message random IV
    here would break login and is therefore intentionally NOT done.

    Confidentiality of the credentials in transit rests on TLS (https), not on
    this cipher. This AESCipher is used ONLY for the Chaoxing login POST
    (auth_service.py) and must never be repurposed for at-rest credential storage;
    any non-Chaoxing use must use a per-message random IV prepended to the
    ciphertext instead.
    """

    def __init__(self):
        # key and iv are intentionally the same Chaoxing-mandated constant; see
        # the class docstring. Do not "fix" this to a random IV without breaking
        # Chaoxing login.
        self.key = str(gc.AESKey).encode("utf8")
        self.iv = str(gc.AESKey).encode("utf8")

    def encrypt(self, plaintext: str):
        ciphertext = b""
        cbc = pyaes.AESModeOfOperationCBC(self.key, self.iv)
        plaintext = plaintext.encode("utf-8")
        blocks = split_to_data_blocks(pkcs7_padding(plaintext))
        for b in blocks:
            ciphertext = ciphertext + cbc.encrypt(b)
        base64_text = base64.b64encode(ciphertext).decode("utf8")
        return base64_text

    # def decrypt(self, ciphertext: str):
    #     cbc = pyaes.AESModeOfOperationCBC(self.key, self.iv)
    #     ciphertext.encode('utf8')
    #     ciphertext = base64.b64decode(ciphertext)
    #     ptext = b""
    #     for b in split_to_data_blocks(ciphertext):
    #         ptext = ptext + cbc.decrypt(b)
    #     return pkcs7_unpadding(ptext.decode())
