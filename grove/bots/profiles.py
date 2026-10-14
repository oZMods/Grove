"""Reviewed routes, distinct from the current player position."""
from dataclasses import dataclass

@dataclass(frozen=True)
class OakProfile:
    name: str
    anchor: tuple[int,int]
    trees: frozenset[tuple[int,int]]
    plane: int = 0

    def __post_init__(self):
        if not self.name or len(self.trees) != 3:
            raise ValueError('An oak route requires a name and exactly three tree tiles.')
        if any((x-self.anchor[0])**2+(y-self.anchor[1])**2 > 100 for x,y in self.trees):
            raise ValueError('Oak route trees must be within ten tiles of the anchor.')

VARROCK_WEST_OAKS = OakProfile('Varrock West oaks',(3164,3418),
                              frozenset({(3161,3416),(3167,3420),(3165,3411)}))
