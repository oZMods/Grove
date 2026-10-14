import random
import unittest
from grove.input.motion import bezier_path

class MotionTests(unittest.TestCase):
    def test_exact_endpoint_and_bounded_jitter(self):
        path=bezier_path((10,10),(790,590),(800,600),random.Random(5))
        self.assertEqual(path[-1][0],(790,590))
        self.assertTrue(all(0<=x<800 and 0<=y<600 and delay>=8 for (x,y),delay in path))

    def test_path_curves_and_eases(self):
        path=bezier_path((10,200),(790,200),(800,600),random.Random(5))
        self.assertTrue(any(abs(point[1]-200)>5 for point,delay in path))
        xs=[10]+[point[0] for point,delay in path]
        self.assertLess(xs[1]-xs[0],xs[len(xs)//2]-xs[len(xs)//2-1])
        self.assertLess(xs[-1]-xs[-2],xs[len(xs)//2]-xs[len(xs)//2-1])

    def test_zero_distance_and_invalid_bounds(self):
        self.assertEqual(bezier_path((10,10),(10,10),(800,600),random.Random(1))[-1][0],(10,10))
        with self.assertRaises(ValueError): bezier_path((0,0),(1,1),(0,10))

if __name__=='__main__': unittest.main()
