"""Reusable bank settings and guarded targets. Submission is not completion."""
import re
from dataclasses import dataclass
from grove.api.contracts import ActionMismatchError

def clean(value): return re.sub(r'<[^>]*>', '', value).strip()

@dataclass(frozen=True)
class BankSettings:
    opened: bool
    quantity: str | None
    notes: bool | None
    placeholders: bool | None

class Banking:
    def __init__(self, client): self.client = client
    def settings(self):
        snapshot=self.client.action_snapshot()
        if not snapshot.bank.opened: return BankSettings(False,None,None,None)
        controls=self.client.interfaces((12,))
        note=next((c for c in controls if c.id==786457 and c.sub_id==-1 and c.visible_candidate),None)
        placeholder=next((c for c in controls if c.id==786472 and c.sub_id==-1 and c.visible_candidate),None)
        note_ops=[clean(a) for a in note.operations] if note else []
        notes=False if 'Enable Notes' in note_ops else True if 'Disable Notes' in note_ops else None
        placeholder_ops=[clean(a) for a in placeholder.operations] if placeholder else []
        placeholders=False if 'Enable' in placeholder_ops else True if 'Disable' in placeholder_ops else None
        defaults={clean(c.operations[0]) for c in controls if c.id==786444 and c.quantity>0 and c.operations}
        quantity=next((name for name in ('1','5','10','All','X') if defaults=={'Withdraw-'+name}),None)
        return BankSettings(True,quantity,notes,placeholders)
    def control(self, component_id, action=None):
        component=next((c for c in self.client.interfaces((12,)) if c.id==component_id and c.sub_id==-1 and c.visible_candidate),None)
        if component is None: raise ActionMismatchError('Bank control is hidden or absent.')
        requested=action or (component.operations[0] if component.operations else None)
        if not requested: raise ActionMismatchError('Bank control has no mapped action.')
        return self.client.hover_interface(component,requested)
    def hover_quantity(self, quantity):
        identifiers={'1':786461,'5':786463,'10':786465,'All':786469}
        key=str(quantity)
        if key not in identifiers: raise ActionMismatchError('Use a mapped quantity: 1, 5, 10 or All.')
        return self.control(identifiers[key],'Default quantity: '+key)
    def hover_notes(self, enabled):
        component=next((c for c in self.client.interfaces((12,)) if c.id==786457 and c.sub_id==-1 and c.visible_candidate),None)
        action=next((a for a in component.operations if clean(a)==('Enable Notes' if enabled else 'Disable Notes')),None) if component else None
        if action is None: raise ActionMismatchError('Requested mode is already selected or control is unavailable.')
        return self.client.hover_interface(component,action)
    def hover_placeholders(self, enabled): return self.control(786472,'Enable' if enabled else 'Disable')
    def hover_withdraw(self,slot,item_id,action='Withdraw-1'): return self.client.hover_withdraw(slot,item_id,action)
    def hover_deposit(self,slot,item_id,action='Deposit-All'): return self.client.hover_deposit(slot,item_id,action)
    @staticmethod
    def preserve(before,after,item_ids):
        return all(before.count(item_id)==after.count(item_id) for item_id in item_ids)
