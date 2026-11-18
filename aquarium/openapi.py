"""The API description (OpenAPI 3) behind the API docs page (Settings > Advanced > API docs).

It's built for this install: the server address, the tanks and the test codes come from the database,
so the examples and drop-downs on the docs page are ones that work here.
"""
from django.http import JsonResponse
from django.shortcuts import render

from . import api_tanks
from .active import default_tank
from .models import DosingReservoir, ParameterType, SumpChamber, Tank


def _obj(properties, **extra):
    return {'type': 'object', 'properties': properties, **extra}


def _ref(name):
    return {'$ref': f'#/components/schemas/{name}'}


def _list_of(name):
    return {'type': 'array', 'items': _ref(name)}


NUMBER, INTEGER, STRING, BOOLEAN = {'type': 'number'}, {'type': 'integer'}, {'type': 'string'}, {'type': 'boolean'}


def _nullable(schema, description=''):
    return {**schema, 'nullable': True, **({'description': description} if description else {})}


def _tank_schemas():
    """The Tank system page as API objects: a tank, its sumps, their chambers, plumbing runs and equipment."""
    volume_from = {'type': 'string', 'enum': ['dimensions', 'typed'],
                   'description': 'Worked out from the size, or typed in by hand'}
    stage = {'type': 'string', 'enum': ['uncycled', 'cycled', 'mature']}
    return {
        'TankSummary': _obj({
            'id': INTEGER, 'name': STRING,
            'is_primary': {**BOOLEAN, 'description': 'Readings sent without a tank go to the primary tank'},
            'stage': stage,
            'has_sump': BOOLEAN, 'sump_count': INTEGER,
            'total_gallons': {**NUMBER, 'description': 'Display tank, sumps and plumbing (US gallons)'},
            'total_liters': NUMBER,
            'living_animals': {**INTEGER, 'description': 'Living animals in the tank (a group of 5 counts as 5)'},
            'url': {**STRING, 'description': "This tank's full detail"},
        }),
        'TankList': _obj({
            'count': {**INTEGER, 'description': 'How many current tanks you have'},
            'primary_tank_id': _nullable(INTEGER, 'Where readings sent without a tank go'),
            'tanks': _list_of('TankSummary'),
        }),
        'Dimensions': _obj({'width': NUMBER, 'depth': NUMBER, 'height': NUMBER,
                            'unit': {'type': 'string', 'enum': ['in', 'cm']}},
                           description='Inside measurements. null when any of them is missing.'),
        'Equipment': _obj({'id': INTEGER, 'name': STRING, 'category': {**STRING, 'example': 'return_pump'},
                           'status': {**STRING, 'example': 'operational'}}),
        'Water': _obj({
            'tank_gallons': {**NUMBER, 'description': "The tank's own volume, back chambers included"},
            'display_gallons': {**NUMBER, 'description': 'The water you see: the tank less any back chambers inside it'},
            'inside_gallons': {**NUMBER, 'description': 'All-in-one back chambers (part of tank_gallons)'},
            'sumps_gallons': {**NUMBER, 'description': 'Sumps below the tank'},
            'plumbing_gallons': {**NUMBER, 'description': 'Water held in the pipes'},
            'total_gallons': {**NUMBER, 'description': 'tank + sumps below + plumbing: the volume used for dosing'},
            'total_liters': NUMBER,
        }, description='How much water the system holds, in US gallons unless it says liters'),
        'Level': _nullable(_obj({
            'value': NUMBER, 'formatted_value': STRING, 'unit': {**STRING, 'example': 'mm'},
            'status': {'type': 'string', 'enum': ['low', 'optimal', 'high']},
            'measured_at': {'type': 'string', 'format': 'date-time'}, 'reading_id': INTEGER,
        }), 'The newest water level read here. null when it has never been read.'),
        'LevelTargets': _obj({'low_mm': _nullable(NUMBER, 'Flagged low under this'),
                              'high_mm': _nullable(NUMBER, 'Flagged high over this')},
                             description="This place's own water levels, set on its edit page"),
        'Reservoir': _obj({
            'id': INTEGER, 'name': STRING, 'type': {**STRING, 'example': 'ato'},
            'capacity': NUMBER, 'unit': STRING,
            'level': _ref('Level'), 'level_targets': _ref('LevelTargets'),
        }, description='ATO and dosing containers. Log a level with "reservoir": its id'),
        'Display': _obj({
            'dimensions': _nullable(_ref('Dimensions')), 'volume_from': volume_from,
            'fill_percent': {**NUMBER, 'description': 'Usable water as a % of the glass box'},
            'substrate': _nullable(STRING), 'live_rock': _nullable(STRING),
            'level': {**_ref('Level'), 'description': "The display's newest water level (one sent with no place)"},
            'equipment': {**_list_of('Equipment'), 'description': 'Equipment in the display tank'},
        }),
        'Chamber': _obj({
            'id': INTEGER, 'position': {**INTEGER, 'description': 'Order in the water path, 1 = first'},
            'name': STRING,
            'type': {'type': 'string', 'enum': [code for code, _ in SumpChamber.CHAMBER_TYPES]},
            'share_percent': {**NUMBER, 'description': "Share of the sump's water in this chamber"},
            'volume_gallons': NUMBER,
            'level': _ref('Level'), 'level_targets': _ref('LevelTargets'),
            'equipment': _list_of('Equipment'),
        }, description='Log a level here with "chamber": its id'),
        'Sump': _obj({
            'id': INTEGER, 'name': STRING,
            'location': {'type': 'string', 'enum': ['below', 'inside'],
                         'description': "'inside' is an all-in-one tank's back chambers: part of the tank's volume, not added to it"},
            'volume_gallons': NUMBER, 'volume_liters': NUMBER,
            'volume_from': volume_from,
            'fill_percent': {**NUMBER, 'description': 'How full the sump runs (its water level)'},
            'dimensions': _nullable(_ref('Dimensions')),
            'overflow': _nullable(STRING, 'The overflow feeding it, like "Corner overflow, back right"'),
            'head_height_ft': _nullable(NUMBER, 'How far the return pump lifts the water'),
            'chamber_share_total': _nullable(NUMBER, 'The chambers\' shares added up; 100 when the whole sump is divided'),
            'level': {**_ref('Level'), 'description': 'The newest level sent for the sump as a whole'},
            'level_targets': _ref('LevelTargets'),
            'equipment': {**_list_of('Equipment'), 'description': 'Equipment in the sump but not in a chamber'},
            'chambers': _list_of('Chamber'),
        }, description='Log a level for the whole sump with "sump": its id'),
        'PlumbingRun': _obj({'id': INTEGER, 'name': STRING, 'pipe': {**STRING, 'example': '1" PVC 40'},
                             'length': NUMBER, 'unit': {'type': 'string', 'enum': ['ft', 'm']},
                             'count': {**INTEGER, 'description': 'Identical pipes, like 2 drains'}, 'gallons': NUMBER}),
        'Plumbing': _obj({'total_feet': NUMBER, 'gallons': NUMBER, 'runs': _list_of('PlumbingRun')}),
        'Flow': _obj({
            'return_gph': INTEGER, 'wavemaker_gph': INTEGER, 'total_gph': INTEGER,
            'return_turnover': _nullable(NUMBER, 'Times an hour the return pump moves the whole system\'s water'),
            'circulation_turnover': _nullable(NUMBER, 'Times an hour all the flow moves the display tank\'s water'),
            'return_status': {'type': 'string', 'enum': ['low', 'ok', 'high', 'unknown']},
            'circulation_status': {'type': 'string', 'enum': ['low', 'ok', 'high', 'unknown']},
        }, description='Estimated from the pumps that are switched on'),
        'Lighting': _obj({'lights': INTEGER, 'watts_now': INTEGER, 'watts_full': INTEGER},
                         description='Display lights only; sump and refugium lights are under their sump'),
        'Tank': _obj({
            'id': INTEGER, 'name': STRING, 'is_primary': BOOLEAN, 'stage': stage, 'living_animals': INTEGER,
            'water': _ref('Water'), 'display': _ref('Display'),
            'has_sump': BOOLEAN, 'sumps': _list_of('Sump'), 'reservoirs': _list_of('Reservoir'),
            'plumbing': _ref('Plumbing'), 'flow': _ref('Flow'), 'lighting': _ref('Lighting'),
        }),
    }


