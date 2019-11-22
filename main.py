import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import re
import json
from geopy.geocoders import Nominatim
import hashlib

# CONSTANTS
TODAY_DATE = datetime.combine(datetime.today(), datetime.min.time())
TOMORROW_DATE = TODAY_DATE + timedelta(days=1)
GEOLOCATOR = Nominatim(user_agent="orarifarmacie")

# GLOBALS
lat_lng_cache = {}


def timestr_to_datetime(time_str, date):
    if time_str == '24:00':
        return date + timedelta(days=1)
    else:
        return datetime.combine(date, datetime.strptime(time_str, '%H:%M').time())


def get_lat_lng_from_address(address):
    print('Getting coords for address: %s' % address)
    latitude = ''
    longitude = ''

    global GEOLOCATOR
    try:
        location = GEOLOCATOR.geocode(address)
    except Exception:
        location = None
    if location is not None:
        latitude = location.latitude
        longitude = location.longitude
    return latitude, longitude


def get_drugstore_id(drugstore_result):
    return hashlib.sha1(drugstore_result['name'].encode()).hexdigest()


def get_names_and_timestamps(url, date):
    result_list = []

    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    # get names
    dom_names = soup.select(".bb:not(.c) > b")
    for i, dom_name in enumerate(dom_names):
        name = ''
        for j, string in enumerate(dom_name.stripped_strings):
            name += (' ' if j > 0 else '')
            name += string
        result_list.append({'name': name})

    # get addresses
    dom_addresses = soup.select(".bb:not(.c)")
    for i, dom_address in enumerate(dom_addresses):
        for b in dom_address.select('b'):
            b.decompose()
        address = ''
        fraction = ''
        city = ''
        province = ''
        for j, string in enumerate(dom_address.stripped_strings):
            if not re.search(r"(.*\s)?Tel\..*", string):
                address_fraction_match = re.search(r"([^-]+)-([^(]+)\(([^)]+)\)", string)
                address_match = re.search(r"([^(]+)\(([^)]+)\)", string)
                if address_fraction_match is not None:
                    fraction = address_fraction_match.group(1)
                    city = address_fraction_match.group(2)
                    province = address_fraction_match.group(3)
                else:
                    if address_match is not None:
                        city = address_match.group(1)
                        province = address_match.group(2)
                    else:
                        address = string
        result_list[i]['address'] = address.strip()
        result_list[i]['fraction'] = fraction.strip()
        result_list[i]['city'] = city.strip()
        result_list[i]['province'] = province.strip()

        id = get_drugstore_id(result_list[i])

        global lat_lng_cache
        if id in lat_lng_cache:
            latitude, longitude = lat_lng_cache[id]
        else:
            latitude, longitude = get_lat_lng_from_address(address + ' ' + fraction + ' ' + city + ' ' + province)
            lat_lng_cache[id] = (latitude, longitude)
        result_list[i]['latitude'] = latitude
        result_list[i]['longitude'] = longitude

    # get times
    dom_times = soup.select(".bb.c.ch")
    for i, dom_times in enumerate(dom_times):
        result_list[i]['openings'] = []
        for j, string in enumerate(dom_times.stripped_strings):
            time_match = re.search(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", string)
            if time_match is not None:
                open = int(timestr_to_datetime(time_match.group(1), date).timestamp())
                close = int(timestr_to_datetime(time_match.group(2), date).timestamp())
                result_list[i]['openings'].append((open, close))

    result = {}
    for result_item in result_list:
        result[get_drugstore_id(result_item)] = result_item

    return result


def merge_results(a, b):
    for id in a:
        if id in b:
            for key in a[id]:
                if key == 'openings':
                    a[id][key] = a[id][key] + b[id][key]
                else:
                    if key in b[id]:
                        if a[id][key] != b[id][key]:
                            print('Inconsistent values in id ' + id + ' on key ' + str(key) + ': "' + str(
                                a[id][key]) + '" != "' + str(b[id][key]) + '" (keeping the first one)')
                    else:
                        print('Inconsistent values in id ' + id + ' on key ' + str(key) + ': b has no value')
            for key in b[id]:
                if key not in a[id]:
                    a[id][key] = b[id][key]
                    print('Inconsistent values in id ' + id + ' on key ' + str(key) + ': a has no value')

    for id in b:
        if id not in a:
            a[id] = b[id]

    return a


def get_data_for_comune(cod):
    global TODAY_DATE, TOMORROW_DATE

    today_url = "https://www.farmaciediturno.org/comune.asp?cod=" + str(cod) + "&domani=0"
    tomorrow_url = "https://www.farmaciediturno.org/comune.asp?cod=" + str(cod) + "&domani=1"

    print('Getting today results for %s..' % cod)
    today_result = get_names_and_timestamps(today_url, TODAY_DATE)
    print('Getting tomorrow results for %s..' % cod)
    tomorrow_result = get_names_and_timestamps(tomorrow_url, TOMORROW_DATE)
    print('Merging today+tomorrow results for %s..' % cod)
    total_result = merge_results(today_result, tomorrow_result)

    return total_result


def get_regioni_province_comuni(url):
    elements = []

    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    dom_links = soup.select(".sf0:not(.c) > .mnu")
    for dom_link in dom_links:
        if dom_link.has_attr('href'):
            elements.append({
                'link': 'https://www.farmaciediturno.org' + dom_link.attrs['href'],
                'name': dom_link.string
            })

    return elements


def get_all_comuni(url='https://www.farmaciediturno.org/italia.asp'):
    result = []
    elements = get_regioni_province_comuni(url)
    for element in elements:
        if re.search(r"/comune\.asp($|\?)", element['link']) is not None:
            code = re.search(r"cod=(\d+)(&|$)", element['link'])
            if code is not None:
                result.append(code.group(1))
        else:
            result.extend(get_all_comuni(element['link']))
    return result


def main():
    global lat_lng_cache
    try:
        with open('cache.json') as cache_file:
            lat_lng_cache = json.load(cache_file)
    except Exception:
        lat_lng_cache = {}

    result = {}

    cities = get_all_comuni('https://www.farmaciediturno.org/regione.asp?cod=42')
    for city in cities:
        merge_results(result, get_data_for_comune(city))

    result_json = json.dumps(result, indent=2)
    with open('results.json', 'w') as f:
        f.write('%s' % result_json)

    with open('cache.json', 'w') as cache_file:
        json.dump(lat_lng_cache, cache_file)


main()
