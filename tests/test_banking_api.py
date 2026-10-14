import unittest
from types import SimpleNamespace
from grove.api.banking import Banking
from grove.api.models import InterfaceComponent,Rectangle,Inventory,Item

def component(identity,operations,slot=-1,quantity=0):
    return InterfaceComponent(identity,slot,12,-1,Rectangle(0,0,36,36),'',tuple(operations),True,1,1521,quantity)

class BankingTests(unittest.TestCase):
    def test_notes_placeholders_and_quantity_are_read_from_actions(self):
        controls=[component(786457,['Disable <col=ff9040>Notes']),component(786472,['Disable']),
                  component(786444,['Withdraw-1','Withdraw-All'],3,50)]
        client=SimpleNamespace(action_snapshot=lambda:SimpleNamespace(bank=SimpleNamespace(opened=True)),interfaces=lambda groups:controls)
        settings=Banking(client).settings()
        self.assertEqual((settings.quantity,settings.notes,settings.placeholders),('1',True,True))

    def test_conflicting_defaults_remain_unknown(self):
        controls=[component(786444,['Withdraw-1'],1,1),component(786444,['Withdraw-All'],2,1)]
        client=SimpleNamespace(action_snapshot=lambda:SimpleNamespace(bank=SimpleNamespace(opened=True)),interfaces=lambda groups:controls)
        self.assertIsNone(Banking(client).settings().quantity)

    def test_preservation_requires_exact_quantity(self):
        before=Inventory((Item(0,1357,1),Item(1,1521,10)))
        after=Inventory((Item(0,1357,1),))
        self.assertTrue(Banking.preserve(before,after,(1357,)))
        self.assertFalse(Banking.preserve(before,Inventory(()),(1357,)))

    def test_partial_component_targets_visible_intersection(self):
        control=component(786444,['Withdraw-1'])
        from dataclasses import replace
        control=replace(control,bounds=Rectangle(0,0,36,36),clipped_bounds=Rectangle(0,20,36,16))
        self.assertEqual((control.screen.x,control.screen.y),(18,28))
