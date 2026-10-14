# Grove Python API

The API exposes typed client state, immutable queries and verified actions through a local Python session. Attachment requires a reviewed executable hash. The current installed build has passed offline recovery but is not yet a reviewed runtime profile; see [validation](VALIDATION.md).

## Attach and snapshot

```python
from grove.api import ClientAPI

with ClientAPI.attach(read_only=True) as client:
    state = client.snapshot()
    print(state.player.x, state.player.y)
    print(state.inventory.count(1521))   # oak logs
    print(state.inventory.free_slots)
```

`ClientAPI.attach(pid=None)` validates the executable hash, resolves one `osclient.exe`, and returns a session. Pass a PID if more than one client is running. `attach(read_only=True)` skips window enumeration and input adapter construction. Use that for diagnostics, research, or anything that doesn't send input.

`snapshot()` does one pass of memory reads and returns a frozen `Snapshot`. The reads are not atomic. A moving scene or open bank can produce slightly stale state. The snapshot records a `captured_at` timestamp; hover methods reject anything older than two seconds.

`action_snapshot()` is a lighter read that skips scene objects and is used internally right before posting a click.

## What's in a snapshot

`Snapshot` fields:

| Field | Type | Notes |
|---|---|---|
| `player` | `Player` | world tile (x, y, plane), route_length, animation, world_instance_id |
| `inventory` | `Inventory` | 28-slot container with item ID, quantity, name, operations |
| `objects` | `tuple[WorldObject]` | game objects, walls and decorations, with a projected screen point when visible |
| `bank` | `Bank` | open state, inventory slots, close point and identity |
| `menu` | `tuple[MenuAction]` | full visible menu |
| `default_action` | `MenuAction` or None | the default left-click action |
| `woodcutting_level` | int | effective Woodcutting level |
| `woodcutting_xp` | int | current Woodcutting XP |
| `ground_tiles` | `tuple[GroundTile]` | projected walkable tiles in the current viewport |
| `actors` | `tuple[Actor]` | nearby players and NPCs |
| `interfaces` | `tuple[InterfaceComponent]` | interface components (included when snapshot is called with `interface_groups`) |
| `equipment` | `Inventory` | container 94, 14 slots |
| `bank_items` | `Inventory` | container 95, up to 2048 slots |
| `skills` | `tuple[Skill]` | all 25 skills: effective level, base level and XP |
| `camera` | `Camera` | yaw, pitch, zoom, position |
| `collision` | `CollisionGrid` or None | directional wall flags from the loaded map |
| `game_state` | int | raw game state integer |
| `logged_in` | bool | |
| `ground_items` | `tuple[GroundItem]` | visible dropped items |

`Player.world_instance_id` is the client's internal scene instance value, not the OSRS world number. It's used to verify that a click target belongs to the same scene load as the player.

`Player.moving` is `route_length > 0`. `Player.position` returns a `Coordinate`.

`WorldObject.screen` is `None` when the object isn't projected into the current viewport. Always check before using it as a click target.

## Queries

Queries are immutable and reusable. They don't trigger any reads on their own. Evaluate them against a snapshot you already have.

```python
from grove.api import ClientAPI, ObjectQuery, Coordinate, Area

oaks = ObjectQuery().names('Oak tree').actions('Chop down').within(10).projected()

with ClientAPI.attach(read_only=True) as client:
    state = client.snapshot()
    tree = oaks.nearest(state)
    if tree:
        print(tree.x, tree.y, tree.screen)
```

`ObjectQuery` filters: `ids(*ids)`, `names(*names)` (case-insensitive), `actions(*actions)`, `within(tiles, origin=None)`, `in_area(area)`, `projected()`, `where(predicate)`. `.results(snapshot)` returns a tuple of matching objects. `.nearest(snapshot)` returns the closest one or None.

`EntityQuery` covers actors, interfaces, inventory items, equipment, bank storage and ground items. Use `snapshot.query_npcs()`, `snapshot.query_players()`, `snapshot.query_interfaces()`, etc. to start a query on the right collection. Additional filters: `kinds(*kinds)`, `groups(*groups)`, `text_contains(text)`. `.first(snapshot)` returns the first match.

`Coordinate.distance_to(other)` returns `inf` if the planes differ. `Area` takes two `Coordinate` corners in (south_west, north_east) order on the same plane.

`snapshot.find_objects(ids, name, operation)` is a quick filter without building a query object. `snapshot.nearest(objects)` takes an iterable of `WorldObject` and returns the closest.

`snapshot(interface_groups=(12, 15))` pulls in interface components for those groups. `client.interfaces(group_ids)` reads them separately without a full snapshot.

## Hover and click

Input has to be armed first. Arm once at the start of a session, disarm when done.

```python
client.arm_input()
```

Each hover call:

```python
client.hover(screen_point)           # Point(x, y)
expectation = client.hover_object(obj, 'Chop down')
expectation = client.hover_deposit(slot, item_id)
expectation = client.hover_bank_close()
expectation = client.hover_ground_tile(coordinate)
expectation = client.hover_interface(component, action)
expectation = client.hover_actor(actor, action)
```

The `hover_*` methods re-read state, verify the target still exists and has the expected action, move the mouse, and return an `ActionExpectation`. That expectation captures the action name, target ID, world instance ID, tile coordinates, and optionally a slot or item ID.

After waiting for the UI scheduler to process the movement:

```python
client.click_expected(expectation)
```

This re-reads state, checks that the current default menu action satisfies the expectation, reads the client's input event recorder to confirm the movement was acknowledged, then posts the button down/up. It raises `ActionMismatchError` if anything doesn't match. No click is sent. Returns the pre-click snapshot.

For a custom check instead of the expectation:

```python
client.click_verified(lambda fresh: fresh.default_action is not None
    and fresh.default_action.action == 'Chop down'
    and fresh.default_action.target_id == tree.id
    and fresh.default_action.x == tree.x
    and fresh.default_action.y == tree.y
    and fresh.default_action.world_instance_id == fresh.player.world_instance_id)
```

A hover revision counter prevents re-using the same hover for two clicks. Each click requires a fresh hover.

## Navigation

```python
path = client.plan_path(Coordinate(3185, 3436, 0))  # A* through loaded collision map
```

Returns a tuple of `Coordinate` tiles from player position to the destination. Returns an empty tuple if the destination isn't reachable within the loaded map. Handles directional walls, corner checks, and diagonal movement. Region transitions, doors, and stairs are not covered.

`CollisionGrid.open(tile)`, `can_step(start, end)`, `line_walk(start, end)` are all available on `snapshot.collision` directly if you need them.

## Events and async

```python
unsub = client.subscribe('player_moved', callback)
task = client.wait_until(scheduler, condition, timeout_seconds=10)
```

`subscribe` returns an unsubscribe function. Subscriber exceptions are caught and recorded, they don't propagate. `wait_until` polls through a scheduler event loop and returns a `ConditionTask` with a `.cancel()` method. All outstanding tasks are cancelled when the API is closed.

## Capabilities and errors

`client.capabilities.require('verified_window_input')` raises `UnsupportedCapabilityError` if the session was attached read-only. Supported capabilities: `local_player`, `inventory`, `scene_game_objects`, `ground_tile_projection`, `native_menu`, `bank_inventory`, `woodcutting_skill`, `verified_window_input`, `collision_navigation`, `npcs`, `players`, `equipment`, `skills`, `game_state`, `interfaces`, `bank_storage`, `cached_item_definitions`, `camera_state`, `ground_items`.

All errors extend `GroveError` which extends `RuntimeError`:

- `DetachedError`: called after the session was closed
- `StaleStateError`: snapshot is older than two seconds before a hover
- `ActionMismatchError`: pre-click menu check failed, no click sent
- `InputAcknowledgmentError`: movement wasn't confirmed in the event recorder
- `UnsupportedCapabilityError`: capability not available in this session

## RuntimeConfig

Pass a `RuntimeConfig` to `BotRuntime` to tune the scheduler:

```python
from grove.core.config import RuntimeConfig
config = RuntimeConfig(
    countdown_ms=5000,
    poll_ms=600,
    hover_ms=300,
    action_timeout_seconds=15,
    bank_timeout_seconds=30,
    idle_timeout_seconds=180,
    event_limit=2000,
    menu_retry_limit=3,
)
```

All values must be finite positive numbers. `_ms` and count fields must be integers.

## Writing a bot

```python
from grove.bots.registry import BotDefinition, register

def choose(snapshot): ...       # return a target dict: kind, point, id, x, y, ...
def menu_matches(target, snapshot): ...   # True if default action matches
def acknowledged(target, before, after, button_event): ...  # True if action succeeded
def settle_delay(target): ...   # ms to wait before selecting the next target

MY_BOT = BotDefinition('my_bot', 'My Bot', 'Description', choose, menu_matches, acknowledged, settle_delay, frozenset())
register(MY_BOT)
```

The runtime calls `choose` to get a target, hovers and clicks it, waits for `acknowledged` to return True (polling every 500ms until `action_timeout_seconds`), then calls `choose` again. Camera adjustment and collision-based stepping are handled automatically when `choose` returns a `'walk'` or `'camera'` target.

`required_items` is a frozenset of item IDs that must stay in inventory after every action. The runtime will stop if any of them disappear.

`raw_snapshot()` is a compatibility shim for the woodcutting policy that returns the internal raw dict. New bots should use `snapshot()`.


## Implementation notes

Focus-independent input: the runtime background-input mode enables client-child window messages for movement, clicks and camera arrow keys without requiring the game to stay foreground or uncovered. It does not move the desktop cursor or issue global keyboard input. Keep the client unminimized so geometry and projection remain valid. Native target identity and gameplay acknowledgement checks remain enforced; switching applications alone does not stop the bot. Background camera messages are attempted and their state changes verified, with bounded recovery when the client does not acknowledge them. This is not internal-function injection. The optional background hover probe remains movement-only.

`client.plan_step(Coordinate(...))` selects a collision-safe projected local waypoint or requests camera recovery. The woodcutting bot delegates to this shared stepping implementation. It has no Varrock coordinate restrictions; the bot's reviewed route still does. This does not add cross-region transports or stairs.

Recent bank/interface validation: `client.banking.settings()` reports quantity, Notes and placeholder modes from current actions; unknown values remain `None`. Live quantity 1, Notes and placeholders were verified. `hover_quantity`, `hover_notes`, `hover_placeholders`, `hover_deposit` and `hover_withdraw` prepare guarded expectations; callers must still schedule submission and verify the resulting state. Withdrawals recheck the bank slot's item ID and positive quantity immediately before clicking. Custom quantity entry, contextual selection and equipment operations are still unfinished.

Interfaces now propagate hidden ancestors, subtract parent scroll positions and intersect bounds with ancestor containers. `InterfaceComponent.hidden`, `.scroll` and `.clipped_bounds` expose this evidence. `.screen` uses the visible intersection. A bank scroll offset of 180 pixels was confirmed live. Menu identity remains necessary before interaction.

Ground items were verified live using a dropped oak log: ID 1521, quantity 1, tile (3185, 3436). `hover_ground_item(item, 'Take')` refreshes and resolves that item before movement and returns an action expectation. This does not itself submit a click or establish pickup completion.

The API wraps the raw memory reader in typed, immutable snapshots. It exposes a local Python interface to the running client.
