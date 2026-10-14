from dataclasses import dataclass, replace
from typing import Callable
from grove.bots import woodcutting

@dataclass(frozen=True)
class BotDefinition:
    id: str
    name: str
    description: str
    choose: Callable
    menu_matches: Callable
    acknowledged: Callable
    settle_delay: Callable
    required_items: frozenset

OAK_POLICY = woodcutting.AnchoredOaks()
WOODCUTTING = BotDefinition(
    'woodcutting', 'Woodcutting',
    'Three oaks around the attachment tile · Varrock West Bank · retain axe and other items',
    OAK_POLICY.choose, OAK_POLICY.menu_matches, OAK_POLICY.acknowledged,
    woodcutting.settle_delay, frozenset(woodcutting.AXES))
BOTS = {WOODCUTTING.id: WOODCUTTING}

def instantiate(definition):
    if definition.id == 'woodcutting':
        policy = woodcutting.AnchoredOaks()
        return replace(definition, choose=policy.choose, menu_matches=policy.menu_matches,
                       acknowledged=policy.acknowledged), policy
    return definition, None

def register(definition):
    if not isinstance(definition, BotDefinition) or not definition.id or not definition.name:
        raise ValueError('Bots require a BotDefinition with a nonempty ID and name.')
    if not all(callable(getattr(definition,name)) for name in ('choose','menu_matches','acknowledged','settle_delay')):
        raise ValueError('Bot lifecycle functions must be callable.')
    if definition.id in BOTS:
        raise ValueError('A bot with this ID is already registered.')
    BOTS[definition.id] = definition
