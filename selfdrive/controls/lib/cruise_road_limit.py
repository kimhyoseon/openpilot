def should_raise_to_road_limit(v_cruise_kph, road_limit_target_speed, road_limit_speed_valid):
  # road limit sync only raises the set speed; it never pulls down a speed the driver already set
  return road_limit_speed_valid and road_limit_target_speed > v_cruise_kph


def should_resume_road_limit_sync(sync_enabled, previous_road_limit_speed, road_limit_speed, road_limit_speed_valid):
  return not sync_enabled and previous_road_limit_speed != 0 and road_limit_speed_valid and previous_road_limit_speed != road_limit_speed
