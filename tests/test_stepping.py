import unittest
from grove.core.stepping import next_step

class SteppingTests(unittest.TestCase):
    def state(self):
        return {'player':{'x':100,'y':100},'dimensions':(900,600),
                'collision':{'origin_x':100,'origin_y':100,'width':5,'height':5,'plane':0,'flags':[0]*25},
                'ground_points':[{'x':103,'y':103,'point':(450,300)}]}

    def test_shared_navigation_has_no_varrock_coordinate_limit(self):
        target=next_step(self.state(),(104,104))
        self.assertEqual((target['kind'],target['x'],target['y']),('walk',103,103))

    def test_edge_projection_requests_camera_instead_of_ui_click(self):
        state=self.state()
        state['ground_points'][0]['point']=(10,590)
        self.assertEqual(next_step(state,(104,104))['kind'],'camera')