def build_spec(request):
    tests = list(ParameterType.objects.in_use().order_by('display_order', 'name'))
    tanks = list(Tank.objects.filter(is_archived=False).order_by('position', 'pk'))
    primary = default_tank()
    codes = [t.code for t in tests]

    def middle(test):
        """A sensible value for the examples: the middle of the test's ideal range."""
        return round((float(test.min_ideal) + float(test.max_ideal)) / 2, test.decimal_places)
    by_code = {t.code: t for t in tests}
    example_test = by_code.get('alkalinity') or (tests[0] if tests else None)
    other_test = next((t for t in tests if t is not example_test and t.code != 'temperature'), None)
    first = example_test.code if example_test else 'alkalinity'
    reading_example = {'parameter': first, 'value': middle(example_test) if example_test else 8.4, 'notes': 'Hanna checker'}
    second_example = {'parameter': other_test.code, 'value': middle(other_test)} if other_test else {'parameter': first, 'value': reading_example['value']}
    test_list = ', '.join(f"`{t.code}` ({t.unit})" if t.unit else f"`{t.code}`" for t in tests) or 'none yet'
    tank_list = ', '.join(f"`{t.name}`" for t in tanks) or 'none yet'

    reading = {
        'type': 'object',
        'required': ['parameter', 'value'],
        'properties': {
            'parameter': {'type': 'string', 'description': "The test's code, name or ID (any case).", 'example': first,
                          **({'enum': codes} if codes else {})},
            'value': {'type': 'number', 'example': reading_example['value']},
            'unit': {'type': 'string', 'description': "Optional. The value's unit when it isn't the test's own, "
                                                      "such as °C or SG. It's converted; one the app can't convert is refused.",
                     'example': '°C'},
            'measured_at': {'type': 'string', 'format': 'date-time', 'description': 'Optional, ISO 8601. Defaults to now.',
                            'example': '2026-11-04T22:30:00Z'},
            'notes': {'type': 'string', 'maxLength': 255, 'example': 'Hanna checker'},
            'tank': {'type': 'string', 'description': f"Optional tank ID or name. Defaults to {primary.name if primary else 'the primary tank'}, "
                                                      "or the tank of the place given below.",
                     **({'enum': [t.name for t in tanks]} if tanks else {})},
            'chamber': {'type': 'string', 'description': "water_level only, optional: the sump chamber it was read in, by ID "
                                                         "(or a name only one chamber has, or 'Sump/Chamber'). See GET /api/tanks/{tank}/."},
            'sump': {'type': 'string', 'description': 'water_level only, optional: a sump (or all-in-one back section) as a whole, by ID or name.'},
            'reservoir': {'type': 'string', 'description': 'water_level only, optional: an ATO or dosing reservoir, by ID or name.'},
        },
        'description': ("Give at most one of chamber, sump or reservoir. With none, a water level is the display tank's. "
                        "A level read at a place is judged against that place's own low and high levels."),
    }
    tank_schemas = _tank_schemas()
    # Water level examples point at this install's own chambers and reservoirs where there are some
    chamber = SumpChamber.objects.filter(sump__tank__is_archived=False).select_related('sump').order_by('sump__tank__position', 'position').first()
    ato = (DosingReservoir.objects.filter(tank__is_archived=False).order_by('-reservoir_type').first())
    level_examples = {'level': {'summary': 'Water level in the display tank', 'value': {
        'parameter': 'water_level', 'value': 19.0, 'unit': 'cm', 'notes': 'Display level sensor'}}}
    level_examples['level_chamber'] = {
        'summary': f"Water level in a sump chamber{f' ({chamber.sump.name} › {chamber.plain_name})' if chamber else ''}",
        'value': {'parameter': 'water_level', 'value': 152, 'chamber': chamber.pk if chamber else 1, 'notes': 'Return chamber sensor'}}
    level_examples['level_reservoir'] = {
        'summary': f"Water level in a reservoir{f' ({ato.name})' if ato else ''}",
        'value': {'parameter': 'water_level', 'value': 9.5, 'unit': 'in', 'reservoir': ato.pk if ato else 1}}
    # The response examples are this install's own first tank, so the docs show real numbers
    first_tank = api_tanks._tanks().first()
    detail_example = api_tanks.tank_detail(first_tank) if first_tank else None
    list_example = ({'count': len(tanks), 'primary_tank_id': primary.pk if primary else None,
                     'tanks': [api_tanks.tank_summary(t, request) for t in api_tanks._tanks()]} if tanks else None)
    logged = {
        'type': 'object',
        'properties': {
            'id': {'type': 'integer'}, 'parameter': {'type': 'string'}, 'code': {'type': 'string'},
            'tank': {'type': 'string', 'nullable': True},
            'place': {'type': 'object', 'nullable': True, 'description': 'Where a water level was read; null for the display tank',
                      'properties': {'type': {'type': 'string', 'enum': ['chamber', 'sump', 'reservoir']},
                                     'id': {'type': 'integer'}, 'name': {'type': 'string'}}},
            'value': {'type': 'number'},
            'formatted_value': {'type': 'string'}, 'unit': {'type': 'string'}, 'decimal_places': {'type': 'integer'},
            'status': {'type': 'string', 'enum': ['low', 'optimal', 'high']},
            'measured_at': {'type': 'string', 'format': 'date-time'}, 'notes': {'type': 'string'},
        },
    }
    error = {'type': 'object', 'properties': {'error': {'type': 'string'}}}
    errors = {'type': 'object', 'properties': {'success': {'type': 'boolean', 'example': False},
                                               'errors': {'type': 'array', 'items': {'type': 'string'}}}}

    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'Nudibranch API',
            'version': '1',
            'description': (
                "Log water tests from probes, test kits, Home Assistant or your own scripts.\n\n"
                "**Authorize first:** press **Authorize** and paste the `API_SECRET_KEY` from your `.env` file. "
                "The key isn't saved; it's forgotten when you leave this page.\n\n"
                "**Try it out adds real readings** to your tanks. Delete any you don't want from the Water page.\n\n"
                f"Your tests: {test_list}.\n\nYour tanks: {tank_list}."
            ),
        },
        'servers': [{'url': request.build_absolute_uri('/').rstrip('/')}],
        'tags': [{'name': 'Tanks', 'description': 'The tanks readings can go to'},
                 {'name': 'Water tests', 'description': 'Reading and logging test results'}],
        'components': {
            'securitySchemes': {
                'ApiKey': {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'},
                'Bearer': {'type': 'http', 'scheme': 'bearer', 'description': 'The same key, sent as Authorization: Bearer <key>'},
            },
            'schemas': {**tank_schemas, 'Reading': reading, 'LoggedReading': logged, 'Error': error, 'Errors': errors},
        },
        'security': [{'ApiKey': []}, {'Bearer': []}],
        'paths': {
            '/api/tanks/': {
                'get': {
                    'tags': ['Tanks'],
                    'summary': 'List your tanks',
                    'description': ("Your current tanks in the order the app shows them. Send a tank's `id` or `name` as `tank` "
                                    "when logging readings; without one they go to the primary tank. Archived tanks aren't listed "
                                    "because they don't take new readings."),
                    'responses': {
                        '200': {'description': 'Your tanks', 'content': {'application/json': {
                            'schema': {'$ref': '#/components/schemas/TankList'},
                            **({'example': list_example} if list_example else {})}}},
                        '401': {'description': 'Missing or wrong key', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}},
                    },
                },
            },
            '/api/tanks/{tank}/': {
                'get': {
                    'tags': ['Tanks'],
                    'summary': "One tank's whole system",
                    'description': ("Everything the Tank system page shows: the display tank, each sump and its chambers "
                                    "in the order the water flows through them, plumbing, flow and lighting. Equipment is "
                                    "listed where it sits. Notes and prices are left out."),
                    'parameters': [{'name': 'tank', 'in': 'path', 'required': True, 'description': 'Tank ID or name (any case)',
                                    'schema': {'type': 'string', **({'example': str(tanks[0].pk)} if tanks else {})}}],
                    'responses': {
                        '200': {'description': 'The tank', 'content': {'application/json': {
                            'schema': {'$ref': '#/components/schemas/Tank'},
                            **({'example': detail_example} if detail_example else {})}}},
                        '401': {'description': 'Missing or wrong key', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}},
                        '404': {'description': 'Unknown or archived tank', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}},
                    },
                },
            },
            '/api/parameters/types/': {
                'get': {
                    'tags': ['Water tests'],
                    'summary': 'List your tests',
                    'description': "Each test's code, unit, decimals and target range. Add `tank` for that tank's own ranges.",
                    'parameters': [{'name': 'tank', 'in': 'query', 'required': False,
                                    'description': 'Tank ID or name', 'schema': {'type': 'string'}}],
                    'responses': {
                        '200': {'description': 'Your tests', 'content': {'application/json': {'schema': {
                            'type': 'object', 'properties': {'parameters': {'type': 'array', 'items': {
                                'type': 'object', 'properties': {
                                    'id': {'type': 'integer'}, 'name': {'type': 'string'}, 'code': {'type': 'string'},
                                    'unit': {'type': 'string'}, 'decimal_places': {'type': 'integer'},
                                    'min_ideal': {'type': 'number'}, 'max_ideal': {'type': 'number'},
                                    'formatted_min': {'type': 'string'}, 'formatted_max': {'type': 'string'},
                                    'color': {'type': 'string'}}}}}}}}},
                        '401': {'description': 'Missing or wrong key', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}},
                        '404': {'description': 'Unknown tank', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}},
                    },
                },
            },
            '/api/parameters/log/': {
                'post': {
                    'tags': ['Water tests'],
                    'summary': 'Log one or more readings',
                    'description': (
                        "Send one reading, or several as `readings`. A `tank` beside `readings` applies to all of them. "
                        "Readings that can't be used are listed under `warnings` while the rest are saved; "
                        "if none can be, the reply is 400 with `errors`."
                    ),
                    'requestBody': {
                        'required': True,
                        'content': {
                            'application/json': {
                                'schema': {'oneOf': [
                                    {'$ref': '#/components/schemas/Reading'},
                                    {'type': 'object', 'required': ['readings'], 'properties': {
                                        'tank': {'type': 'string', 'description': 'Tank ID or name for every reading'},
                                        'readings': {'type': 'array', 'items': {'$ref': '#/components/schemas/Reading'}}}},
                                ]},
                                'examples': {
                                    'one': {'summary': 'One reading', 'value': reading_example},
                                    'batch': {'summary': 'Several at once', 'value': {'readings': [reading_example, second_example]}},
                                    'unit': {'summary': 'A probe reporting °C', 'value': {'parameter': 'temperature', 'value': 25.6, 'unit': '°C'}},
                                    **(level_examples if 'water_level' in by_code else {}),
                                },
                            },
                            'application/x-www-form-urlencoded': {'schema': {'$ref': '#/components/schemas/Reading'}},
                        },
                    },
                    'responses': {
                        '201': {'description': 'Saved', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                            'success': {'type': 'boolean', 'example': True}, 'count': {'type': 'integer'},
                            'logs': {'type': 'array', 'items': {'$ref': '#/components/schemas/LoggedReading'}},
                            'warnings': {'type': 'array', 'items': {'type': 'string'}}}}}}},
                        '400': {'description': 'Nothing could be saved', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Errors'}}}},
                        '401': {'description': 'Missing or wrong key', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}},
                    },
                },
            },
        },
    }


def openapi_json(request):
    """GET /api/openapi.json - the API description, for the docs page or tools like Postman."""
    return JsonResponse(build_spec(request), json_dumps_params={'ensure_ascii': False})


def api_docs_view(request):
    """The Swagger docs page. It's a page of its own, so the app's styles (8-bit included) don't restyle Swagger."""
    return render(request, 'aquarium/api_docs.html')
