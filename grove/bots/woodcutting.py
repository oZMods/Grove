"""Input-independent target policy. Exact menu identity is required before clicks."""
import time
import math
from enum import Enum
from grove.core.navigation import from_raw
from grove.core.stepping import next_step
AXES = {1351, 1349, 1353, 1355, 1357, 1359, 1361, 6739, 20011, 23673}

def walking_target(snapshot,destination):
    return next_step(snapshot,destination)

def choose(snapshot, log_id=1511, tree_tiles=None):
    inventory, player = snapshot['inventory'], snapshot['player']
    if not any(item['id'] in AXES for item in inventory):
        raise RuntimeError('Keep an axe in your inventory for this version.')
    if not (3140 <= player['x'] <= 3200 and 3390 <= player['y'] <= 3470) or player['plane'] != 0:
        raise RuntimeError('Outside the validated Varrock West Bank training area.')
    logs = [item for item in inventory if item['id'] == log_id]
    if player['route'] > 0:
        return {'kind': 'wait', 'reason': 'Walking'}
    if snapshot['bank_open']:
        if logs:
            for slot in snapshot['bank_slots']:
                if slot['id'] == log_id and any(item['slot'] == slot['slot'] for item in logs):
                    return {'kind': 'deposit', **slot}
            raise RuntimeError('No validated log bank slot.')
        if snapshot['bank_close']:
            return {'kind': 'close', 'point': snapshot['bank_close'], **(snapshot.get('bank_close_identity') or {})}
        raise RuntimeError('Bank close control is not mapped; close the bank manually.')
    if len(inventory) >= 28:
        if not logs:
            raise RuntimeError('Inventory full without selected logs; other items will not be deposited.')
        candidates = [obj for obj in snapshot['objects'] if obj['id'] == 10583 and
                      obj['x'] == 3186 and obj['y'] in (3438, 3440, 3442, 3444) and obj['point']]
        kind = 'bank'
    else:
        if player['animation'] != -1:
            return {'kind': 'wait', 'reason': 'Player animation active'}
        candidates = [obj for obj in snapshot['objects'] if obj['id'] in (1276, 1278) and obj['point']
                      and 3140 <= obj['x'] <= 3200 and 3390 <= obj['y'] <= 3470]
        if tree_tiles is not None:
            candidates = [obj for obj in snapshot['objects'] if
                          (obj['x'], obj['y']) in tree_tiles and obj.get('name') in ('Oak', 'Oak tree') and
                          'Chop down' in obj.get('operations', obj.get('ops', [])) and obj['point']]
        kind = 'tree'
    dimensions = snapshot.get('dimensions')
    if dimensions:
        width, height = dimensions
        candidates = [obj for obj in candidates if
                      20 <= obj['point'][0] < width-20 and 20 <= obj['point'][1] < height-40]
    if not candidates:
        if tree_tiles is not None and kind == 'bank':
            return walking_target(snapshot,(3185,3436))
        if kind == 'tree' and tree_tiles is not None and not any(
                (obj['x'], obj['y']) in tree_tiles and obj.get('name') in ('Oak', 'Oak tree')
                for obj in snapshot['objects']):
            return {'kind': 'wait', 'reason': 'Waiting for anchored oaks to respawn'}
        if kind == 'tree' and tree_tiles:
            destination=min(tree_tiles,key=lambda t:(t[0]-player['x'])**2+(t[1]-player['y'])**2)
            return walking_target(snapshot,destination)
        raise RuntimeError('No visible validated target; adjust camera or move nearer manually.')
    candidate = min(candidates, key=lambda obj: (obj['x'] - player['x']) ** 2 + (obj['y'] - player['y']) ** 2)
    # Scene classification is metadata; it must not replace the bot operation.
    return {**candidate, 'object_kind': candidate.get('kind', 'game_object'), 'kind': kind}

def menu_matches(target, snapshot, log_id=1511):
    entry = snapshot.get('default')
    if not entry:
        return False
    kind = target['kind']
    if kind == 'walk':
        return (entry['action']=='Walk here' and entry['x']==target['x'] and entry['y']==target['y'] and
                entry['world']==snapshot['player']['world_id'])
    if kind in ('tree', 'bank'):
        return (entry['action'] == ('Chop down' if kind == 'tree' else 'Bank') and
                entry['id'] == target['id'] and entry['x'] == target['x'] and
                entry['y'] == target['y'] and entry['world'] == snapshot['player']['world_id'])
    if kind == 'deposit':
        return (snapshot['bank_open'] and entry['id'] == 983043 and entry['slot'] == target['slot'] and
                entry['action'] in ('Deposit-All', 'Deposit-1', 'Deposit-5', 'Deposit-10') and
                any(item['id'] == log_id and item['slot'] == target['slot'] for item in snapshot['inventory']))
    return (kind == 'close' and snapshot['bank_open'] and entry['action'] == 'Close' and
            ('id' not in target or entry['id'] == target['id']) and
            ('slot' not in target or entry['slot'] == target['slot']))

def acknowledged(target, before, after, button_event, log_id=1511):
    logs = lambda s: sum(item['quantity'] for item in s['inventory'] if item['id'] == log_id)
    kind = target['kind']
    if kind == 'walk':
        return (after['player']['x'],after['player']['y']) != (before['player']['x'],before['player']['y'])
    if kind == 'tree':
        gained = after['xp'] > before['xp'] or logs(after) > logs(before)
        return gained or bool(button_event) and (after['player']['animation'] != -1 or after['player']['route'] > 0)
    if kind == 'bank': return after['bank_open']
    if kind == 'deposit': return logs(after) < logs(before)
    return kind == 'close' and not after['bank_open']

