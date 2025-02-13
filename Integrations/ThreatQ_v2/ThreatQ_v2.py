import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *
''' IMPORTS '''
import requests
import json
import shutil
from typing import Dict, Any

# disable insecure warnings
requests.packages.urllib3.disable_warnings()

''' GLOBAL VARIABLES '''

SERVER_URL = demisto.params()['serverUrl'].rstrip('/')
API_URL = SERVER_URL + '/api'
CLIENT_ID = demisto.params()['client_id']
EMAIL = demisto.getParam('credentials').get('identifier')
PASSWORD = demisto.getParam('credentials').get('password')
USE_SSL = not demisto.params().get('insecure', False)
THRESHOLD = int(demisto.params().get('threshold', '0'))
if THRESHOLD:
    THRESHOLD = int(THRESHOLD)

domain_regex = r'(?i)(?:(?:https?|ftp|hxxps?):\/\/|www\[?\.\]?|ftp\[?\.\]?)(?:[-A-Z0-9]+\[?\.\]?)+[-A-Z0-9]+' \
               r'(?::[0-9]+)?(?:(?:\/|\?)[-A-Z0-9+&@#\/%=~_$?!:,.\(\);\*|]*[-A-Z0-9+&@#\/%=~_$\(\);\*|])?|' \
               r'\b[-A-Za-z0-9._%+\*|]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'

REGEX_MAP = {
    'email': re.compile(emailRegex, regexFlags),
    'url': re.compile(urlRegex, regexFlags),
    'md5': re.compile(r'\b[0-9a-fA-F]{32}\b', regexFlags),
    'sha1': re.compile(r'\b[0-9a-fA-F]{40}\b', regexFlags),
    'sha256': re.compile(r'\b[0-9a-fA-F]{64}\b', regexFlags),
    'domain': re.compile(domain_regex, regexFlags)
}

TQ_TO_DEMISTO_INDICATOR_TYPES = {
    'IP Address': 'ip',
    'IPv6 Address': 'ip',
    'Email Address': 'email',
    'URL': 'url',
    'MD5': 'file',
    'SHA-1': 'file',
    'SHA-256': 'file',
    'FQDN': 'domain'
}

STATUS_ID_TO_STATUS = {
    1: 'Active',
    2: 'Expired',
    3: 'Indirect',
    4: 'Review',
    5: 'Whitelisted'
}

TYPE_ID_TO_INDICATOR_TYPE = {
    1: 'Binary String',
    2: 'CIDR Block',
    3: 'CVE',
    4: 'Email Address',
    5: 'Email Attachment',
    6: 'Email Subject',
    7: 'File Mapping',
    8: 'File Path',
    9: 'Filename',
    10: 'FQDN',
    11: 'Fuzzy Hash',
    12: 'GOST Hash',
    13: 'Hash ION',
    14: 'IP Address',
    15: 'IPv6 Address',
    16: 'MD5',
    17: 'Mutex',
    18: 'Password',
    19: 'Registry Key',
    20: 'Service Name',
    21: 'SHA-1',
    22: 'SHA-256',
    23: 'SHA-384',
    24: 'SHA-512',
    25: 'String',
    26: 'x509 Serial',
    27: 'x509 Subject',
    28: 'URL',
    29: 'URL Path',
    30: 'User-agent',
    31: 'Username',
    32: 'X-Mailer'
}

TYPE_ID_TO_EVENT_TYPE = {
    1: 'Spearphish',
    2: 'Watering Hole',
    3: 'SQL Injection Attack',
    4: 'DoS Attack',
    5: 'Malware',
    6: 'Watchlist',
    7: 'Command and Control',
    8: 'Anonymization',
    9: 'Exfiltration',
    10: 'Host Characteristics',
    11: 'Compromised PKI Certificate',
    12: 'Login Compromise',
    13: 'Incident'
}

TYPE_ID_TO_FILE_TYPE = {
    1: 'Cuckoo',
    2: 'CrowdStrike Intelligence',
    3: 'Early Warning and Indicator Notice (EWIN)',
    4: 'FireEye Analysis',
    5: 'FBI FLASH',
    6: 'Generic Text',
    7: 'Intelligence Whitepaper',
    8: 'iSight Report',
    9: 'iSight ThreatScape Intelligence Report',
    10: 'IB',
    11: 'AEC',
    12: 'Malware Analysis Report',
    13: 'Malware Initial Findings Report (MFIR)',
    14: 'Malware Sample',
    15: 'Packet Capture',
    16: 'Palo Alto Networks WildFire XML',
    17: 'PCAP',
    18: 'PDF',
    19: 'Private Industry Notification (PIN)',
    20: 'Spearphish Attachment',
    21: 'STIX',
    22: 'ThreatAnalyzer Analysis',
    23: 'ThreatQ CSV File',
    24: 'Whitepaper'
}

TABLE_HEADERS = {
    'indicator': ['ID', 'Type', 'Value', 'Description', 'Status',
                  'TQScore', 'CreatedAt', 'UpdatedAt', 'URL'],
    'adversary': ['ID', 'Name', 'CreatedAt', 'UpdatedAt', 'URL'],
    'event': ['ID', 'Type', 'Title', 'Description', 'Occurred', 'CreatedAt', 'UpdatedAt', 'URL'],
    'attachment': ['ID', 'Name', 'Title', 'FileType', 'Size', 'Description', 'MD5', 'CreatedAt', 'UpdatedAt',
                   'MalwareLocked', 'ContentType', 'URL'],
    'attributes': ['ID', 'Name', 'Value'],
    'sources': ['ID', 'Name']
}

