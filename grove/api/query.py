"""Immutable, reusable queries evaluated against one snapshot at a time."""
from dataclasses import dataclass
from math import hypot

@dataclass(frozen=True)
class Coordinate:
    x: int
    y: int
    plane: int = 0

    def distance_to(self, other):
        return hypot(self.x-other.x, self.y-other.y) if self.plane == other.plane else float('inf')

@dataclass(frozen=True)
class Area:
    south_west: Coordinate
    north_east: Coordinate

    def __post_init__(self):
        if self.south_west.plane != self.north_east.plane or self.south_west.x > self.north_east.x or self.south_west.y > self.north_east.y:
            raise ValueError('Area corners must be ordered on the same plane.')

    def contains(self, coordinate):
        return (coordinate.plane == self.south_west.plane and
                self.south_west.x <= coordinate.x <= self.north_east.x and
                self.south_west.y <= coordinate.y <= self.north_east.y)

@dataclass(frozen=True)
class ObjectQuery:
    predicates: tuple = ()

    def where(self, predicate): return ObjectQuery(self.predicates + (predicate,))
    def ids(self, *ids):
        accepted = frozenset(ids)
        return self.where(lambda obj, state: obj.id in accepted)
    def names(self, *names):
        accepted = frozenset(name.casefold() for name in names)
        return self.where(lambda obj, state: obj.name.casefold() in accepted)
    def actions(self, *actions):
        return self.where(lambda obj, state: all(action in obj.operations for action in actions))
    def projected(self): return self.where(lambda obj, state: obj.screen is not None)
    def within(self, distance, origin=None):
        if distance < 0: raise ValueError('Distance must be nonnegative.')
        return self.where(lambda obj, state: Coordinate(obj.x,obj.y,state.player.plane).distance_to(origin or state.player.position) <= distance)
    def in_area(self, area):
        return self.where(lambda obj, state: area.contains(Coordinate(obj.x,obj.y,state.player.plane)))
    def results(self, snapshot):
        return tuple(obj for obj in snapshot.objects if all(predicate(obj,snapshot) for predicate in self.predicates))
    def nearest(self, snapshot, origin=None):
        origin = origin or snapshot.player.position
        return min(self.results(snapshot), key=lambda obj: Coordinate(obj.x,obj.y,snapshot.player.plane).distance_to(origin), default=None)

@dataclass(frozen=True)
class EntityQuery:
    source:str
    predicates:tuple = ()
    def where(self,predicate): return EntityQuery(self.source,self.predicates+(predicate,))
    def ids(self,*ids):
        accepted=frozenset(ids)
        return self.where(lambda e,s:e.id in accepted)
    def names(self,*names):
        accepted=frozenset(name.casefold() for name in names)
        return self.where(lambda e,s:getattr(e,'name','').casefold() in accepted)
    def actions(self,*actions): return self.where(lambda e,s:all(a in getattr(e,'operations',()) for a in actions))
    def kinds(self,*kinds): return self.where(lambda e,s:getattr(e,'kind',None) in kinds)
    def groups(self,*groups): return self.where(lambda e,s:getattr(e,'group',None) in groups)
    def text_contains(self,text): return self.where(lambda e,s:text.casefold() in getattr(e,'text','').casefold())
    def projected(self): return self.where(lambda e,s:getattr(e,'screen',None) is not None)
    def within(self,distance,origin=None):
        if self.source not in ('objects','actors','ground_items'): raise ValueError('This collection has no world coordinates.')
        if distance<0: raise ValueError('Distance must be nonnegative.')
        return self.where(lambda e,s:Coordinate(e.x,e.y,getattr(e,'plane',s.player.plane)).distance_to(origin or s.player.position)<=distance)
    def results(self,snapshot):
        if self.source not in ('objects','actors','interfaces','inventory','equipment','bank_items','ground_items'):
            raise ValueError('Unknown query collection.')
        collection=getattr(snapshot,self.source,())
        collection=getattr(collection,'items',collection)
        return tuple(e for e in collection if all(predicate(e,snapshot) for predicate in self.predicates))
    def first(self,snapshot): return next(iter(self.results(snapshot)),None)
    def nearest(self,snapshot,origin=None):
        if self.source not in ('objects','actors','ground_items'): raise ValueError('Nearest requires world coordinates.')
        origin=origin or snapshot.player.position
        return min(self.results(snapshot),key=lambda e:Coordinate(e.x,e.y,getattr(e,'plane',snapshot.player.plane)).distance_to(origin),default=None)
