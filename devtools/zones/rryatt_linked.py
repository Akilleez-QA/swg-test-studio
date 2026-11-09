"""Authoritative assertions for the saved Rryatt guide protocol gate."""
import math

ROUTES = ('rryattOne_rryattTwo', 'rryattTwo_rryattOne', 'rryattTwo_rryattThree',
          'rryattThree_rryattTwo', 'rryattThree_rryattFour', 'rryattFour_rryattThree',
          'rryattFour_rryattFive', 'rryattFive_rryattFour')
DESTINATION_ROWS = (0, 0, 1, 0, 2, 1, 3, 2)



def matches_point(row, setup, returning):
    prefix = 'return_' if returning else ''
    raw = [float(setup[prefix+k]) for k in ('x','y','z')]
    ground = float(setup[prefix+'ground_y'])
    floor = float(setup.get('floor_y','nan')) if not returning else float('nan')
    point = [float(row[k]) for k in ('x','y','z')]
    if not all(math.isfinite(v) for v in raw+[ground]+point):
        return False
    # Prefer the actual collision surface over background terrain below a
    # platform. The standing-floor query reads geometry at the asserted X/Z,
    # rather than deriving an expected height from the player's location.
    standing = float(row.get('standing_floor_y','nan'))
    surface = max(ground,floor) if math.isfinite(floor) else ground
    heights = []
    if raw[1] >= surface-.1:
        heights.append(raw[1])
    if abs(surface-raw[1]) <= 3:
        heights.append(surface)
    if row.get('on_floor') == 'true' and math.isfinite(standing) and abs(standing-raw[1]) <= 3:
        heights.append(standing)
    return (abs(point[0]-raw[0]) <= .1 and abs(point[2]-raw[2]) <= .1 and
            any(abs(point[1]-height)<=.1 for height in heights))



def assert_arrival(before, after, setup, index, returning):
    """A coordinate match alone cannot establish the right linked instance."""
    anchor = int(setup['anchor'])
    if (not 0 <= index < len(ROUTES) or anchor not in (0,4,8,12,16,20) or
            setup['route'] != ROUTES[index] or int(before['buildout_row'])//4*4 != anchor):
        raise RuntimeError('Invalid linked-set route evidence')
    if (before['scene'] != 'kashyyyk_rryatt_trail' or after['scene'] != before['scene'] or
            before['instance'] != after['instance'] or
            before['instance_controller'] in ('null','0',None) or
            after['instance_controller'] != before['instance_controller'] or
            int(after['buildout_row']) != anchor+(0 if returning else DESTINATION_ROWS[index]) or
            after.get('last_rryatt_guide') != setup['target'] or
            after.get('outstanding') != 'false' or after.get('connected') != 'true'):
        raise RuntimeError('Guide travel changed the linked set, controller or saved guide')
    if not matches_point(after, setup, returning):
        raise RuntimeError('Guide travel missed its authored offset or terrain height')