OBJ_DIRECTORY = {
    'indicator': 'indicators',
    'adversary': 'adversaries',
    'event': 'events',
    'attachment': 'attachments'
}

RELATED_KEY = {
    'indicator': 'RelatedIndicator',
    'adversary': 'RelatedAdversary',
    'event': 'RelatedEvent'
}

CONTEXT_PATH = {
    'indicator': 'ThreatQ.Indicator(val.ID === obj.ID)',
    'adversary': 'ThreatQ.Adversary(val.ID === obj.ID)',
    'event': 'ThreatQ.Event(val.ID === obj.ID)',
    'attachment': 'ThreatQ.File(val.ID === obj.ID)'
}


''' HELPER FUNCTIONS '''


def get_errors_string_from_bad_request(bad_request_results, status_code):
    if status_code == 404:
        return 'Object does not exist.\n'

    # Errors could be retrieved in two forms:
    # 1. A dictionary of fields and errors list related to the fields, all under 'data' key in the response json object
    # 2. A list, directly within the response object

    errors_string = 'Errors from service:\n\n'

    # First form
    errors_dict = bad_request_results.json().get('data', {}).get('errors', {})
    if errors_dict:
        for error_num, (key, lst) in enumerate(errors_dict.items(), 1):
            curr_error_string = '\n'.join(lst) + '\n\n'
            errors_string += 'Error #{0}. In \'{1}\':\n{2}'.format(error_num, key, curr_error_string)
        return errors_string

    # Second form
    errors_list = bad_request_results.json().get('errors', [])
    if errors_list:
        for error_num, error in enumerate(errors_list, 1):
            if isinstance(error, str):
                errors_string += 'Error #{0}: {1}\n'.format(error_num, error)
            else:  # error is a list
                for i in range(len(error)):
                    errors_string += 'Error #{0}.{1}: {2}\n'.format(error_num, i, error[i])
        return errors_string

    return str()  # Service did not provide any errors.


def tq_request(method, url_suffix, params=None, files=None, retrieve_entire_response=False, allow_redirects=True):
    api_call_headers = None
    if url_suffix != '/token':
        access_token = get_access_token()
        api_call_headers = {'Authorization': 'Bearer ' + access_token}

        if not files:
            params = json.dumps(params)

    response = requests.request(method, API_URL + url_suffix, data=params, headers=api_call_headers,
                                verify=USE_SSL, files=files, allow_redirects=allow_redirects)

    if response.status_code >= 400:
        errors_string = get_errors_string_from_bad_request(response, response.status_code)
        error_message = 'Received an error - status code [{0}].\n{1}'.format(response.status_code, errors_string)
        return_error(error_message)

    if retrieve_entire_response:
        return response
    elif method != 'DELETE':  # the DELETE request returns nothing in response
        return response.json()
    return None


def request_new_access_token():
    params = {'grant_type': 'password', 'email': EMAIL, 'password': PASSWORD, 'client_id': CLIENT_ID}
    access_token_response = tq_request('POST', '/token', params, allow_redirects=False)

    updated_integration_context = {
        'access_token': access_token_response['access_token'],
        'access_token_creation_time': int(time.time()) - 1,  # decrementing one second to be on the safe side
        'access_token_expires_in': access_token_response['expires_in']
    }
    demisto.setIntegrationContext(updated_integration_context)
    threatq_access_token = access_token_response['access_token']
    return threatq_access_token


def access_token_not_expired():
    epoch_time_now = time.time()
    epoch_time_when_token_granted = demisto.getIntegrationContext().get('access_token_creation_time')
    token_time_until_expiration = demisto.getIntegrationContext().get('access_token_expires_in')
    return int(epoch_time_now) - int(epoch_time_when_token_granted) < int(token_time_until_expiration)


def get_access_token():
    existing_access_token = demisto.getIntegrationContext().get('access_token')
    if existing_access_token and access_token_not_expired():
        return existing_access_token
    else:
        new_access_token = request_new_access_token()
        return new_access_token


def make_create_object_request(obj_type, params):
    url_suffix = '/{0}'.format(OBJ_DIRECTORY[obj_type])
    res = tq_request('POST', url_suffix, params)

    # For some reason, only while creating an indicator, the response data is a list of dicts with size 1.
    # Creating other objects simply returns one dict, as expected.
    data = res['data'][0] if obj_type == 'indicator' else res['data']
    raw = data_to_demisto_format(data, obj_type)

    entry_context = {CONTEXT_PATH[obj_type]: createContext(raw, removeNull=True)}

    readable_title = '{0} was successfully created.'.format(obj_type.title())
    readable = build_readable(readable_title, obj_type, raw)

    return_outputs(readable, entry_context, raw)


