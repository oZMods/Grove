"""Bot lifecycle and verification, independent of dashboard widgets."""
import time
import random
import math
from grove.input.motion import bezier_path
from grove.api.client import ClientAPI
from grove.api.models import Point
from grove.api.contracts import ActionMismatchError,InputAcknowledgmentError
from grove.input.win32 import U
from grove.bots.registry import WOODCUTTING, instantiate
from grove.core.config import RuntimeConfig, RuntimeState
from grove.core.recovery import RecoveryBudget, MovementProgress

class BotRuntime:
    def __init__(self, scheduler, emit, definition=WOODCUTTING, config=None, profile=None):
        self.root, self.emit = scheduler, emit
        self.definition, self.policy = instantiate(definition)
        self.config = config or RuntimeConfig()
        self.profile = profile
        self.state = RuntimeState.DETACHED
        self.last_error = None
        self.wait_since = None
        self.completed_actions = 0
        self.metrics_started = None
        self.metrics_xp = 0
        self.logs_gained = self.logs_banked = self.bank_deposits = 0
        self.menu_retries = 0
        self.close_recoveries = 0
        self.wait_reason = None
        self.last_wait_report = 0
        self.idle_motion_at = 0
        self.idle_motion_anchor = None
        self.ack_retries=0
        self.camera_attempts=0
        self.recovery_budget = RecoveryBudget()
        self.movement_progress = MovementProgress()
        self.stalled_replans = 0
        self.last_acknowledged_kind = None
        self.camera_left_sign=None
        self.camera_probe=False
        self.background_probe = False
        self.background_run = False
        self.background_probe_passed = False
        self.background_foreground = None
        self.reader = self.mouse = self.session = None
        self.api = None
        self.running = self.probing = self.probe_passed = False
        self.closed = False
        self.generation = 0
        self.snapshot = self.target = None
        self.offset_index = 0
        self.offsets = [(0, 0), (0, -20), (0, 20), (-20, 0), (20, 0), (0, -40), (0, 40)]
        self.records = []
        self.root.after(100, self.watch_stop)

    def log(self, text, **data):
        event = {'time': time.time(), 'text': text, **data}
        self.records.append(event)
        self.records = self.records[-self.config.event_limit:]
        self.emit('event', event)

    def read(self):
        snapshot = self.api.raw_snapshot()
        if self.running and not self.probing and self.snapshot is not None:
            count = lambda state: sum(i['quantity'] for i in state['inventory'] if i['id'] == 1521)
            self.logs_gained += max(0, count(snapshot)-count(self.snapshot))
        self.snapshot = snapshot
        p = snapshot['player']
        self.emit('snapshot', snapshot)
        return snapshot

    def set_state(self, state):
        self.state = state
        self.emit('lifecycle', {'state': state.value, 'completed_actions': self.completed_actions})

    def select_definition(self, definition):
        self.stop()
        self.definition, self.policy = instantiate(definition)
        self.probe_passed = False

    def attach(self, pid=None):
        self.stop()
        if self.api:
            self.api.close()
        self.reader = self.mouse = self.session = None
        self.api = None
        self.probe_passed = False
        self.definition, self.policy = instantiate(self.definition)
        try:
            self.api = ClientAPI.attach(pid)
            self.session = self.api.session
            self.reader, self.mouse = self.session.reader, self.session.input
            self.read()
            self.probe_passed = False
            self.log('Attached read-only', pid=self.reader.pid, size=self.snapshot['dimensions'])
            self.last_error = None
            self.set_state(RuntimeState.READY)
        except Exception as error:
            if self.api: self.api.close()
            self.api = self.reader = self.mouse = self.session = None
            self.snapshot = None
            self.set_state(RuntimeState.DETACHED)
            self.log('Attach failed: ' + str(error))

    def arm(self, probe, background=False, background_run=False):
        if background and not probe:
            raise RuntimeError('Background clicks are not enabled; use the movement-only probe.')
        if not self.reader or not self.mouse:
            self.log('Attach successfully first.')
            return
        if not probe and not self.probe_passed and not background_run:
            self.log('Run the movement-only probe before Start.')
            return
        self.stop()
        self.probing = probe
        self.close_recoveries = 0
        self.background_probe = background
        self.background_run = background_run
        self.mouse.background_movement_only = background
        self.mouse.background_enabled = background_run
        self.camera_probe=False
        self.menu_retries = 0
        self.wait_since = None
        self.recovery_budget = RecoveryBudget()
        self.movement_progress = MovementProgress()
        self.stalled_replans = 0
        self.set_state(RuntimeState.COUNTDOWN)
        self.last_acknowledged_kind = None
        token = self.generation
        self.log('Background movement probe in 5 seconds; keep another app foreground and the game unminimized. No click will be sent.'
                 if background else 'Focus-independent run starts in 5 seconds; keep the game unminimized. You can use other apps.'
                 if background_run else 'Focus the game now. Starting in 5 seconds; leave the mouse still.')
        self.root.after(self.config.countdown_ms, lambda: self.begin(token))

    def begin(self, token):
        if token != self.generation:
            return
        try:
            if self.background_probe:
                self.background_foreground = U.GetForegroundWindow()
            self.mouse.foreground()
            if self.policy and self.policy.anchor is None:
                snapshot = self.read()
                if self.profile: self.policy.load_profile(self.profile,snapshot)
                else: self.policy.capture(snapshot)
                self.log('Woodcutting route initialized',anchor=self.policy.anchor,trees=sorted(self.policy.tiles))
            self.mouse.failure = None
            self.api.arm_input()
            if not self.probing:
                self.metrics_started = time.monotonic()
                self.metrics_xp = self.snapshot['xp']
                self.logs_gained = self.logs_banked = self.bank_deposits = 0
                self.completed_actions = 0
            self.running = True
            self.next_target(token)
        except Exception as error:
            self.fail(error)

    def later(self, delay, function, token):
        def run():
            if token == self.generation and self.running:
                try:
                    function(token)
                except Exception as error:
                    self.fail(error)
        self.root.after(delay, run)

    def next_target(self, token):
        self.mouse.foreground()
        prior = self.snapshot
        snapshot = self.read()
        self.recovery_budget.observe(snapshot)
        if self.movement_progress.observe(snapshot['player']):
            if self.stalled_replans >= 2:
                raise RuntimeError('Navigation remained stalled after two fresh replans.')
            if not self.target or self.target['kind'] != 'wait' or self.last_acknowledged_kind != 'walk':
                raise RuntimeError('Movement stalled without an acknowledged action; no automatic replay.')
            self.stalled_replans += 1
            snapshot = dict(snapshot,player=dict(snapshot['player'],route=0))
            self.movement_progress.changed_at = time.monotonic()
            self.log('Navigation stalled; selecting a fresh collision-safe target',attempt=self.stalled_replans)
        elif prior and (prior['player']['x'],prior['player']['y']) != (snapshot['player']['x'],snapshot['player']['y']):
            self.stalled_replans = 0
        if prior and snapshot['xp'] > prior['xp']:
            self.wait_since = None
        self.target = self.definition.choose(snapshot)
        if self.target['kind'] == 'wait':
            self.set_state(RuntimeState.WAITING)
            if self.wait_since is None: self.wait_since = time.monotonic()
            if time.monotonic()-self.wait_since > self.config.idle_timeout_seconds:
                raise RuntimeError('Player remained idle or busy beyond the configured timeout.')
            self.emit('status', self.target['reason'])
            now = time.monotonic()
            if self.api.last_hover_point and now>=self.idle_motion_at:
                if self.idle_motion_anchor is None: self.idle_motion_anchor=self.api.last_hover_point
                anchor=self.idle_motion_anchor
                width,height=snapshot['dimensions']
                self.api.hover(Point(max(0,min(width-1,anchor.x+random.randint(-1,1))),
                                     max(0,min(height-1,anchor.y+random.randint(-1,1)))))
                self.idle_motion_at=now+random.uniform(1.2,2.8)
            if self.wait_reason != self.target['reason'] or now-self.last_wait_report >= 10:
                self.wait_reason,self.last_wait_report = self.target['reason'],now
                self.log('Waiting for next action',reason=self.wait_reason,
                         animation=snapshot['player']['animation'],route=snapshot['player']['route'],
                         xp=snapshot['xp'],inventory=len(snapshot['inventory']),
                         active_tree=self.policy.active_tile if self.policy else None)
            self.later(self.config.poll_ms, self.next_target, token)
            return
        self.wait_since = None
        self.wait_reason = None
        self.idle_motion_anchor = None
        self.set_state(RuntimeState.TARGETING)
        if self.target['kind']=='camera':
            self.begin_camera(token)
            return
        self.camera_attempts=0
        self.offset_index = 0
        self.hover(token)

    def arm_camera_probe(self):
        if not self.api:
            self.log('Attach successfully first.')
            return
        self.stop()
        self.camera_probe=True
        self.probing=True
        self.camera_attempts=0
        token=self.generation
        self.log('Camera probe in 5 seconds; focus the client. No click will be sent.')
        self.root.after(self.config.countdown_ms,lambda:self.begin_camera_probe(token))

    def begin_camera_probe(self,token):
        if token!=self.generation: return
        try:
            self.api.arm_input()
            self.running=True
            state=self.read()
            self.target={'kind':'camera','point':None,'yaw_target':state['camera']['yaw']+.2}
            self.begin_camera(token)
        except Exception as error:self.fail(error)

    def begin_camera(self,token):
        self.recovery_budget.observe(self.snapshot)
        self.recovery_budget.consume()
        self.camera_attempts+=1
        if self.camera_attempts>8: raise RuntimeError('Camera recovery exhausted its bounded attempts.')
        self.before_camera=self.snapshot['camera']
        error=(self.target['yaw_target']-self.before_camera['yaw']+math.pi)%(2*math.pi)-math.pi
        if abs(error)<.08: key=0x26
        elif self.camera_left_sign is None: key=0x25
        else: key=0x25 if error*self.camera_left_sign>0 else 0x27
        self.camera_key=key
        self.api.camera_key_down(key)
        self.later(350,self.release_camera,token)

    def release_camera(self,token):
        self.api.camera_key_up(self.camera_key)
        self.later(100,self.confirm_camera,token)

    def confirm_camera(self,token):
        after=self.read()['camera']
        yaw=(after['yaw']-self.before_camera['yaw']+math.pi)%(2*math.pi)-math.pi
        pitch=after['pitch']-self.before_camera['pitch']
        if abs(yaw)<.002 and abs(pitch)<.002:
            if self.background_run and not self.camera_probe:
                self.log('Camera key was not acknowledged; replanning without changing foreground focus',key=self.camera_key)
                self.later(self.config.poll_ms,self.next_target,token)
                return
            raise RuntimeError('Camera key did not change the view; verify client keyboard focus or camera settings.')
        if self.camera_key==0x25 and abs(yaw)>=.002: self.camera_left_sign=1 if yaw>0 else -1
        self.log('Camera adjustment acknowledged',key=self.camera_key,yaw_delta=yaw,pitch_delta=pitch)
        if self.camera_probe:
            self.stop()
            self.log('Camera probe passed; no click sent.')
        else:self.later(150,self.next_target,token)

    def hover(self, token):
        target = self.target
        offsets = self.offsets if target['kind'] in ('tree', 'bank') else [(0,0),(0,-4),(0,4),(-4,0),(4,0)] if target['kind']=='walk' else [(0, 0)]
        if target['kind'] in ('deposit','close'):
            child_offset=self.mouse.client_offset() if hasattr(self.mouse,'client_offset') else (0,0)
            offsets=list(dict.fromkeys([child_offset,(child_offset[0]+3,child_offset[1]),
                                       (child_offset[0]-3,child_offset[1]),(child_offset[0],child_offset[1]+3),
                                       (child_offset[0],child_offset[1]-3),(0,0)]))
            offsets=[offset for offset in offsets if target['point'][0]+offset[0]>=child_offset[0]
                     and target['point'][1]+offset[1]>=child_offset[1]]
            self.hover_child_offset = child_offset
        else:
            self.hover_child_offset = (0,0)
        if self.offset_index >= len(offsets):
            if target['kind']=='close':
                self.menu_retries += 1
                self.log('Bank close hover unavailable; refreshing control without clicking',target=target,
                         actual=self.snapshot.get('default'),attempt=self.menu_retries)
                if self.menu_retries>self.config.menu_retry_limit:
                    raise RuntimeError('Bank close control remained unavailable after bounded recovery.')
                self.later(self.config.poll_ms,self.next_target,token)
                return
            if target['kind']=='deposit':
                self.menu_retries += 1
                controls = self.api.interfaces((15,))
                component = next((entry for entry in controls if entry.id==983043 and entry.sub_id==target['slot']),None)
                self.log('Deposit hover not confirmed; no click sent',target=target,
                         bank_open=self.snapshot.get('bank_open'),actual=self.snapshot.get('default'),
                         menu=self.snapshot.get('menu'),attempt=self.menu_retries,
                         control_operations=component.operations if component else None,
                         control_visible=component.visible_candidate if component else None)
                if self.menu_retries>self.config.menu_retry_limit:
                    raise RuntimeError('Deposit slot did not expose a supported default action after bounded re-hover attempts; no click sent.')
                self.later(self.config.poll_ms,self.next_target,token)
                return
            if target['kind'] == 'bank' and self.policy:
                player = self.snapshot['player']
                destination = (3185,3436)
                camera = {'kind':'camera','point':None,'destination':destination,
                          'yaw_target':math.atan2(-(destination[0]-player['x']),destination[1]-player['y'])}
                self.log('Bank target obscured; adjusting camera before replanning',target=target,
                         actual=self.snapshot.get('default'))
                self.target = camera
                self.begin_camera(token)
                return
            if target['kind'] in ('tree','walk') and self.policy:
                self.policy.reject_target(target)
                self.log('Projected target menu unavailable; selecting an alternative',target=target)
                self.later(self.config.poll_ms,self.next_target,token)
                return
            raise RuntimeError('Projected target could not be confirmed in the menu; adjust camera and Probe again.')
        dx, dy = offsets[self.offset_index]
        point = (target['point'][0] + dx, target['point'][1] + dy)
        point=(point[0]+random.randint(-2,2),point[1]+random.randint(-2,2))
        target['input_point'] = point
        self.target_dimensions = tuple(self.snapshot['dimensions'])
        self.ack_retries=0
        previous=self.api.last_hover_point
        if previous and point==(previous.x,previous.y):
            point=(max(0,min(self.target_dimensions[0]-1,point[0]+(1 if point[0]<self.target_dimensions[0]-1 else -1))),point[1])
        start=(previous.x,previous.y) if previous else (self.target_dimensions[0]//2,self.target_dimensions[1]//2)
        self.motion_steps=iter(bezier_path(start,point,self.target_dimensions))
        self.move_step(token)

    def move_step(self,token):
        try: point,delay=next(self.motion_steps)
        except StopIteration:
            # Capture the final movement while the native queue still holds it.
            # Menu settling must not make a short-lived receipt disappear.
            self.api.collect_input_events((0,3,4,6,7))
            self.later(round(self.config.hover_ms*random.uniform(.8,1.2)),self.confirm_hover,token)
            return
        if self.target['kind'] in ('deposit','close'):
            point=(max(self.hover_child_offset[0],point[0]),max(self.hover_child_offset[1],point[1]))
        self.api.hover(Point(*point))
        self.later(delay,self.move_step,token)

    def confirm_hover(self, token):
        if self.background_probe and U.GetForegroundWindow() != self.background_foreground:
            raise RuntimeError('Foreground changed during background movement probe; no click sent.')
        if not self.mouse.audit_ok():
            raise RuntimeError('Window-message backend is not armed.')
        recorded=self.confirm_client_event(0,required=False)
        if recorded is None:
            self.ack_retries+=1
            if self.ack_retries<=5:
                self.later(40,self.confirm_hover,token)
                return
            self.log('Movement endpoint was not acknowledged; no click sent',target=self.target,
                     point=self.mouse.target,sent_at=self.mouse.sent_at)
            if self.menu_retries>=self.config.menu_retry_limit:
                raise InputAcknowledgmentError('Movement acknowledgment retries exhausted; no click sent.')
            self.menu_retries+=1
            self.later(self.config.poll_ms,self.next_target,token)
            return
        snapshot = self.read()
        if tuple(snapshot['dimensions']) != self.target_dimensions:
            self.menu_retries += 1
            if self.menu_retries>self.config.menu_retry_limit:
                raise RuntimeError('Client kept resizing during targeting; no click sent.')
            self.log('Client resized; refreshing target without clicking',target=self.target)
            self.later(self.config.poll_ms,self.next_target,token)
            return
        if self.target['kind'] in ('deposit','close') and not snapshot['bank_open']:
            self.log('Bank closed during targeting; no click sent',target=self.target)
            self.later(self.config.poll_ms,self.next_target,token)
            return
        if self.target['kind'] == 'tree' and not any(
                (obj['id'],obj['x'],obj['y']) == (self.target['id'],self.target['x'],self.target['y'])
                for obj in snapshot['objects']):
            self.log('Tree depleted before click; selecting another oak',target=self.target)
            self.later(self.config.poll_ms,self.next_target,token)
            return
        if not self.definition.menu_matches(self.target, snapshot):
            self.offset_index += 1
            self.hover(token)
            return
        self.log('Hover confirmed', target=self.target, default=snapshot['default'], recorder=recorded)
        if self.probing:
            if self.background_probe:
                self.background_probe_passed = True
            else:
                self.probe_passed = True
            self.stop()
            self.log('Background movement probe passed: exact menu confirmed and foreground unchanged. No click sent.'
                     if self.background_probe else 'Probe passed: window-message movement and exact menu identity confirmed. No click sent.',
                     **({'foreground_hwnd':self.background_foreground} if self.background_probe else {}))
            return
        self.submit_click(token)

    def submit_click(self, token):
        try:
            self.api.click_verified(lambda current: self.definition.menu_matches(self.target, self.api.last_raw), scheduler=self.root)
        except ActionMismatchError:
            # This exception is raised before posting either button event. Re-read
            # and re-hover rather than replaying an unknown gameplay operation.
            self.menu_retries += 1
            actual = (self.api.last_raw or {}).get('default')
            self.log('Menu changed before click; no click sent',target=self.target,actual=actual,attempt=self.menu_retries)
            if self.menu_retries > self.config.menu_retry_limit:
                raise RuntimeError('Menu kept changing before click; see the Activity log for expected/actual targets.')
            self.set_state(RuntimeState.TARGETING)
            self.later(self.config.poll_ms,self.next_target,token)
            return
        self.menu_retries = 0
        self.before_click = self.api.last_raw
        self.log('Action submitted',target=self.target,default=self.before_click.get('default'))
        self.click_deadline = time.monotonic() + (self.config.bank_timeout_seconds if self.target['kind'] == 'bank' else self.config.action_timeout_seconds)
        self.set_state(RuntimeState.VERIFYING)
        self.later(350, self.confirm_action, token)

    def confirm_action(self, token):
        self.mouse.foreground()
        if self.mouse.failure:
            raise RuntimeError(self.mouse.failure)
        button_event = self.confirm_client_event((3, 4), required=False)
        after, before = self.read(), self.before_click
        # Axe must remain present after every operation; never deposit inventory wholesale.
        quantities = lambda state, identity: sum(item['quantity'] for item in state['inventory'] if item['id']==identity)
        axes_before = {item['id'] for item in before['inventory'] if item['id'] in self.definition.required_items}
        if any(quantities(before,identity) != quantities(after,identity) for identity in axes_before):
            raise RuntimeError('Axe preservation check failed.')
        if self.target['kind']=='deposit':
            protected={item['id'] for item in before['inventory'] if item['id'] != self.target['id']}
            if any(quantities(before,identity) != quantities(after,identity) for identity in protected):
                raise RuntimeError('Deposit changed a protected inventory item quantity.')
        kind = self.target['kind']
        log_count = lambda s: sum(item['quantity'] for item in s['inventory'] if item['id'] == 1521)
        success = self.definition.acknowledged(self.target, before, after, button_event)
        if success:
            self.last_acknowledged_kind = kind
            if kind=='close': self.close_recoveries = 0
            if kind == 'deposit':
                self.logs_banked += max(0, log_count(before)-log_count(after))
                self.bank_deposits += 1
            self.completed_actions += 1
            self.log('Action acknowledged', kind=kind, xp=after['xp'], log_count=log_count(after), button_event=button_event)
            self.later(round(self.definition.settle_delay(self.target)*random.uniform(.8,1.4)), self.next_target, token)
        elif time.monotonic() >= self.click_deadline:
            if self.recover_bank_close(before,after,token):
                return
            events = list(self.api.event_history)
            recent = [event for event in events if self.mouse.sent_at <= event['stamp'] <= self.mouse.sent_at + 2500]
            self.log('Action timeout diagnostics', target=self.target, input_point=self.mouse.target,
                     sent_at=self.mouse.sent_at, button_event=button_event, recent_events=recent[-12:],
                     before_inventory=before['inventory'], after_inventory=after['inventory'],
                     bank_before=before['bank_open'], bank_after=after['bank_open'])
            raise RuntimeError('Action timed out; click outcome uncertain. No automatic retry.')
        else:
            self.later(500, self.confirm_action, token)

    def recover_bank_close(self,before,after,token):
        if self.target['kind']!='close' or not after['bank_open'] or not after.get('bank_close'):
            return False
        inventory=lambda state:sorted((item['slot'],item['id'],item['quantity']) for item in state['inventory'])
        if inventory(before)!=inventory(after) or after['player']['route']>0:
            return False
        if any(before['player'][key]!=after['player'][key] for key in ('world_id','plane')):
            return False
        if self.close_recoveries>=2:
            return False
        self.close_recoveries += 1
        self.mouse.release()
        self.log('Bank remains open with unchanged inventory; refreshing close control',attempt=self.close_recoveries,
                 identity=after.get('bank_close_identity'))
        self.set_state(RuntimeState.TARGETING)
        self.later(self.config.poll_ms,self.next_target,token)
        return True

    def stop(self):
        self.generation += 1
        self.running = False
        self.set_state(RuntimeState.STOPPED if self.reader else RuntimeState.DETACHED)
        if self.mouse:
            try:
                self.mouse.close()
            except Exception as error:
                self.log(str(error))

    def confirm_client_event(self, kind, required=True):
        kinds = (kind,) if isinstance(kind, int) else tuple(kind)
        return self.api.confirm_input_event(kinds, Point(*self.mouse.target), self.mouse.sent_at, required)

    def fail(self, error):
        self.stop()
        self.last_error = {'type': type(error).__name__, 'message': str(error)}
        self.set_state(RuntimeState.FAILED)
        self.log('Stopped: ' + str(error),error_type=type(error).__name__,target=self.target,
                 player=self.snapshot.get('player') if self.snapshot else None,
                 default=self.snapshot.get('default') if self.snapshot else None)

    def watch_stop(self):
        if self.running and U.GetAsyncKeyState(0x77) & 0x8000:
            self.fail(RuntimeError('F8 stop requested.'))
        if not self.closed:
            self.root.after(100, self.watch_stop)


    def close(self):
        self.closed = True
        self.stop()
        if self.api:
            self.api.close()
        self.session = self.reader = self.mouse = None
        self.set_state(RuntimeState.CLOSED)
