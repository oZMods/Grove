"""Public Grove interface for bot authors."""
__all__ = ['ClientAPI', 'Bank', 'Inventory', 'Item', 'MenuAction', 'Player', 'Point', 'Snapshot', 'WorldObject', 'GroundTile',
           'GroundItem','Actor','Rectangle','InterfaceComponent','Skill','Camera',
           'Coordinate', 'Area', 'ObjectQuery','EntityQuery', 'Capabilities', 'ActionExpectation',
           'GroveError', 'DetachedError', 'StaleStateError', 'ActionMismatchError', 'UnsupportedCapabilityError','InputAcknowledgmentError']

def __getattr__(name):
    from importlib import import_module
    if name not in __all__: raise AttributeError(name)
    source = 'client' if name == 'ClientAPI' else 'query' if name in ('Coordinate','Area','ObjectQuery','EntityQuery') else 'contracts' if name in ('Capabilities','ActionExpectation','GroveError','DetachedError','StaleStateError','ActionMismatchError','UnsupportedCapabilityError','InputAcknowledgmentError') else 'models'
    module = import_module('grove.api.' + source)
    return getattr(module, name)