def make_edit_request_for_an_object(obj_id, obj_type, params):
    # Remove items with empty values.
    params = {k: v for k, v in params.items() if v is not None}

    url_suffix = '/{0}/{1}?with=attributes,sources'.format(OBJ_DIRECTORY[obj_type], obj_id)
    if obj_type == 'indicator':
        url_suffix += ',score'

    res = tq_request('PUT', url_suffix, params)

    raw = data_to_demisto_format(res['data'], obj_type)
    entry_context = {CONTEXT_PATH[obj_type]: createContext(raw, removeNull=True)}

    readable_title = 'Successfully edited {0} with ID {1}'.format(obj_type, obj_id)
    readable = build_readable(readable_title, obj_type, raw)

    return_outputs(readable, entry_context, raw)


def make_indicator_reputation_request(indicator_type, value, generic_context):
    # Search for the indicator ID by keyword:
    url_suffix = '/search?query={0}&limit=1'.format(value)
    res = tq_request('GET', url_suffix)

    raw_context = {}  # type: Dict[str, Any]
    if res['data'] and res['data'][0].get('value') == value:  # ThreatQ returns results whose prefixes match the query
        # Search for detailed information about the indicator
        url_suffix = '/indicators/{0}?with=attributes,sources,score,type'.format(res['data'][0].get('id'))
        res = tq_request('GET', url_suffix)
        raw_context = indicator_data_to_demisto_format(res['data'])

    dbot_context = create_dbot_context(value, indicator_type, raw_context.get('TQScore', -1))
    entry_context = set_indicator_entry_context(indicator_type, raw_context, dbot_context, generic_context)

    readable_title = 'Search results for {0} {1}'.format(indicator_type, value)
    readable = build_readable(readable_title, 'indicator', raw_context)

    return_outputs(readable, entry_context, raw_context)


def create_dbot_context(indicator, ind_type, ind_score):
    """ This function converts a TQ scoring value of an indicator into a DBot score.
    The default score mapping function is: -1 -> 0, [0,3] -> 1, [4,7] -> 2, [8,10] -> 3.

    If threshold parameter is set manually, it overrides the default function definition for a
    malicious indicator, such that TQ score >= threshold iff the DBot score == 3.

    Args:
        indicator (str): The indicator name
        ind_type (str): The indicator type
        ind_score (int): The indicator TQ score

    Returns:
        (dict). The indicator's DBotScore.

    """
    dbot_score_map = {
        -1: 0,
        0: 1,
        1: 1,
        2: 1,
        3: 1,
        4: 2,
        5: 2,
        6: 2,
        7: 2,
        8: 2,
        9: 2,
        10: 2
    }

    ret = {
        'Vendor': 'ThreatQ',
        'Indicator': indicator,
        'Type': ind_type
    }

    if ind_score >= THRESHOLD:
        ret['Score'] = 3
    else:
        ret['Score'] = dbot_score_map[ind_score]

    return ret


def get_tq_score_from_response(score_data):
    if score_data is None:
        return None
    if isinstance(score_data, dict):
        # score will be max(gen_score, manual_score)
        gen_score = str(score_data.get('generated_score'))
        manual_score = score_data.get('manual_score', 0.0)
        if manual_score is None:
            manual_score = -1
        return max(float(gen_score), float(manual_score))
    else:
        # score is already defined as a number
        return float(score_data)


def clean_html_from_string(raw_html):
    """ This function receives an HTML string of a text, and retrieves a clean string of its content.

    Args:
        raw_html: An HTML format text

    Returns:
        (string). A clean text string
    """
    if not raw_html:
        return None
    clean_r = re.compile('<.*?>')
    clean_text = re.sub(clean_r, '', raw_html)
    return clean_text


def sources_to_request_format(sources):
    if not sources:
        return []
    if isinstance(sources, str):
        sources = sources.split(',')
    return [{'name': source} for source in sources]


def sources_to_demisto_format(lst):
    if lst is None:
        return None
    return [{
        'Name': elem.get('name'),
        'ID': elem.get('pivot', {}).get('id')
    } for elem in lst]


def attributes_to_request_format(attributes_names, attributes_values):
    if not attributes_names and not attributes_values:
        return []
    if isinstance(attributes_names, str):
        attributes_names = attributes_names.split(',')
    if isinstance(attributes_values, str):
        attributes_values = attributes_values.split(',')
    if not attributes_names or not attributes_values or len(attributes_names) != len(attributes_values):
        return_error('Attributes_names and attributes_values arguments must have the same length.')

    return [{'name': name, 'value': val} for name, val in zip(attributes_names, attributes_values)]


def attributes_to_demisto_format(lst):
    if lst is None:
        return None
    return [{
        'Name': elem.get('name'),
        'Value': elem.get('value'),
        'ID': elem.get('id')
    } for elem in lst]


def content_type_to_demisto_format(c_type_id):
    # content_type is a file object property
    return 'text/plain' if c_type_id == 1 else 'text/rtf'


def malware_locked_to_request_format(state):
    # malware_locked is a file object property
    if not state:
        return None
    return 1 if state == 'on' else 0


def malware_locked_to_demisto_format(state):
    return 'on' if state == 1 else 'off'


def parse_date(text):
    valid_formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']
    for fmt in valid_formats:
        try:
            return str(datetime.strptime(text, fmt))
        except ValueError:
            pass
    return_error('Time data \'{0}\' does not match any valid format.'.format(text))


def data_to_demisto_format(data, obj_type):
    if obj_type == 'indicator':
        return indicator_data_to_demisto_format(data)
    elif obj_type == 'event':
        return event_data_to_demisto_format(data)
    elif obj_type == 'adversary':
        return adversary_data_to_demisto_format(data)
    elif obj_type == 'attachment':
        return file_data_to_demisto_format(data)


