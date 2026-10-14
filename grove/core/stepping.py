"""Client-independent selection of a projected, collision-safe local waypoint."""
import math
from grove.core.navigation import from_raw

def next_step(snapshot,destination,max_distance=6):
    player=snapshot['player']
    grid=from_raw(snapshot['collision']) if snapshot.get('collision') else None
    start=(player['x'],player['y'])
    path=grid.path(start,destination,adjacent=not grid.open(destination)) if grid else ()
    if grid and not path: raise RuntimeError('No collision-safe local path to the destination.')
    distance=lambda x,y:(x-destination[0])**2+(y-destination[1])**2
    candidates=[tile for tile in snapshot.get('ground_points',()) if tile.get('point') and
                0<(tile['x']-player['x'])**2+(tile['y']-player['y'])**2<=max_distance**2 and
                (grid is not None or distance(tile['x'],tile['y'])<distance(player['x'],player['y']))]
    dimensions=snapshot.get('dimensions')
    if dimensions:
        width,height=dimensions
        candidates=[tile for tile in candidates if 20<=tile['point'][0]<width-20 and 20<=tile['point'][1]<height-40]
    if grid:
        order={tile:index for index,tile in enumerate(path)}
        candidates=[tile for tile in candidates if (tile['x'],tile['y']) in order and grid.line_walk(start,(tile['x'],tile['y']))]
    if not candidates:
        if grid and path:
            return {'kind':'camera','point':None,'destination':destination,
                    'yaw_target':math.atan2(-(destination[0]-player['x']),destination[1]-player['y'])}
        raise RuntimeError('No projected ground step toward the destination.')
    tile=max(candidates,key=lambda t:order[(t['x'],t['y'])]) if grid else min(candidates,key=lambda t:distance(t['x'],t['y']))
    return {**tile,'kind':'walk','destination':destination,'path':list(path)}
