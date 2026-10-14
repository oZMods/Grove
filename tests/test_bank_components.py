import struct
import unittest
from types import SimpleNamespace
from grove.clients.osrs import ClientState

class BankComponentTests(unittest.TestCase):
    def reader(self):
        values = {1000+4275176:2000,2000+26768:3000,3000+288+8:3,
                  3000+288+16:4000,4008:5000,4024:6000,4040:7000,
                  1000+4275408:100,1000+4275416:1,9004:295,9008:0}
        rects={5000:(0,0,512,540),6000:(12,2,488,537),7000:(0,0,488,537),8000:(459,6,26,23)}
        for ptr,parent in ((5000,-1),(6000,786432),(7000,786433),(8000,786434)):
            values[ptr+56]=100
            values[ptr+116]=parent
            values[ptr+92]=rects[ptr][0]
            values[ptr+96]=rects[ptr][1]
        values.update({7000+2896:1,7000+2904:11000,11008:8000,8000+736:1,8000+744:12000})
        reader=SimpleNamespace(q=lambda address:values.get(address,0),i=lambda address:values.get(address,0),
                               read=lambda address,size:b'\0' if size==1 else struct.pack('<iiii',*rects[address-92]),
                               string=lambda address:'Close',chain_lookup=lambda *args:9000,
                               s=lambda state,offset:state+offset)
        return reader,values

    def test_nested_close_adds_static_and_dynamic_parent_offsets(self):
        reader,values=self.reader()
        self.assertEqual(ClientState.bank_close_point(reader,1000),(779,19))

    def test_parent_cycle_is_rejected(self):
        reader,values=self.reader()
        values[6000+116]=786433
        with self.assertRaises(RuntimeError): ClientState.bank_close_point(reader,1000)

if __name__ == '__main__': unittest.main()