def indicator_data_to_demisto_format(data):
    ret = {
        'ID': data.get('id'),
        'UpdatedAt': data.get('updated_at'),
        'CreatedAt': data.get('created_at'),
        'Value': data.get('value'),
        'Status': STATUS_ID_TO_STATUS[data.get('status_id')],
        'Type': TYPE_ID_TO_INDICATOR_TYPE[data.get('type_id')],
        'URL': '{0}/indicators/{1}/details'.format(SERVER_URL, data.get('id')),
        'TQScore': get_tq_score_from_response(data.get('score')),
        'Description': clean_html_from_string(data.get('description')),
        'Source': sources_to_demisto_format(data.get('sources')),
        'Attribute': attributes_to_demisto_format(data.get('attributes'))
    }
    return ret


def adversary_data_to_demisto_format(data):
    ret = {
        'ID': data.get('id'),
        'UpdatedAt': data.get('updated_at'),
        'CreatedAt': data.get('created_at'),
        'Name': data.get('name'),
        'URL': '{0}/indicators/{1}/details'.format(SERVER_URL, data.get('id')),
        'Source': sources_to_demisto_format(data.get('sources')),
        'Attribute': attributes_to_demisto_format(data.get('attributes'))
    }
    return ret


def event_data_to_demisto_format(data):
    ret = {
        'ID': data.get('id'),
        'UpdatedAt': data.get('updated_at'),
        'CreatedAt': data.get('created_at'),
        'Title': data.get('title'),
        'Occurred': data.get('happened_at'),
        'Type': TYPE_ID_TO_EVENT_TYPE[data.get('type_id')],
        'URL': '{0}/indicators/{1}/details'.format(SERVER_URL, data.get('id')),
        'Description': clean_html_from_string(data.get('description')),
        'Source': sources_to_demisto_format(data.get('sources')),
        'Attribute': attributes_to_demisto_format(data.get('attributes'))
    }
    return ret


def file_data_to_demisto_format(data):
    raw = {
        'ID': data.get('id'),
        'CreatedAt': data.get('created_at'),
        'UpdatedAt': data.get('updated_at'),
        'Size': data.get('file_size'),
        'MD5': data.get('hash'),
        'Type': TYPE_ID_TO_FILE_TYPE[data.get('type_id')],
        'Name': data.get('name'),
        'Title': data.get('title'),
        'Description': data.get('description'),
        'ContentType': content_type_to_demisto_format(data.get('content_type_id')),
        'MalwareLocked': malware_locked_to_demisto_format(data.get('content_type_id')),
        'Source': sources_to_demisto_format(data.get('sources')),
        'Attribute': attributes_to_demisto_format(data.get('attributes'))
    }

    return raw


def get_pivot_id(obj1_type, obj1_id, obj2_type, obj2_id):
    # A pivot id represents a connection between two objects.

    url_suffix = '/{0}/{1}/{2}'.format(OBJ_DIRECTORY[obj1_type], obj1_id, OBJ_DIRECTORY[obj2_type])
    res = tq_request('GET', url_suffix)

    for related_object in res['data']:  # res['data'] contains all the related objects of obj_id1
        if int(related_object.get('id')) == int(obj2_id):
            return int(related_object['pivot']['id'])
    else:
        return_error('Command failed - objects are not related.')


def add_malicious_data(generic_context, tq_score):
    generic_context['Malicious'] = {
        'Vendor': 'ThreatQ',
        'Description': 'Score from ThreatQ is {0}'.format(tq_score)
    }


def set_indicator_entry_context(indicator_type, raw, dbot, generic):
    if dbot.get('Score') == 3:
        add_malicious_data(generic, raw.get('TQScore', -1))

    ec = {
        outputPaths[indicator_type]: generic,
        'DBotScore': dbot
    }
    if raw:
        ec[CONTEXT_PATH['indicator']] = raw
    return ec


def build_readable_for_search_by_name(indicator_context, event_context, adversary_context, file_context):
    if not (indicator_context or event_context or adversary_context or file_context):
        return 'No results.'

    human_readable = ''
    if indicator_context:
        human_readable += tableToMarkdown('Search Results - Indicators', indicator_context)
    if event_context:
        human_readable += tableToMarkdown('Search Results - Events', event_context)
    if adversary_context:
        human_readable += tableToMarkdown('Search Results - Adversaries', adversary_context)
    if file_context:
        human_readable += tableToMarkdown('Search Results - Files', file_context)

    return human_readable


def build_readable(readable_title, obj_type, data, metadata=None):
    if isinstance(data, dict):  # One object data
        readable = tableToMarkdown(readable_title, data, headers=TABLE_HEADERS[obj_type],
                                   headerTransform=pascalToSpace, removeNull=True, metadata=metadata)
        if 'Attribute' in data:
            readable += tableToMarkdown('Attributes', data['Attribute'], headers=TABLE_HEADERS['attributes'],
                                        removeNull=True, headerTransform=pascalToSpace, metadata=metadata)
        if 'Source' in data:
            readable += tableToMarkdown('Sources', data['Source'], headers=TABLE_HEADERS['sources'],
                                        removeNull=True, headerTransform=pascalToSpace, metadata=metadata)
        if 'URL' in data:
            url_in_markdown_format = '[{0}]({1})'.format(data['URL'], data['URL'])
            readable = readable.replace(data['URL'], url_in_markdown_format)

    else:  # 'data' is a list of objects
        readable = tableToMarkdown(readable_title, data, headers=TABLE_HEADERS[obj_type],
                                   headerTransform=pascalToSpace, removeNull=True, metadata=metadata)
        for elem in data:
            url_in_markdown_format = '[{0}]({1})'.format(elem['URL'], elem['URL'])
            readable = readable.replace(elem['URL'], url_in_markdown_format)

    return readable


