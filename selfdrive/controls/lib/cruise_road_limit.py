def should_preserve_current_speed_on_set(enabled, current_speed, road_limit_target_speed, road_limit_speed_valid):
  return not enabled and road_limit_speed_valid and current_speed > road_limit_target_speed


def get_initial_set_speed_override(existing_override, enabled, current_speed, road_limit_target_speed, road_limit_speed_valid):
  if existing_override is not None:
    return existing_override
  if should_preserve_current_speed_on_set(enabled, current_speed, road_limit_target_speed, road_limit_speed_valid):
    return current_speed
  return None


def should_resume_road_limit_sync(sync_enabled, previous_road_limit_speed, road_limit_speed, road_limit_speed_valid):
  return not sync_enabled and previous_road_limit_speed != 0 and road_limit_speed_valid and previous_road_limit_speed != road_limit_speed
