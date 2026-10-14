from dataclasses import dataclass
from typing import Optional, Tuple
from grove.api.query import Coordinate, ObjectQuery,EntityQuery

@dataclass(frozen=True)
class Point:
    x: int
    y: int

@dataclass(frozen=True)
class Item:
    slot: int
    id: int
    quantity: int
    name: str = ''
    operations: Tuple[str,...] = ()

@dataclass(frozen=True)
class Inventory:
    items: Tuple[Item, ...]
    capacity: int = 28

    @property
    def occupied(self): return len(self.items)
    @property
    def full(self): return self.occupied >= self.capacity
    def count(self, item_id): return sum(item.quantity for item in self.items if item.id == item_id)
    def contains(self, item_id): return self.count(item_id) > 0
    def slots_for(self, item_id): return tuple(item.slot for item in self.items if item.id == item_id)
    @property
    def free_slots(self): return max(0, self.capacity-self.occupied)
    def get_slot(self, slot): return next((item for item in self.items if item.slot == slot), None)

@dataclass(frozen=True)
class Player:
    world_instance_id: int
    x: int
    y: int
    plane: int
    route_length: int
    animation: int

    @property
    def moving(self): return self.route_length > 0
    @property
    def position(self): return Coordinate(self.x, self.y, self.plane)

@dataclass(frozen=True)
class WorldObject:
    id: int
    x: int
    y: int
    screen: Optional[Point]
    name: str = ''
    operations: Tuple[str, ...] = ()
    kind:str = 'game_object'

    def distance_squared(self, player): return (self.x - player.x) ** 2 + (self.y - player.y) ** 2

@dataclass(frozen=True)
class GroundTile:
    position: Coordinate
    screen: Point

@dataclass(frozen=True)
class GroundItem:
    id:int
    quantity:int
    x:int
    y:int
    plane:int
    name:str
    operations:Tuple[str,...]
    screen:Optional[Point]

@dataclass(frozen=True)
class Actor:
    kind:str
    index:int
    id:int
    name:str
    x:int
    y:int
    plane:int
    world_instance_id:int
    animation:int
    route_length:int
    screen:Optional[Point]
    operations:Tuple[str,...] = ()
    def distance_squared(self,player): return (self.x-player.x)**2+(self.y-player.y)**2

@dataclass(frozen=True)
class Rectangle:
    x:int
    y:int
    width:int
    height:int
    @property
    def center(self): return Point(self.x+self.width//2,self.y+self.height//2)
    def contains(self,point): return self.x<=point.x<self.x+self.width and self.y<=point.y<self.y+self.height

@dataclass(frozen=True)
class InterfaceComponent:
    id:int
    sub_id:int
    group:int
    parent_id:int
    bounds:Rectangle
    text:str
    operations:Tuple[str,...]
    visible_candidate:bool
    processed_frame:int
    item_id:int
    quantity:int
    hidden:bool = False
    scroll:Tuple[int,int] = (0,0)
    clipped_bounds:Optional[Rectangle] = None
    @property
    def screen(self): return (self.clipped_bounds or self.bounds).center if self.visible_candidate else None
    @property
    def name(self): return self.text

@dataclass(frozen=True)
class Skill:
    id:int
    effective_level:int
    base_level:int
    xp:int

@dataclass(frozen=True)
class Camera:
    yaw:float
    pitch:float
    zoom:int
    position:Tuple[int,int,int]

@dataclass(frozen=True)
class MenuAction:
    action: str
    target_id: int
    sub_id: int
    world_instance_id: int
    x: int
    y: int
    target_text: str

@dataclass(frozen=True)
class Bank:
    opened: bool
    inventory_slots: Tuple[Item, ...]
    close_point: Optional[Point]
    close_identity: Optional[Tuple[int,int]] = None

@dataclass(frozen=True)
class Snapshot:
    pid: int
    captured_at: float
    player: Player
    inventory: Inventory
    objects: Tuple[WorldObject, ...]
    bank: Bank
    menu: Tuple[MenuAction, ...]
    default_action: Optional[MenuAction]
    woodcutting_level: int
    woodcutting_xp: int
    dimensions: Tuple[int, int]
    ground_tiles: Tuple[GroundTile,...] = ()
    actors:Tuple[Actor,...] = ()
    interfaces:Tuple[InterfaceComponent,...] = ()
    equipment:Inventory = Inventory((),14)
    bank_items:Inventory = Inventory((),2048)
    skills:Tuple[Skill,...] = ()
    camera:Optional[Camera] = None
    collision:object = None
    game_state:int = -1
    tick:int = -1
    logged_in:bool = False
    ground_items:Tuple[GroundItem,...] = ()

    def query_objects(self): return ObjectQuery()
    def query_npcs(self): return EntityQuery('actors').kinds('npc')
    def query_players(self): return EntityQuery('actors').kinds('player')
    def query_interfaces(self): return EntityQuery('interfaces')
    def query_inventory(self): return EntityQuery('inventory')
    def query_equipment(self): return EntityQuery('equipment')
    def query_bank(self): return EntityQuery('bank_items')
    def query_ground_items(self): return EntityQuery('ground_items')

    def find_objects(self, ids=None, name=None, operation=None):
        return tuple(obj for obj in self.objects if
                     (ids is None or obj.id in ids) and
                     (name is None or obj.name.casefold() == name.casefold()) and
                     (operation is None or operation in obj.operations))

    def nearest(self, objects):
        return min(objects, key=lambda obj: obj.distance_squared(self.player), default=None)