''' COMMANDS '''


def test_module():
    token = request_new_access_token()
    threshold = demisto.params().get('threshold')
    threshold_is_integer = isinstance(threshold, int) or (isinstance(threshold, str) and threshold.isdigit())
    if token and threshold_is_integer and 0 <= int(threshold) <= 10:
        demisto.results('ok')


def search_by_name_command():
    args = demisto.args()
    name = args.get('name')
    limit = args.get('limit')

    if limit and isinstance(limit, str) and not limit.isdigit():
        return_error('limit argument must be an integer.')

    url_suffix = '/search?query={0}&limit={1}'.format(name, limit)
    res = tq_request('GET', url_suffix)

    indicator_context = [{'ID': e['id'], 'Value': e['value']} for e in res['data'] if e['object'] == 'indicator']
    event_context = [{'ID': e['id'], 'Title': e['value']} for e in res['data'] if e['object'] == 'event']
    adversary_context = [{'ID': e['id'], 'Name': e['value']} for e in res['data'] if e['object'] == 'adversary']
    file_context = [{'ID': e['id'], 'Name': e['value'].split()[1]} for e in res['data'] if e['object'] == 'attachment']
    # file value in response is returned in the form ["title" name], thus we use the split method above

    entry_context = {
        CONTEXT_PATH['indicator']: indicator_context,
        CONTEXT_PATH['event']: event_context,
        CONTEXT_PATH['adversary']: adversary_context,
        CONTEXT_PATH['attachment']: file_context
    }

    # Remove items with empty values:
    entry_context = {k: v for k, v in entry_context.items() if v}

    human_readable = build_readable_for_search_by_name(indicator_context, event_context, adversary_context, file_context)

    return_outputs(human_readable, entry_context)


def search_by_id_command():
    args = demisto.args()
    obj_type = args.get('obj_type')
    obj_id = args.get('obj_id')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')

    url_suffix = '/{0}/{1}?with=attributes,sources'.format(OBJ_DIRECTORY[obj_type], obj_id)
    if obj_type == 'indicator':
        url_suffix += ',score,type'

    res = tq_request('GET', url_suffix)
    raw = data_to_demisto_format(res['data'], obj_type)

    ec = {CONTEXT_PATH[obj_type]: createContext(raw, removeNull=True)}

    if obj_type == 'indicator':
        indicator_type = TQ_TO_DEMISTO_INDICATOR_TYPES.get(raw['Type'])
        if indicator_type is not None:
            ec['DBotScore'] = create_dbot_context(raw['Value'], indicator_type, raw['TQScore'])

    readable_title = 'Search results for {0} with ID {1}'.format(obj_type, obj_id)
    readable = build_readable(readable_title, obj_type, raw)

    return_outputs(readable, ec, raw)


def create_indicator_command():
    args = demisto.args()
    indicator_type = args.get('type')
    status = args.get('status')
    value = args.get('value')
    sources = args.get('sources')
    attributes_names = args.get('attributes_names')
    attributes_values = args.get('attributes_values')

    params = {
        'type': indicator_type,
        'status': status,
        'value': value,
        'sources': sources_to_request_format(sources),
        'attributes': attributes_to_request_format(attributes_names, attributes_values)
    }

    make_create_object_request('indicator', params)


def create_adversary_command():
    args = demisto.args()
    name = args.get('name')
    sources = args.get('sources')
    attributes_names = args.get('attributes_names')
    attributes_values = args.get('attributes_values')

    params = {
        'name': name,
        'sources': sources_to_request_format(sources),
        'attributes': attributes_to_request_format(attributes_names, attributes_values)
    }

    make_create_object_request('adversary', params)


def create_event_command():
    args = demisto.args()
    event_type = args.get('type')
    title = args.get('title')
    date = args.get('date')
    sources = args.get('sources')
    attributes_names = args.get('attributes_names')
    attributes_values = args.get('attributes_values')

    params = {
        'title': title,
        'type': event_type,
        'happened_at': parse_date(date),
        'sources': sources_to_request_format(sources),
        'attributes': attributes_to_request_format(attributes_names, attributes_values)
    }

    make_create_object_request('event', params)


def edit_indicator_command():
    args = demisto.args()
    indicator_id = args.get('id')
    value = args.get('value')
    indicator_type = args.get('type')
    description = args.get('description')

    if isinstance(indicator_id, str) and not indicator_id.isdigit():
        return_error('id argument must be an integer.')

    params = {
        'value': value,
        'type': indicator_type,
        'description': description
    }

    make_edit_request_for_an_object(indicator_id, 'indicator', params)


