"""Local Python API. No network endpoint, credentials, or remote input surface."""
import time
from collections import deque
from grove.api.models import Bank, Inventory, Item, MenuAction, Player, Point, Snapshot, WorldObject, GroundTile
from grove.api.query import Coordinate
from grove.api.models import Actor,Rectangle,InterfaceComponent,Skill,Camera,GroundItem
from grove.core.navigation import from_raw
from grove.core.events import EventHub
from grove.core.execution import ConditionTask
from grove.api.banking import Banking
from grove.core.session import ClientSession
from grove.api.contracts import Capabilities, ActionExpectation, DetachedError, StaleStateError, ActionMismatchError, UnsupportedCapabilityError, InputAcknowledgmentError

def point(value):
    return Point(*value) if value is not None else None

def menu_action(value):
    if value is None: return None
    return MenuAction(value['action'], value['id'], value['slot'], value['world'], value['x'], value['y'], value['target'])

def interface_component(c):
    return InterfaceComponent(c['id'],c['sub_id'],c['group'],c['parent_id'],Rectangle(*c['bounds']),c['text'],tuple(c['ops']),c['visible_candidate'],c['processed_frame'],c['item_id'],c['quantity'],
                              c.get('hidden',False),tuple(c.get('scroll',(0,0))),Rectangle(*c['clipped_bounds']) if c.get('clipped_bounds') else None)

def convert(raw, captured_at=None):
    player = raw['player']
    definitions={entry['id']:entry for entry in raw.get('item_definitions',())}
    def items(entries,capacity=28):
        return Inventory(tuple(Item(item['slot'],item['id'],item['quantity'],definitions.get(item['id'],{}).get('name',''),
                                    tuple(definitions.get(item['id'],{}).get('operations',()))) for item in entries),capacity)
    inventory = items(raw['inventory'])
    return Snapshot(raw['pid'], time.monotonic() if captured_at is None else captured_at,
                    Player(player['world_id'], player['x'], player['y'], player['plane'], player['route'], player['animation']),
                    inventory,
                    tuple(WorldObject(obj['id'], obj['x'], obj['y'], point(obj['point']), obj.get('name', ''), tuple(obj.get('ops', ())),obj.get('kind','game_object')) for obj in raw['objects']),
                    Bank(raw['bank_open'], tuple(item for item in inventory.items if any(slot['slot'] == item.slot and slot['id'] == item.id for slot in raw['bank_slots'])), point(raw['bank_close']),
                         (raw['bank_close_identity']['id'],raw['bank_close_identity']['slot']) if raw.get('bank_close_identity') else None),
                    tuple(menu_action(entry) for entry in raw['menu']), menu_action(raw['default']),
                    raw['level'], raw['xp'], tuple(raw['dimensions']),
                    tuple(GroundTile(Coordinate(tile['x'],tile['y'],player['plane']),point(tile['point'])) for tile in raw.get('ground_points',())),
                    tuple(Actor(a['kind'],a['index'],a['id'],a['name'],a['x'],a['y'],a['plane'],a['world_instance_id'],a['animation'],a['route'],point(a['point']),tuple(a['ops'])) for a in raw.get('actors',())),
                    tuple(interface_component(c) for c in raw.get('interfaces',())),
                    items(raw.get('equipment',()),14),items(raw.get('bank_items',()),2048),
                    tuple(Skill(**s) for s in raw.get('skills',())),Camera(**raw['camera']) if raw.get('camera') else None,
                    from_raw(raw['collision']) if raw.get('collision') else None,
                    raw.get('game_state',-1),raw.get('tick',-1),raw.get('logged_in',False),
                    tuple(GroundItem(g['id'],g['quantity'],g['x'],g['y'],g['plane'],g['name'],tuple(g['ops']),point(g['point'])) for g in raw.get('ground_items',())))


