"""Public release identity; contains no private signing material."""

import base64
import hashlib

HOST_NAME = "com.saveit4u.downloader"
PUBLIC_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAltBYcTBbPUMmt+2ii8QrY08O08IMI57GTdLGtSY5xLZNK7pR1x0aLMttAQSehSBRC6yyUYIcCkE4TnGefeYixDN+K7+JTRQvbUYwPVpQPb3xvH2J0Z1AFCntWnWtdAbFWkcaoPN6q9cf4ePMnzojQ/RqWqndCTQixKBO5k1pMmz5UOg8WWW1nETl08vinXnvly8omU4s29fqrJ3dhMQlrJbaLZ0m1+rrLV5cR76KDzmbwdFKGuT+X8oYDVgpJDPmuKS5vYHTeO3E0rpmpimbfQple/FSr1lfjwo7uAmJeZ5efilcErKGfpXiWiUr+zGlp7Yx73Ou5snizXCCJPIZ+QIDAQAB"


def extension_id(key=PUBLIC_KEY):
    digest = hashlib.sha256(base64.b64decode(key, validate=True)).hexdigest()[:32]
    return "".join(chr(97 + int(char, 16)) for char in digest)


def allowed_origins():
    return {f"chrome-extension://{extension_id()}/"}