def edit_adversary_command():
    args = demisto.args()
    adversary_id = args.get('id')
    name = args.get('name')

    if isinstance(adversary_id, str) and not adversary_id.isdigit():
        return_error('id argument must be an integer.')

    params = {
        'name': name
    }

    make_edit_request_for_an_object(adversary_id, 'adversary', params)


def edit_event_command():
    args = demisto.args()
    event_id = args.get('id')
    event_type = args.get('type')
    title = args.get('title')
    date = args.get('date')
    description = args.get('description')

    if isinstance(event_id, str) and not event_id.isdigit():
        return_error('id argument must be an integer.')

    params = {
        'title': title,
        'happened_at': parse_date(date) if date else None,
        'type': event_type,
        'description': description
    }

    make_edit_request_for_an_object(event_id, 'event', params)


def delete_object_command():
    args = demisto.args()
    obj_type = args.get('obj_type')
    obj_id = args.get('obj_id')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')

    url_suffix = '/{0}/{1}'.format(OBJ_DIRECTORY[obj_type], obj_id)
    tq_request('DELETE', url_suffix)
    demisto.results('Successfully deleted {0} with ID {1}.'.format(obj_type, obj_id))


def get_related_objs_command(related_type):
    args = demisto.args()
    obj_type = args.get('obj_type')
    obj_id = args.get('obj_id')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')

    url_suffix = '/{0}/{1}/{2}?with=sources'.format(OBJ_DIRECTORY[obj_type], obj_id, OBJ_DIRECTORY[related_type])
    if related_type == 'indicator':
        url_suffix += ',score'
    res = tq_request('GET', url_suffix)

    info = [data_to_demisto_format(obj, related_type) for obj in res['data']]
    info = createContext(info, removeNull=True)
    raw = {
        RELATED_KEY[related_type]: createContext(info, removeNull=True),
        'ID': int(obj_id)
    }
    ec = {CONTEXT_PATH[obj_type]: raw} if info else {}

    readable_title = 'Related {0} type objects of {1} with ID {2}'.format(related_type, obj_type, obj_id)
    readable = build_readable(readable_title, related_type, raw[RELATED_KEY[related_type]])

    return_outputs(readable, ec, raw)


def link_objects_command():
    args = demisto.args()
    obj1_type = args.get('obj1_type')
    obj1_id = args.get('obj1_id')
    obj2_type = args.get('obj2_type')
    obj2_id = args.get('obj2_id')

    if isinstance(obj1_id, str) and not obj1_id.isdigit() or isinstance(obj2_id, str) and not obj2_id.isdigit():
        return_error('obj1_id, obj2_id arguments must be integers.')

    if obj1_type == obj2_type and obj1_id == obj2_id:
        return_error('Cannot link an object to itself.')

    url_suffix = '/{0}/{1}/{2}'.format(OBJ_DIRECTORY[obj1_type], obj1_id, OBJ_DIRECTORY[obj2_type])
    params = {
        'id': obj2_id
    }
    tq_request('POST', url_suffix, params)
    demisto.results(
        'Successfully linked {0} with ID {1} and {2} with ID {3}.'.format(obj1_type, obj1_id, obj2_type, obj2_id))


def unlink_objects_command():
    args = demisto.args()
    obj1_type = args.get('obj1_type')
    obj1_id = args.get('obj1_id')
    obj2_type = args.get('obj2_type')
    obj2_id = args.get('obj2_id')

    if isinstance(obj1_id, str) and not obj1_id.isdigit() or isinstance(obj2_id, str) and not obj2_id.isdigit():
        return_error('obj1_id, obj2_id arguments must be integers.')

    if obj1_type == obj2_type and obj1_id == obj2_id:
        return_error('An object cannot be linked to itself.')

    p_id = get_pivot_id(obj1_type, obj1_id, obj2_type, obj2_id)
    url_suffix = '/{0}/{1}/{2}'.format(OBJ_DIRECTORY[obj1_type], obj1_id, OBJ_DIRECTORY[obj2_type])
    tq_request('DELETE', url_suffix, params=[p_id])
    demisto.results(
        'Successfully unlinked {0} with ID {1} and {2} with ID {3}.'.format(obj1_type, obj1_id, obj2_type, obj2_id))


def update_score_command():
    # Note: We can't update DBot Score because API doesn't retrieve the indicator value.
    args = demisto.args()
    indicator_id = args.get('id')
    score = args.get('score')

    if isinstance(indicator_id, str) and not indicator_id.isdigit():
        return_error('id argument must be an integer.')

    if isinstance(score, str) and not score.isdigit():  # User chose 'Generated Score' option
        manual_score = None
    else:
        manual_score = int(score)

    url_suffix = '/indicator/{0}/scores'.format(indicator_id)
    params = {'manual_score': manual_score}

    res = tq_request('PUT', url_suffix, params)

    raw = {
        'ID': int(indicator_id),
        'TQScore': get_tq_score_from_response(res['data'])
    }

    ec = {CONTEXT_PATH['indicator']: raw}

    readable = 'Successfully updated score of indicator with ID {0} to {1}. '\
               'Notice that final score is the maximum between ' \
               'manual and generated scores.'.format(indicator_id, int(raw['TQScore']))

    return_outputs(readable, ec, raw)


