from dataclasses import dataclass


@dataclass
class EncryptionParams:
    """Encryption parameters for video progress logging"""

    clazzId: str
    jobid: str
    objectId: str
    playingTime: int
    duration: int
    userid: str
