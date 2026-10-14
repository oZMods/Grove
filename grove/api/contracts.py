"""Explicit support boundaries and action identity contracts."""
from dataclasses import dataclass

class GroveError(RuntimeError): pass
class DetachedError(GroveError): pass
class StaleStateError(GroveError): pass
class ActionMismatchError(GroveError): pass
class UnsupportedCapabilityError(GroveError): pass
class InputAcknowledgmentError(GroveError): pass

@dataclass(frozen=True)
class Capabilities:
    supported: frozenset = frozenset({'local_player', 'inventory', 'scene_game_objects', 'ground_tile_projection',
                                     'native_menu', 'bank_inventory', 'woodcutting_skill', 'verified_window_input',
                                     'collision_navigation','npcs','players','equipment','skills','game_state',
                                     'interfaces','bank_storage','cached_item_definitions','camera_state','ground_items'})

    def require(self, capability):
        if capability not in self.supported:
            raise UnsupportedCapabilityError(f'Client driver does not support {capability}.')

@dataclass(frozen=True)
class ActionExpectation:
    action: str
    target_id: int
    world_instance_id: int
    x: int | None = None
    y: int | None = None
    slot: int | None = None
    inventory_item_id: int | None = None
    menu_world_instance_id: int | None = None
    bank_item_id: int | None = None

    def matches(self, snapshot):
        menu = snapshot.default_action
        return bool(menu and menu.action == self.action and menu.target_id == self.target_id and
                    menu.world_instance_id == (self.world_instance_id if self.menu_world_instance_id is None else self.menu_world_instance_id) and
                    snapshot.player.world_instance_id == self.world_instance_id and
                    (self.x is None or menu.x == self.x) and
                    (self.y is None or menu.y == self.y) and
                    (self.slot is None or menu.sub_id == self.slot) and
                    (self.inventory_item_id is None or any(item.slot == self.slot and item.id == self.inventory_item_id for item in snapshot.inventory.items)) and
                    (self.bank_item_id is None or any(item.slot == self.slot and item.id == self.bank_item_id and item.quantity > 0 for item in snapshot.bank_items.items)))