def add_source_command():
    args = demisto.args()
    source = args.get('source')
    obj_id = args.get('obj_id')
    obj_type = args.get('obj_type')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')

    url_suffix = '/{0}/{1}/sources'.format(OBJ_DIRECTORY[obj_type], obj_id)
    params = {
        'name': source
    }

    tq_request('POST', url_suffix, params)
    demisto.results('Successfully added source {0} to {1} with ID {2}.'.format(source, obj_type, obj_id))


def delete_source_command():
    args = demisto.args()
    source_id = args.get('source_id')
    obj_id = args.get('obj_id')
    obj_type = args.get('obj_type')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')
    if isinstance(source_id, str) and not source_id.isdigit():
        return_error('source_id argument must be an integer.')

    url_suffix = '/{0}/{1}/sources/{2}'.format(OBJ_DIRECTORY[obj_type], obj_id, source_id)

    tq_request('DELETE', url_suffix)
    demisto.results('Successfully deleted source #{0} from {1} with ID {2}.'.format(source_id, obj_type, obj_id))


def add_attribute_command():
    args = demisto.args()
    attribute_name = args.get('name')
    attribute_value = args.get('value')
    obj_type = args.get('obj_type')
    obj_id = args.get('obj_id')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')

    url_suffix = '/{0}/{1}/attributes'.format(OBJ_DIRECTORY[obj_type], obj_id)
    params = {
        'name': attribute_name,
        'value': attribute_value
    }

    tq_request('POST', url_suffix, params)
    demisto.results('Successfully added attribute to {0} with ID {1}.'.format(obj_type, obj_id))


def modify_attribute_command():
    args = demisto.args()
    attribute_id = args.get('attribute_id')
    attribute_value = args.get('attribute_value')
    obj_type = args.get('obj_type')
    obj_id = args.get('obj_id')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')
    if isinstance(attribute_id, str) and not attribute_id.isdigit():
        return_error('attribute_id argument must be an integer.')

    url_suffix = '/{0}/{1}/attributes/{2}'.format(OBJ_DIRECTORY[obj_type], obj_id, attribute_id)
    params = {'value': attribute_value}

    tq_request('PUT', url_suffix, params)

    demisto.results('Successfully modified attribute #{0} of {1} with ID {2}.'.format(attribute_id, obj_type, obj_id))


def delete_attribute_command():
    args = demisto.args()
    attribute_id = args.get('attribute_id')
    obj_type = args.get('obj_type')
    obj_id = args.get('obj_id')

    if isinstance(obj_id, str) and not obj_id.isdigit():
        return_error('obj_id argument must be an integer.')
    if isinstance(attribute_id, str) and not attribute_id.isdigit():
        return_error('attribute_id argument must be an integer.')

    url_suffix = '/{0}/{1}/attributes/{2}'.format(OBJ_DIRECTORY[obj_type], obj_id, attribute_id)

    tq_request('DELETE', url_suffix)
    demisto.results('Successfully deleted attribute #{0} from {1} with ID {2}.'.format(attribute_id, obj_type, obj_id))


def update_status_command():
    args = demisto.args()
    indicator_id = args.get('id')
    status = args.get('status')

    if isinstance(indicator_id, str) and not indicator_id.isdigit():
        return_error('id argument must be an integer.')

    url_suffix = '/indicators/{0}'.format(indicator_id)
    params = {'status': status}

    res = tq_request('PUT', url_suffix, params)

    raw = {
        'ID': int(indicator_id),
        'Status': STATUS_ID_TO_STATUS[res['data'].get('status_id')],
    }

    ec = {CONTEXT_PATH['indicator']: raw}

    readable = 'Successfully updated status of indicator with ID {0} to {1}.'.format(indicator_id, status)

    return_outputs(readable, ec, raw)


def upload_file_command():
    args = demisto.args()
    entry_id = args.get('entry_id')
    title = args.get('title')
    malware_safety_lock = args.get('malware_safety_lock')
    file_category = args.get('file_category')

    file_info = demisto.getFilePath(entry_id)

    if not title:
        title = file_info['name']

    params = {
        'name': file_info['name'],
        'title': title,
        'type': file_category,
        'malware_locked': malware_locked_to_request_format(malware_safety_lock)
    }

    try:
        shutil.copy(file_info['path'], file_info['name'])
    except Exception as e:
        return_error('Failed to prepare file for upload. Error message: {0}'.format(str(e)))

    try:
        with open(file_info['name'], 'rb') as f:
            files = {'file': f}
            url_suffix = '/attachments'
            res = tq_request('POST', url_suffix, params, files=files)
    finally:
        shutil.rmtree(file_info['name'], ignore_errors=True)

    raw = file_data_to_demisto_format(res['data'])

    ec = {CONTEXT_PATH['attachment']: raw}

    readable_title = 'Successfully uploaded file {0}.'.format(file_info['name'])
    readable = build_readable(readable_title, 'attachment', raw)

    return_outputs(readable, ec, raw)


def download_file_command():
    args = demisto.args()
    file_id = args.get('id')

    if isinstance(file_id, str) and not file_id.isdigit():
        return_error('id argument must be an integer.')

    url_suffix = '/attachments/{0}/download'.format(file_id)

    res = tq_request('GET', url_suffix, retrieve_entire_response=True)

    # 'Content-Disposition' value is of the form: attachment; filename="filename.txt"
    # Since we don't have the file name anywhere else in the response object, we parse it from this entry.
    filename = res.headers.get('Content-Disposition', str()).split('\"')[1]
    content = res.content

    demisto.results(fileResult(filename, content))


