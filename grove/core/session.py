from dataclasses import dataclass
from grove.clients.osrs import ClientState
from grove.input.window_messages import WindowMouse

@dataclass
class ClientSession:
    reader: ClientState
    input: WindowMouse | None

    @classmethod
    def connect(cls, pid=None, read_only=False):
        reader = ClientState(pid)
        try:
            if read_only:
                reader.snapshot()
                return cls(reader, None)
            if not getattr(reader,'profile',{'input_validated':True})['input_validated']:
                raise RuntimeError('This build is available for read-only validation; input profile is not yet approved.')
            adapter = WindowMouse(reader.pid, reader)
            snapshot = reader.snapshot()
            if tuple(adapter.geometry()[2:]) != tuple(snapshot['dimensions']):
                raise RuntimeError('Client geometry and renderer dimensions disagree.')
            return cls(reader, adapter)
        except Exception:
            reader.close()
            raise

    def close(self):
        try:
            if self.input: self.input.close()
        finally:
            self.reader.close()
