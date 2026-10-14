from dataclasses import dataclass
from enum import Enum
import math

class RuntimeState(str, Enum):
    DETACHED = 'detached'
    READY = 'ready'
    COUNTDOWN = 'countdown'
    TARGETING = 'targeting'
    WAITING = 'waiting'
    VERIFYING = 'verifying'
    STOPPED = 'stopped'
    FAILED = 'failed'
    CLOSED = 'closed'

@dataclass(frozen=True)
class RuntimeConfig:
    countdown_ms: int = 5000
    poll_ms: int = 600
    hover_ms: int = 300
    action_timeout_seconds: float = 15
    bank_timeout_seconds: float = 30
    idle_timeout_seconds: float = 180
    event_limit: int = 2000
    menu_retry_limit: int = 3

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be a finite positive number.')
            if name.endswith('_ms') or name in ('event_limit','menu_retry_limit'):
                if not isinstance(value,int): raise ValueError(f'{name} must be an integer.')
