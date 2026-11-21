import unittest

from selfdrive.controls.lib.cruise_road_limit import should_raise_to_road_limit, should_resume_road_limit_sync


class TestCruiseRoadLimit(unittest.TestCase):
  def test_raise_only_when_target_is_higher(self):
    self.assertFalse(should_raise_to_road_limit(120, 115, True))
    self.assertTrue(should_raise_to_road_limit(90, 115, True))
    self.assertFalse(should_raise_to_road_limit(115, 115, True))
    self.assertFalse(should_raise_to_road_limit(90, 115, False))

  def test_set_speed_above_target_is_never_lowered(self):
    # cruise engages at the current speed (120) after SET is released; road limit target is 115
    v_cruise_kph = 120
    for _ in range(500):
      if should_raise_to_road_limit(v_cruise_kph, 115, True):
        v_cruise_kph = 115
    self.assertEqual(v_cruise_kph, 120)

  def test_resume_only_for_a_new_valid_road_limit(self):
    self.assertFalse(should_resume_road_limit_sync(False, 60, 60, True))
    self.assertFalse(should_resume_road_limit_sync(False, 60, 0, False))
    self.assertTrue(should_resume_road_limit_sync(False, 60, 80, True))
    self.assertFalse(should_resume_road_limit_sync(True, 60, 80, True))


if __name__ == "__main__":
  unittest.main()
