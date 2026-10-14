"""Snapshot-derived events; subscriber failures are recorded and isolated."""
from dataclasses import dataclass
from collections import deque

@dataclass(frozen=True)
class StateEvent:
    kind:str
    captured_at:float
    before:object
    after:object

class EventHub:
    def __init__(self):
        self.previous=None
        self.listeners={}
        self.errors=deque(maxlen=20)
    def subscribe(self,kind,callback):
        if not callable(callback): raise ValueError('A subscriber must be callable.')
        self.listeners.setdefault(kind,[]).append(callback)
        def unsubscribe():
            listeners=self.listeners.get(kind,[])
            if callback in listeners:listeners.remove(callback)
        return unsubscribe
    def update(self,snapshot):
        previous,self.previous=self.previous,snapshot
        if previous is None:return ()
        comparisons=[('inventory_changed',tuple((i.slot,i.id,i.quantity) for i in previous.inventory.items),tuple((i.slot,i.id,i.quantity) for i in snapshot.inventory.items)),
                     ('equipment_changed',previous.equipment.items,snapshot.equipment.items),
                     ('bank_changed',previous.bank.opened,snapshot.bank.opened),
                     ('position_changed',previous.player.position,snapshot.player.position),
                     ('animation_changed',previous.player.animation,snapshot.player.animation),
                     ('world_changed',previous.player.world_instance_id,snapshot.player.world_instance_id),
                     ('game_state_changed',previous.game_state,snapshot.game_state),
                     ('skills_changed',previous.skills,snapshot.skills)]
        # Lightweight action snapshots do not contain scene collections.
        if previous.objects and snapshot.objects:
            comparisons.append(('objects_changed',frozenset((o.id,o.x,o.y) for o in previous.objects),frozenset((o.id,o.x,o.y) for o in snapshot.objects)))
        events=tuple(StateEvent(kind,snapshot.captured_at,before,after) for kind,before,after in comparisons if before!=after)
        for event in events:
            for callback in tuple(self.listeners.get(event.kind,()))+tuple(self.listeners.get('*',())):
                try:callback(event)
                except Exception as error:self.errors.append({'event':event.kind,'error_type':type(error).__name__,'message':str(error)})
        return events
    def close(self): self.listeners.clear();self.previous=None