def get_all_objs_command(obj_type):
    args = demisto.args()
    page = int(args.get('page'))
    limit = int(args.get('limit'))
    if limit > 200:
        limit = 200

    url_suffix = '/{0}?with=attributes,sources'.format(OBJ_DIRECTORY[obj_type])
    if obj_type == 'indicator':
        url_suffix += ',score'
    res = tq_request('GET', url_suffix)

    from_index = page
    to_index = min(page + limit, len(res['data']))

    raw = [data_to_demisto_format(obj, obj_type) for obj in res['data'][from_index:to_index]]
    ec = {CONTEXT_PATH[obj_type]: createContext(raw, removeNull=True)} if raw else {}

    readable_title = 'List of all objects of type {0} - {1}-{2}'.format(obj_type, from_index, to_index - 1)
    metadata = 'Total number of objects is {0}'.format(len(res['data']))
    readable = build_readable(readable_title, obj_type, raw, metadata=metadata)

    return_outputs(readable, ec, raw)


def get_ip_reputation():
    args = demisto.args()
    ip = args.get('ip')

    if not is_ip_valid(ip, accept_v6_ips=True):
        return_error('{0} is not a valid IP address.'.format(ip))

    generic_context = {'Address': ip}

    make_indicator_reputation_request(indicator_type='ip', value=ip, generic_context=generic_context)


def get_url_reputation():
    args = demisto.args()
    url = args.get('url')

    if not REGEX_MAP['url'].match(url):
        return_error('{0} is not a valid URL.'.format(url))

    generic_context = {'Data': url}

    make_indicator_reputation_request(indicator_type='url', value=url, generic_context=generic_context)


def get_email_reputation():
    args = demisto.args()
    email = args.get('email')

    if not REGEX_MAP['email'].match(email):
        return_error('{0} is not a valid email address.'.format(email))

    generic_context = {'Address': email}

    make_indicator_reputation_request(indicator_type='email', value=email, generic_context=generic_context)


def get_domain_reputation():
    args = demisto.args()
    domain = args.get('domain')

    if not REGEX_MAP['domain'].match(domain):
        return_error('{0} is not a valid domain.'.format(domain))

    generic_context = {'Name': domain}

    make_indicator_reputation_request(indicator_type='domain', value=domain, generic_context=generic_context)


def get_file_reputation():
    args = demisto.args()
    file = args.get('file')

    for fmt in ['md5', 'sha1', 'sha256']:
        if REGEX_MAP[fmt].match(file):
            break
    else:
        return_error('{0} is not a valid file format.'.format(file))

    generic_context = createContext({
        'MD5': file if fmt == 'md5' else None,
        'SHA1': file if fmt == 'sha1' else None,
        'SHA256': file if fmt == 'sha256' else None
    }, removeNull=True)

    make_indicator_reputation_request(indicator_type='file', value=file, generic_context=generic_context)


''' EXECUTION CODE '''
command = demisto.command()
LOG('command is {0}'.format(demisto.command()))
try:
    handle_proxy()
    if command == 'test-module':
        test_module()
    elif command == 'threatq-search-by-name':
        search_by_name_command()
    elif command == 'threatq-search-by-id':
        search_by_id_command()
    elif command == 'threatq-create-indicator':
        create_indicator_command()
    elif command == 'threatq-create-event':
        create_event_command()
    elif command == 'threatq-create-adversary':
        create_adversary_command()
    elif command == 'threatq-edit-indicator':
        edit_indicator_command()
    elif command == 'threatq-edit-event':
        edit_event_command()
    elif command == 'threatq-edit-adversary':
        edit_adversary_command()
    elif command == 'threatq-delete-object':
        delete_object_command()
    elif command == 'threatq-get-related-indicators':
        get_related_objs_command('indicator')
    elif command == 'threatq-get-related-events':
        get_related_objs_command('event')
    elif command == 'threatq-get-related-adversaries':
        get_related_objs_command('adversary')
    elif command == 'threatq-link-objects':
        link_objects_command()
    elif command == 'threatq-unlink-objects':
        unlink_objects_command()
    elif command == 'threatq-update-score':
        update_score_command()
    elif command == 'threatq-add-source':
        add_source_command()
    elif command == 'threatq-delete-source':
        delete_source_command()
    elif command == 'threatq-add-attribute':
        add_attribute_command()
    elif command == 'threatq-modify-attribute':
        modify_attribute_command()
    elif command == 'threatq-delete-attribute':
        delete_attribute_command()
    elif command == 'threatq-update-status':
        update_status_command()
    elif command == 'threatq-upload-file':
        upload_file_command()
    elif command == 'threatq-download-file':
        download_file_command()
    elif command == 'threatq-get-all-indicators':
        get_all_objs_command('indicator')
    elif command == 'threatq-get-all-events':
        get_all_objs_command('event')
    elif command == 'threatq-get-all-adversaries':
        get_all_objs_command('adversary')
    elif command == 'ip':
        get_ip_reputation()
    elif command == 'domain':
        get_domain_reputation()
    elif command == 'email':
        get_email_reputation()
    elif command == 'url':
        get_url_reputation()
    elif command == 'file':
        get_file_reputation()

except Exception as ex:
    return_error(str(ex))
