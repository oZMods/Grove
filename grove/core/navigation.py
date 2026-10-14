"""Bounded local A* against the official client's mapped collision grid."""
from dataclasses import dataclass
import heapq
import itertools

BLOCKED=0x1240100
WALL={(0,1):2,(1,0):8,(0,-1):32,(-1,0):128,
      (-1,1):1,(1,1):4,(1,-1):16,(-1,-1):64}

@dataclass(frozen=True)
class CollisionGrid:
    origin_x:int
    origin_y:int
    width:int
    height:int
    plane:int
    flags:tuple

    def __post_init__(self):
        if not 1<=self.width<=256 or not 1<=self.height<=256 or len(self.flags)!=self.width*self.height:
            raise ValueError('Invalid bounded collision grid.')
    def contains(self,tile):
        return self.origin_x<=tile[0]<self.origin_x+self.width and self.origin_y<=tile[1]<self.origin_y+self.height
    def at(self,tile):
        if not self.contains(tile): return 0xffffffff
        return self.flags[(tile[0]-self.origin_x)*self.height+tile[1]-self.origin_y]
    def open(self,tile): return self.contains(tile) and not self.at(tile)&BLOCKED
    def can_step(self,start,end):
        dx,dy=end[0]-start[0],end[1]-start[1]
        if (dx,dy) not in WALL or not self.contains(start) or not self.open(end): return False
        if self.at(start)&WALL[(dx,dy)] or self.at(end)&WALL[(-dx,-dy)]: return False
        if dx and dy:
            a,b=(start[0]+dx,start[1]),(start[0],start[1]+dy)
            return self.can_step(start,a) and self.can_step(start,b) and self.can_step(a,end) and self.can_step(b,end)
        return True
    def line_walk(self,start,end):
        x,y=start
        dx,dy=abs(end[0]-x),abs(end[1]-y)
        sx,sy=1 if x<end[0] else -1,1 if y<end[1] else -1
        error=dx-dy
        while (x,y)!=end:
            old=(x,y)
            e=2*error
            if e>-dy: error-=dy; x+=sx
            if e<dx: error+=dx; y+=sy
            if not self.can_step(old,(x,y)): return False
        return True
    def path(self,start,goal,adjacent=False,max_nodes=20000):
        if not self.contains(start) or not self.contains(goal): return ()
        goals={goal} if not adjacent else {(goal[0]+dx,goal[1]+dy) for dx in (-1,0,1) for dy in (-1,0,1) if dx or dy}
        goals={tile for tile in goals if self.open(tile)}
        if not goals: return ()
        def heuristic(tile): return min(max(abs(tile[0]-g[0]),abs(tile[1]-g[1])) for g in goals)*10
        serial=itertools.count()
        heap=[(heuristic(start),next(serial),start)]
        cost={start:0}
        previous={}
        closed=set()
        while heap and len(closed)<max_nodes:
            _,_,tile=heapq.heappop(heap)
            if tile in closed: continue
            if tile in goals:
                result=[tile]
                while tile in previous: tile=previous[tile];result.append(tile)
                return tuple(reversed(result))
            closed.add(tile)
            for dx,dy in WALL:
                nxt=(tile[0]+dx,tile[1]+dy)
                if not self.can_step(tile,nxt): continue
                score=cost[tile]+(14 if dx and dy else 10)
                if score<cost.get(nxt,float('inf')):
                    cost[nxt]=score;previous[nxt]=tile
                    heapq.heappush(heap,(score+heuristic(nxt),next(serial),nxt))
        return ()

def from_raw(raw):
    return CollisionGrid(raw['origin_x'],raw['origin_y'],raw['width'],raw['height'],raw['plane'],tuple(raw['flags']))