def settle_delay(target):
    return 1500 if target['kind'] == 'tree' else 600


class WoodcuttingPhase(str,Enum):
    SELECTING='selecting_oak'
    APPROACHING='approaching_oak'
    CHOPPING='chopping'
    TO_BANK='walking_to_bank'
    OPENING='opening_bank'
    DEPOSITING='depositing_logs'
    CLOSING='closing_bank'
    RETURNING='returning_to_oaks'
    RESPAWN='waiting_for_respawn'

class AnchoredOaks:
    """Capture a session's three nearby oaks once, retaining tiles across banking."""
    def __init__(self, clock=time.monotonic):
        self.anchor = None
        self.tiles = frozenset()
        self.clock = clock
        self.active_tile = None
        self.progress = None
        self.last_progress = None
        self.rejected_until = {}
        self.phase=WoodcuttingPhase.SELECTING

    def capture(self, snapshot):
        player = snapshot['player']
        if player['plane'] != 0 or snapshot['bank_open']:
            raise RuntimeError('Attach near the three oaks with the bank closed.')
        anchor = (player['x'], player['y'])
        candidates = {(obj['x'], obj['y']) for obj in snapshot['objects']
                      if obj.get('name') in ('Oak', 'Oak tree') and
                      'Chop down' in obj.get('operations', obj.get('ops', [])) and
                      (obj['x'] - anchor[0]) ** 2 + (obj['y'] - anchor[1]) ** 2 <= 100}
        if len(candidates) < 3:
            raise RuntimeError('Three live oaks within ten tiles are required to capture the anchor.')
        self.anchor = anchor
        self.tiles = frozenset(sorted(candidates, key=lambda p: (p[0]-anchor[0])**2 + (p[1]-anchor[1])**2)[:3])

    def load_profile(self, profile, snapshot):
        if snapshot['player']['plane'] != profile.plane:
            raise RuntimeError('Route profile is on a different plane.')
        known = {(obj['x'],obj['y']) for obj in snapshot['objects'] if
                 obj.get('name') in ('Oak','Oak tree') and 'Chop down' in obj.get('ops',())}
        if not profile.trees.issubset(known):
            # Reviewed coordinates stay valid when an oak has become a stump.
            # Require the route to be inside the loaded collision map instead.
            from grove.core.navigation import from_raw
            grid = from_raw(snapshot['collision']) if snapshot.get('collision') else None
            if grid is None or grid.plane != profile.plane or not all(grid.contains(tile) for tile in profile.trees):
                raise RuntimeError('Route oak tiles must be inside the loaded scene.')
        self.anchor, self.tiles = profile.anchor, profile.trees

    def choose(self, snapshot):
        if self.anchor is None:
            self.capture(snapshot)
        now = self.clock()
        progress = (snapshot.get('xp',0),sum(item['quantity'] for item in snapshot['inventory'] if item['id'] == 1521))
        if progress != self.progress:
            self.progress, self.last_progress = progress, now
        live_tiles = {(obj['x'],obj['y']) for obj in snapshot['objects'] if
                      obj.get('name') in ('Oak','Oak tree') and
                      'Chop down' in obj.get('operations',obj.get('ops',()))}
        working = self.active_tile is None or self.active_tile in live_tiles
        # Animation can remain set after depletion. Only recent progress on a live
        # target keeps chopping busy; a stopped animation immediately permits selection.
        busy = (snapshot['player']['animation'] != -1 and working and
                now-self.last_progress < 12)
        current = dict(snapshot,player=dict(snapshot['player']))
        current['ground_points'] = [tile for tile in snapshot.get('ground_points',())
                                   if self.rejected_until.get(('walk',tile['x'],tile['y']),0)<=now]
        if not busy:
            current['player']['animation'] = -1
        available = self.tiles - {tile for tile,until in self.rejected_until.items() if len(tile)==2 and until > now}
        if not available and not snapshot['bank_open'] and len(snapshot['inventory']) < 28:
            return {'kind':'wait','reason':'Waiting for anchored targets to become available'}
        target=choose(current,1521,available)
        if snapshot['bank_open']:
            self.phase=WoodcuttingPhase.DEPOSITING if target['kind']=='deposit' else WoodcuttingPhase.CLOSING
        elif len(snapshot['inventory'])>=28:
            self.phase=WoodcuttingPhase.OPENING if target['kind']=='bank' else WoodcuttingPhase.TO_BANK
        elif target['kind']=='walk': self.phase=WoodcuttingPhase.RETURNING
        elif target['kind']=='tree': self.phase=WoodcuttingPhase.APPROACHING
        elif snapshot['player']['route']>0:
            self.phase=WoodcuttingPhase.RETURNING if self.phase in (WoodcuttingPhase.CLOSING,WoodcuttingPhase.RETURNING) else WoodcuttingPhase.APPROACHING
        elif busy: self.phase=WoodcuttingPhase.CHOPPING
        else: self.phase=WoodcuttingPhase.RESPAWN
        return target

    def reject_target(self, target):
        if target['kind'] == 'tree':
            self.rejected_until[(target['x'],target['y'])] = self.clock()+5
        elif target['kind'] == 'walk':
            self.rejected_until[('walk',target['x'],target['y'])] = self.clock()+10

    def menu_matches(self, target, snapshot):
        return menu_matches(target, snapshot, 1521)

    def acknowledged(self, target, before, after, button_event):
        success = acknowledged(target, before, after, button_event, 1521)
        if success and target['kind'] == 'tree':
            self.active_tile = (target['x'],target['y'])
            self.last_progress = self.clock()
            self.progress = (after.get('xp',0),sum(item['quantity'] for item in after['inventory'] if item['id'] == 1521))
        elif success:
            self.active_tile = None
        return success
