"""The API description (OpenAPI 3) behind the API docs page (Settings > Advanced > API docs).

It's built for this install: the server address, the tanks and the test codes come from the database,
so the examples and drop-downs on the docs page are ones that work here.
"""
from django.http import JsonResponse
from django.shortcuts import render

from .active import default_tank
from .models import ParameterType, Tank


def build_spec(request):
    tests = list(ParameterType.objects.in_use().order_by('display_order', 'name'))
    tanks = list(Tank.objects.filter(is_archived=False))
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
            'tank': {'type': 'string', 'description': f"Optional tank ID or name. Defaults to {primary.name if primary else 'the primary tank'}.",
                     **({'enum': [t.name for t in tanks]} if tanks else {})},
        },
    }
    logged = {
        'type': 'object',
        'properties': {
            'id': {'type': 'integer'}, 'parameter': {'type': 'string'}, 'code': {'type': 'string'},
            'tank': {'type': 'string', 'nullable': True}, 'value': {'type': 'number'},
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
        'tags': [{'name': 'Water tests', 'description': 'Reading and logging test results'}],
        'components': {
            'securitySchemes': {
                'ApiKey': {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'},
                'Bearer': {'type': 'http', 'scheme': 'bearer', 'description': 'The same key, sent as Authorization: Bearer <key>'},
            },
            'schemas': {'Reading': reading, 'LoggedReading': logged, 'Error': error, 'Errors': errors},
        },
        'security': [{'ApiKey': []}, {'Bearer': []}],
        'paths': {
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