class ClientAPI:
    def __init__(self, session):
        self.session = session
        self.last_raw = None
        self.last_snapshot = None
        self.closed = False
        self.last_hover_point = None
        self.event_history = deque(maxlen=512)
        self.hover_revision=0
        self.consumed_hover_revision=None
        self.events=EventHub()
        self.tasks=[]
        self.banking = Banking(self)
        self.capabilities = Capabilities()
        if self.session.input is None:
            self.capabilities = Capabilities(self.capabilities.supported - {'verified_window_input'})

    def items(self,container_id=93):
        if self.closed:raise DetachedError('Client API is detached.')
        reader=self.session.reader
        entries=reader.inventory(container_id)
        definitions={item['id']:reader.item_definition(item['id']) for item in entries}
        return Inventory(tuple(Item(item['slot'],item['id'],item['quantity'],(definitions[item['id']] or {}).get('name',''),
                                    tuple((definitions[item['id']] or {}).get('operations',()))) for item in entries),
                         28 if container_id==93 else 14 if container_id==94 else 2048)

    def varbit(self, varbit_id):
        if self.closed: raise DetachedError('Client API is detached.')
        return self.session.reader.varbit(varbit_id)

    def item_definition(self,item_id):
        if self.closed:raise DetachedError('Client API is detached.')
        return self.session.reader.item_definition(item_id)

    @classmethod
    def attach(cls, pid=None, read_only=False): return cls(ClientSession.connect(pid, read_only=read_only))
    @property
    def pid(self): return self.session.reader.pid

    def snapshot(self,interface_groups=None):
        if self.closed: raise DetachedError('Client API is detached.')
        self.last_raw = self.session.reader.snapshot() if interface_groups is None else self.session.reader.snapshot(interface_groups=interface_groups)
        self.last_snapshot = convert(self.last_raw)
        self.events.update(self.last_snapshot)
        return self.last_snapshot

    def action_snapshot(self):
        if self.closed: raise DetachedError('Client API is detached.')
        reader=self.session.reader
        self.last_raw=reader.action_snapshot() if hasattr(reader,'action_snapshot') else reader.snapshot()
        self.last_snapshot=convert(self.last_raw)
        self.events.update(self.last_snapshot)
        return self.last_snapshot

    def raw_snapshot(self):
        # Compatibility for the first bot policy; new bots should use snapshot().
        self.snapshot()
        return self.last_raw

    def arm_input(self):
        if self.closed: raise DetachedError('Client API is detached.')
        self.capabilities.require('verified_window_input')
        self.session.input.foreground()
        self.session.input.install()

    def disarm_input(self):
        if self.session.input: self.session.input.close()

    def hover(self, screen_point):
        if self.closed: raise DetachedError('Client API is detached.')
        self.capabilities.require('verified_window_input')
        if self.last_snapshot is None: raise RuntimeError('Read a snapshot before targeting.')
        if time.monotonic()-self.last_snapshot.captured_at > 2:
            raise StaleStateError('Refresh the snapshot before targeting.')
        self.collect_input_events((0,3,4,6,7))
        self.session.input.move((screen_point.x, screen_point.y), self.last_snapshot.dimensions)
        self.last_hover_point = screen_point
        self.hover_revision+=1

    def hover_object(self, obj, action):
        """Resolve a fresh object and return the identity to verify after movement."""
        snapshot = self.snapshot()
        current = next((candidate for candidate in snapshot.objects if
                        (candidate.id,candidate.x,candidate.y) == (obj.id,obj.x,obj.y)), None)
        if current is None or current.screen is None or action not in current.operations:
            raise ActionMismatchError('Object is gone, unprojected, or lacks the requested action.')
        self.hover(current.screen)
        return ActionExpectation(action,current.id,snapshot.player.world_instance_id,current.x,current.y)

    def hover_deposit(self, slot, item_id, action='Deposit-All'):
        if action not in ('Deposit-All','Deposit-1','Deposit-5','Deposit-10'):
            raise ActionMismatchError('Unsupported deposit action.')
        snapshot = self.snapshot()
        item = snapshot.inventory.get_slot(slot)
        target = next((entry for entry in self.last_raw['bank_slots'] if entry['slot'] == slot and entry['id'] == item_id), None)
        if not snapshot.bank.opened or item is None or item.id != item_id or target is None:
            raise ActionMismatchError('Bank inventory slot does not match the requested item.')
        self.hover(point(target['point']))
        return ActionExpectation(action,983043,snapshot.player.world_instance_id,slot=slot,inventory_item_id=item_id,menu_world_instance_id=-1)

    def hover_bank_close(self):
        snapshot = self.snapshot()
        bank = snapshot.bank
        if not bank.opened or bank.close_point is None or bank.close_identity is None:
            raise ActionMismatchError('A validated bank close control is not available.')
        self.hover(bank.close_point)
        return ActionExpectation('Close',bank.close_identity[0],snapshot.player.world_instance_id,
                                 slot=bank.close_identity[1],menu_world_instance_id=-1)

    def hover_withdraw(self, slot, item_id, action='Withdraw-1'):
        if action not in ('Withdraw-1','Withdraw-5','Withdraw-10','Withdraw-All','Withdraw-All-but-1'):
            raise ActionMismatchError('Unsupported withdrawal action.')
        snapshot = self.action_snapshot()
        item = snapshot.bank_items.get_slot(slot)
        if not snapshot.bank.opened or item is None or item.id != item_id or item.quantity <= 0:
            raise ActionMismatchError('Bank storage slot does not match the requested item.')
        component = next((entry for entry in self.interfaces((12,)) if
                          entry.id == (12 << 16 | 12) and entry.sub_id == slot and
                          entry.item_id == item_id and entry.quantity > 0), None)
        if component is None:
            raise ActionMismatchError('Bank storage slot is not currently visible.')
        expected = self.hover_interface(component, action)
        from dataclasses import replace
        return replace(expected,bank_item_id=item_id)

    def hover_ground_tile(self, coordinate):
        snapshot=self.snapshot()
        tile=next((tile for tile in snapshot.ground_tiles if tile.position==coordinate),None)
        if tile is None: raise ActionMismatchError('Ground tile is not projected in the current viewport.')
        self.hover(tile.screen)
        return ActionExpectation('Walk here',-1,snapshot.player.world_instance_id,coordinate.x,coordinate.y)

    def interfaces(self,group_ids=None):
        if self.closed: raise DetachedError('Client API is detached.')
        reader=self.session.reader
        state=reader.q(reader.base+0xE98C18)
        return tuple(interface_component(c)
                     for c in reader.interfaces(state,group_ids))

    def hover_interface(self,component,action):
        snapshot=self.action_snapshot()
        current=next((entry for entry in self.interfaces((component.group,)) if
                      (entry.id,entry.sub_id)==(component.id,component.sub_id)),None)
        if current is None or current.screen is None or action not in current.operations:
            raise ActionMismatchError('Interface component is absent, unprojected, or lacks the action.')
        self.hover(current.screen)
        return ActionExpectation(action,current.id,snapshot.player.world_instance_id,slot=current.sub_id,menu_world_instance_id=-1)

    def hover_actor(self,actor,action):
        snapshot=self.snapshot()
        current=next((entry for entry in snapshot.actors if (entry.kind,entry.index,entry.world_instance_id)==
                      (actor.kind,actor.index,actor.world_instance_id)),None)
        if current is None or current.screen is None or current.kind=='npc' and action not in current.operations:
            raise ActionMismatchError('Actor is unavailable or does not offer the action.')
        self.hover(current.screen)
        return ActionExpectation(action,current.index,current.world_instance_id)

    def hover_ground_item(self,item,action='Take'):
        snapshot=self.snapshot()
        current=next((entry for entry in snapshot.ground_items if
                      (entry.id,entry.x,entry.y,entry.plane)==(item.id,item.x,item.y,item.plane)),None)
        if current is None or current.screen is None or action not in current.operations:
            raise ActionMismatchError('Ground item is gone, unprojected or lacks the requested action.')
        self.hover(current.screen)
        return ActionExpectation(action,current.id,snapshot.player.world_instance_id,current.x,current.y)

    def camera_key_down(self,key):
        if self.closed: raise DetachedError('Client API is detached.')
        self.capabilities.require('verified_window_input')
        self.session.input.key_down(key)

    def camera_key_up(self,key):
        if self.session.input: self.session.input.key_up(key)

    def plan_path(self,destination,adjacent=False):
        snapshot=self.snapshot()
        if snapshot.collision is None: raise UnsupportedCapabilityError('Collision data is unavailable.')
        if destination.plane!=snapshot.player.plane: raise UnsupportedCapabilityError('Use a mapped transition for a different plane.')
        return tuple(Coordinate(x,y,destination.plane) for x,y in snapshot.collision.path((snapshot.player.x,snapshot.player.y),(destination.x,destination.y),adjacent))

    def plan_step(self,destination):
        snapshot=self.snapshot()
        if destination.plane!=snapshot.player.plane:
            raise UnsupportedCapabilityError('Cross-plane transitions require a mapped transport.')
        from grove.core.stepping import next_step
        return next_step(self.last_raw,(destination.x,destination.y))

    def subscribe(self,kind,callback): return self.events.subscribe(kind,callback)
    def wait_until(self,scheduler,condition,timeout_seconds,interval_ms=100,on_complete=None):
        if self.closed: raise DetachedError('Client API is detached.')
        task=ConditionTask(scheduler,condition,timeout_seconds,interval_ms,on_complete)
        self.tasks=[t for t in self.tasks if t.status in ('pending','running')]
        self.tasks.append(task)
        return task.start()

    def click_expected(self, expectation):
        return self.click_verified(expectation.matches)

    def click_verified(self, predicate, scheduler=None):
        self.capabilities.require('verified_window_input')
        if self.consumed_hover_revision==self.hover_revision:
            raise InputAcknowledgmentError('This hover was already used for a click; re-hover before another action.')
        # Always refresh before evaluating the caller's expected action identity.
        snapshot = self.action_snapshot()
        if not self.session.input.audit_ok(): raise RuntimeError('Input is not armed or no hover was sent.')
        if not predicate(snapshot): raise ActionMismatchError('Expected action does not match fresh client state.')
        self.confirm_input_event((0,), Point(*self.session.input.target), self.session.input.sent_at)
        self.consumed_hover_revision=self.hover_revision
        if scheduler is None:
            self.session.input.click()
        else:
            self.session.input.click(scheduler)
        return snapshot  # Posting a click is not proof of gameplay completion.

    def confirm_input_event(self, kinds, screen_point, sent_after_ms, required=True):
        self.collect_input_events(kinds)
        matches = [event for event in self.event_history if event['kind'] in kinds
                   if sent_after_ms <= event['stamp'] <= sent_after_ms + 2500 and
                   abs(event['x'] - screen_point.x) <= 2 and abs(event['y'] - screen_point.y) <= 2]
        if not matches:
            if required: raise InputAcknowledgmentError('No input event matched the generated point/time.')
            return None
        return max(matches, key=lambda event: event['stamp'])

    def collect_input_events(self,kinds):
        events=self.session.reader.input_events(kinds)
        known={(e['kind'],e['stamp'],e['x'],e['y']) for e in self.event_history}
        for event in events:
            key=(event['kind'],event['stamp'],event['x'],event['y'])
            if key not in known:
                self.event_history.append(event)
                known.add(key)

    def close(self):
        if not self.closed:
            for task in self.tasks:task.cancel()
            self.events.close()
            self.session.close()
            self.closed = True

    def __enter__(self): return self
    def __exit__(self, *unused): self.close()
