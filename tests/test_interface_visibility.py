import struct
import unittest
from grove.clients.osrs import ClientState


class InterfaceVisibilityTests(unittest.TestCase):
    def reader(self, hidden=False):
        reader=ClientState.__new__(ClientState)
        state,manager,groups,array,parent,child,node=5000,1000,7000,8000,9000,10000,13000
        q={state+4275176:manager,manager+26760:13,manager+26768:groups,
           groups+24*12+8:2,groups+24*12+16:array,array+8:parent,array+24:child}
        ints={node:12,node+4:100,node+8:200,parent+116:-1,child+116:786432,
              parent+4:786432,child+4:786433,parent+8:-1,child+8:-1,parent+56:1,child+56:1,
              parent+132:0,parent+136:50}
        blocks={parent+92:struct.pack('<4i',0,0,100,100),child+92:struct.pack('<4i',10,130,20,40),
                parent+120:bytes([int(hidden)]),child+120:b'\0',parent+132:struct.pack('<2i',0,50),child+132:b'\0'*8}
        reader.q=lambda address:q.get(address,0)
        reader.i=lambda address:ints.get(address,0)
        reader.read=lambda address,size:blocks.get(address,b'\0'*size)
        reader.string=lambda address:''
        reader.hash_entries=lambda *args:iter((node,))
        return reader,state

    def test_hidden_parent_hides_child(self):
        reader,state=self.reader(True)
        child=next(c for c in reader.interfaces(state,(12,)) if c['id']==786433)
        self.assertTrue(child['hidden'])
        self.assertFalse(child['visible_candidate'])

    def test_scroll_is_subtracted_and_child_clipped(self):
        reader,state=self.reader()
        child=next(c for c in reader.interfaces(state,(12,)) if c['id']==786433)
        self.assertEqual(child['bounds'],(110,280,20,40))
        self.assertEqual(child['clipped_bounds'],(110,280,20,20))
        self.assertTrue(child['visible_candidate'])
