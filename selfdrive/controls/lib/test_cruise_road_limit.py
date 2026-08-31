import unittest

from selfdrive.controls.lib.cruise_road_limit import get_initial_set_speed_override, should_preserve_current_speed_on_set, should_resume_road_limit_sync


class TestCruiseRoadLimit(unittest.TestCase):
  def test_preserve_current_speed_on_initial_set(self):
    self.assertTrue(should_preserve_current_speed_on_set(False, 80, 75, True))
    self.assertFalse(should_preserve_current_speed_on_set(False, 75, 75, True))
    self.assertFalse(should_preserve_current_speed_on_set(False, 70, 75, True))

  def test_preserve_only_on_initial_set_with_valid_road_limit(self):
    self.assertFalse(should_preserve_current_speed_on_set(True, 80, 75, True))
    self.assertFalse(should_preserve_current_speed_on_set(False, 80, 75, False))

  def test_initial_set_speed_is_latched_while_button_is_held(self):
    override = get_initial_set_speed_override(None, False, 80, 75, True)
    self.assertEqual(override, 80)
    self.assertEqual(get_initial_set_speed_override(override, True, 79, 75, True), 80)

  def test_resume_only_for_a_new_valid_road_limit(self):
    self.assertFalse(should_resume_road_limit_sync(False, 60, 60, True))
    self.assertFalse(should_resume_road_limit_sync(False, 60, 0, False))
    self.assertTrue(should_resume_road_limit_sync(False, 60, 80, True))
    self.assertFalse(should_resume_road_limit_sync(True, 60, 80, True))


if __name__ == "__main__":
  unittest.main()
