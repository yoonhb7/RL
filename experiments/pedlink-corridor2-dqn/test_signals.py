"""Boundary checks for new three-service signal control."""
import unittest
import run

class SignalTests(unittest.TestCase):
    def test_priority_respects_minimum_then_requests_pedestrian(self):
        control=run.Junction('priority')
        control.elapsed=14
        self.assertEqual(control.mask(2,10,10,40).tolist(),[True,False,False])
        control.elapsed=15
        self.assertEqual(control.mask(2,10,10,40).tolist(),[False,False,True])
        basic=run.Junction('basic')
        basic.elapsed=15
        self.assertEqual(basic.mask(2,10,10,40).tolist(),[True,True,True])

    def test_yellow_and_all_red_precede_requested_service(self):
        control=run.Junction('basic')
        control.elapsed=15
        control.request(1,0)
        self.assertEqual(control.stage,'yellow')
        self.assertEqual(control.mask(0,0,0,0).tolist(),[False,True,False])
        control.elapsed=3
        control.advance(False)
        self.assertEqual(control.stage,'yellow')
        control.elapsed=4
        control.advance(False)
        self.assertEqual(control.stage,'all_red')
        control.elapsed=1
        control.advance(False)
        self.assertEqual(control.stage,'all_red')
        control.elapsed=2
        control.advance(False)
        self.assertEqual(control.stage,'NS')

    def test_clearance_waits_for_people_even_after_minimum(self):
        control=run.Junction('priority')
        control.stage,control.elapsed,control.target='PED',10,2
        control.request(0,0)
        control.elapsed=9
        control.advance(False)
        self.assertEqual(control.stage,'clearance')
        control.elapsed=10
        control.advance(True)
        self.assertEqual(control.stage,'clearance')
        control.advance(False)
        self.assertEqual(control.stage,'EW')

    def test_cost_fades_and_joint_action_is_single_categorical_choice(self):
        for wait,expected in [(0,.02),(15,.01),(30,0),(60,0)]:
            control=run.Junction('adaptive')
            control.elapsed=15
            changed,cost=control.request(2,wait)
            self.assertTrue(changed)
            self.assertAlmostEqual(cost,expected)
            self.assertEqual(control.request(2,wait),(False,0))
        self.assertEqual(run.ACTIONS.shape,(9,2))
        self.assertEqual(run.ACTIONS[5].tolist(),[1,2])

if __name__=='__main__':
    unittest.main()
