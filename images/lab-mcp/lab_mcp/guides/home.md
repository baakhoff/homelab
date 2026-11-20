# home: Home Assistant, the house

REST with JSON. A device or sensor is an "entity" such as light.kitchen;
acting on one is "calling a service".

## Endpoints
- GET /states                              everything (large; prefer the home_states tool)
- GET /states/{entity_id}
- POST /services/{domain}/{service} {"entity_id": "light.kitchen", ...}
- GET /services                            every service and its fields (large)
- GET /history/period/{start ISO time}?filter_entity_id=sensor.a,sensor.b&end_time={ISO}&minimal_response
- GET /logbook/{start ISO time}?entity=light.kitchen
- POST /template {"template": "{{ states('sensor.hall_temperature') }}"}      answers plain text
- GET /calendars     GET /calendars/{entity_id}?start={ISO}&end={ISO}
- GET /config        GET /error_log
- POST /events/{event_type} {...}

## Services used most
light.turn_on (brightness_pct, color_temp_kelvin, rgb_color) / turn_off / toggle;
switch.turn_on / turn_off; climate.set_temperature (temperature);
cover.open_cover / close_cover; scene.turn_on; script.turn_on;
automation.trigger / turn_on / turn_off; media_player.media_pause / volume_set;
input_boolean.toggle; homeassistant.update_entity.
notify.* services send a message to a phone or chat: only when the person asks.
