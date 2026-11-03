import math
import os
import random
import secrets
import threading
import time
from itertools import zip_longest
from urllib.parse import quote_plus

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

app = Flask(__name__)
# Set SECRET_KEY in production. Without it, a random key is used and everyone is
# signed out on restart (sessions live in memory anyway, so nothing else is lost).
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# With no key the app runs in demo mode: sample restaurants and no geocoding.
API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY')
gmaps = None
if API_KEY:
    import googlemaps
    gmaps = googlemaps.Client(key=API_KEY)
DEMO_MODE = gmaps is None

CUISINES = ['American', 'BBQ', 'Burgers', 'Chinese', 'Indian', 'Italian', 'Japanese', 'Korean',
            'Mediterranean', 'Mexican', 'Pizza', 'Seafood', 'Steakhouse', 'Sushi', 'Thai',
            'Vietnamese', 'Vegetarian', 'Vegan']
RADIUS_OPTIONS = [1, 2, 3, 5, 10, 20]
MAX_CANDIDATES = 12
MAX_CUISINE_SEARCHES = 5
SESSION_TTL_SECONDS = 24 * 60 * 60
METERS_PER_MILE = 1609.34

sessions = {}
sessions_lock = threading.Lock()

# Demo mode location: downtown Gainesville, FL.
DEMO_POINT = (29.6516, -82.3248)
DEMO_RESTAURANTS = [
    {'name': 'Trattoria Nonna', 'cuisine': 'Italian', 'rating': 4.6, 'reviews': 812, 'price': 2, 'offset': (0.004, 0.003)},
    {'name': 'Slice Theory', 'cuisine': 'Pizza', 'rating': 4.4, 'reviews': 1290, 'price': 1, 'offset': (-0.002, 0.005)},
    {'name': 'Bangkok Garden', 'cuisine': 'Thai', 'rating': 4.5, 'reviews': 640, 'price': 2, 'offset': (0.006, -0.004)},
    {'name': 'Lemongrass Kitchen', 'cuisine': 'Thai', 'rating': 4.2, 'reviews': 305, 'price': 1, 'offset': (-0.007, -0.002)},
    {'name': 'Taqueria El Sol', 'cuisine': 'Mexican', 'rating': 4.7, 'reviews': 2210, 'price': 1, 'offset': (0.001, -0.008)},
    {'name': 'Casa Agave', 'cuisine': 'Mexican', 'rating': 4.3, 'reviews': 980, 'price': 2, 'offset': (0.009, 0.006)},
    {'name': 'Smoke & Oak BBQ', 'cuisine': 'BBQ', 'rating': 4.6, 'reviews': 1530, 'price': 2, 'offset': (-0.012, 0.004)},
    {'name': 'Tokyo Table', 'cuisine': 'Japanese', 'rating': 4.5, 'reviews': 720, 'price': 3, 'offset': (0.003, 0.011)},
    {'name': 'Umi Sushi Bar', 'cuisine': 'Sushi', 'rating': 4.4, 'reviews': 590, 'price': 3, 'offset': (-0.005, 0.009)},
    {'name': 'Spice Route', 'cuisine': 'Indian', 'rating': 4.6, 'reviews': 870, 'price': 2, 'offset': (0.010, -0.010)},
    {'name': 'Golden Dragon', 'cuisine': 'Chinese', 'rating': 4.1, 'reviews': 455, 'price': 1, 'offset': (-0.009, -0.009)},
    {'name': 'Seoul Food', 'cuisine': 'Korean', 'rating': 4.5, 'reviews': 410, 'price': 2, 'offset': (0.007, 0.001)},
    {'name': 'Olive & Fig', 'cuisine': 'Mediterranean', 'rating': 4.7, 'reviews': 660, 'price': 2, 'offset': (-0.003, -0.006)},
    {'name': 'Pho Real', 'cuisine': 'Vietnamese', 'rating': 4.5, 'reviews': 930, 'price': 1, 'offset': (0.012, 0.002)},
    {'name': 'The Burger Stand', 'cuisine': 'Burgers', 'rating': 4.3, 'reviews': 1720, 'price': 1, 'offset': (0.002, 0.002)},
    {'name': 'Harbor Fish House', 'cuisine': 'Seafood', 'rating': 4.4, 'reviews': 1105, 'price': 3, 'offset': (-0.015, 0.012)},
    {'name': 'Prime Cut', 'cuisine': 'Steakhouse', 'rating': 4.6, 'reviews': 890, 'price': 4, 'offset': (0.014, -0.006)},
    {'name': 'Green Fork', 'cuisine': 'Vegetarian', 'rating': 4.5, 'reviews': 380, 'price': 2, 'offset': (-0.004, 0.001)},
    {'name': 'Plant Power Cafe', 'cuisine': 'Vegan', 'rating': 4.6, 'reviews': 340, 'price': 2, 'offset': (0.005, -0.001)},
    {'name': 'Main Street Diner', 'cuisine': 'American', 'rating': 4.2, 'reviews': 1450, 'price': 1, 'offset': (-0.001, 0.007)},
]


# ---------- Places ----------

def maps_url(name, place_id):
    return f'https://www.google.com/maps/search/?api=1&query={quote_plus(name)}&query_place_id={place_id}'


def directions_url(name, place_id):
    return f'https://www.google.com/maps/dir/?api=1&destination={quote_plus(name)}&destination_place_id={place_id}'


def geocode(address):
    """Returns (lat, lng) for a typed address or ZIP, or None."""
    if DEMO_MODE:
        return DEMO_POINT
    try:
        results = gmaps.geocode(address)
    except Exception as e:
        app.logger.warning('Geocoding failed: %s', e)
        return None
    if not results:
        return None
    loc = results[0]['geometry']['location']
    return (loc['lat'], loc['lng'])


def search_places(lat, lng, radius_m, cuisine, max_price, open_now):
    """Returns restaurants near a point as plain dicts. All Google Places calls go through here.

    Raises if the Places API call fails, so callers can tell "nothing nearby" from "broken key".
    """
    if DEMO_MODE:
        return [
            {
                'place_id': f'demo-{i}',
                'name': r['name'],
                'vicinity': f'{100 + i * 37} Demo St',
                'rating': r['rating'],
                'reviews': r['reviews'],
                'price': r['price'],
                'open_now': True,
                'lat': DEMO_POINT[0] + r['offset'][0],
                'lng': DEMO_POINT[1] + r['offset'][1],
                'cuisine': r['cuisine'],
            }
            for i, r in enumerate(DEMO_RESTAURANTS)
            if (cuisine is None or r['cuisine'] == cuisine) and r['price'] <= max_price
        ]

    params = {
        'location': (lat, lng),
        'radius': min(int(radius_m), 50000),
        'type': 'restaurant',
        'keyword': f'{cuisine} restaurant' if cuisine else 'restaurant',
    }
    if open_now:
        params['open_now'] = True
    results = gmaps.places_nearby(**params).get('results', [])
    places = []
    for p in results:
        if p.get('business_status', 'OPERATIONAL') != 'OPERATIONAL':
            continue
        # Budget is filtered here, not by Google, so places with no price level aren't dropped.
        if p.get('price_level') is not None and p['price_level'] > max_price:
            continue
        loc = p.get('geometry', {}).get('location', {})
        places.append({
            'place_id': p['place_id'],
            'name': p['name'],
            'vicinity': p.get('vicinity', ''),
            'rating': p.get('rating'),
            'reviews': p.get('user_ratings_total', 0),
            'price': p.get('price_level'),
            'open_now': p.get('opening_hours', {}).get('open_now'),
            'lat': loc.get('lat'),
            'lng': loc.get('lng'),
            'cuisine': cuisine,
        })
    return places


def miles_between(a_lat, a_lng, b_lat, b_lng):
    r = 3958.8
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def pick_cuisines(prefs1, prefs2):
    """Returns (cuisines to search, whether they actually overlap). None in the list means 'any'."""
    c1, c2 = set(prefs1['cuisines']), set(prefs2['cuisines'])
    if not c1 and not c2:
        return [None], True
    if not c1:
        return sorted(c2)[:MAX_CUISINE_SEARCHES], True
    if not c2:
        return sorted(c1)[:MAX_CUISINE_SEARCHES], True
    common = c1 & c2
    if common:
        return sorted(common)[:MAX_CUISINE_SEARCHES], True
    # No overlap: alternate between both people's picks so neither gets cut off by the cap.
    a, b = sorted(c1), sorted(c2)
    mixed = [c for pair in zip_longest(a, b) for c in pair if c is not None]
    return mixed[:MAX_CUISINE_SEARCHES], False


def build_candidates(data):
    p1, p2 = data['prefs'][1], data['prefs'][2]
    lat = (p1['lat'] + p2['lat']) / 2
    lng = (p1['lng'] + p2['lng']) / 2
    # Midpoint search, wide enough that each person's limit is reachable from the middle.
    half_gap = miles_between(p1['lat'], p1['lng'], p2['lat'], p2['lng']) / 2
    radius_miles = max(min(p1['radius'], p2['radius']), half_gap + 1)
    max_price = min(p1['max_price'], p2['max_price'])
    open_now = p1['open_now'] or p2['open_now']
    cuisines, overlap = pick_cuisines(p1, p2)

    found = {}
    calls = failures = 0
    for radius in (radius_miles, radius_miles * 2):
        for cuisine in cuisines:
            calls += 1
            try:
                places = search_places(lat, lng, radius * METERS_PER_MILE, cuisine, max_price, open_now)
            except Exception as e:
                app.logger.warning('Places search failed for %s: %s', cuisine, e)
                failures += 1
                continue
            for place in places:
                found.setdefault(place['place_id'], place)
        if found or failures == calls:
            break

    places = list(found.values())
    for place in places:
        place['maps_url'] = maps_url(place['name'], place['place_id'])
        place['directions_url'] = directions_url(place['name'], place['place_id'])
        if place['lat'] is not None:
            place['distance'] = {
                seat: round(miles_between(p['lat'], p['lng'], place['lat'], place['lng']), 1)
                for seat, p in data['prefs'].items()
            }
        else:
            place['distance'] = {}
    # Well-reviewed places first; review count stops a 5.0 with 3 reviews from winning.
    places.sort(key=lambda p: (p['rating'] or 0) * math.log10((p['reviews'] or 0) + 10), reverse=True)
    data['cuisine_overlap'] = overlap
    data['search_failed'] = failures == calls
    data['candidates'] = places[:MAX_CANDIDATES]


def rank_results(data):
    v1, v2 = data['votes'][1], data['votes'][2]
    ranked = []
    for place in data['candidates']:
        a, b = v1.get(place['place_id'], 0), v2.get(place['place_id'], 0)
        ranked.append({**place, 'votes': (a, b), 'mutual': a > 0 and b > 0, 'score': a + b})
    ranked.sort(key=lambda p: (p['mutual'], p['score'], min(p['votes']), p['rating'] or 0), reverse=True)
    return ranked


# ---------- Session state ----------

def new_session_data():
    return {
        'id': secrets.token_hex(8),
        'created': time.time(),
        'seats': 0,
        'prefs': {1: None, 2: None},
        'votes': {1: None, 2: None},
        'candidates': None,
        'building': False,
        'search_failed': False,
        'cuisine_overlap': True,
    }


def purge_old_sessions():
    cutoff = time.time() - SESSION_TTL_SECONDS
    for code in [c for c, d in sessions.items() if d['created'] < cutoff]:
        del sessions[code]


def seat_for(code):
    """Returns this browser's seat (1 or 2) in a session, or None."""
    entry = session.get('seats', {}).get(code)
    data = sessions.get(code)
    # The id check matters because codes are reused once old sessions expire.
    if entry and data and entry[0] == data['id']:
        return entry[1]
    return None


def claim_seat(code):
    """Gives this browser the next free seat. Call with sessions_lock held.

    Only POST routes claim seats, so link-preview bots that GET a shared link can't take one.
    """
    seat = seat_for(code)
    if seat:
        return seat
    data = sessions[code]
    if data['seats'] >= 2:
        return None
    data['seats'] += 1
    # Drop entries for sessions that are gone so the cookie doesn't grow forever.
    seats = {c: e for c, e in session.get('seats', {}).items()
             if c in sessions and sessions[c]['id'] == e[0]}
    seats[code] = [data['id'], data['seats']]
    session['seats'] = seats
    return data['seats']


def stage_for(data, seat):
    if data['prefs'][seat] is None:
        return 'prefs'
    if data['candidates'] is None:
        return 'wait_prefs'
    if not data['candidates']:
        return 'no_results'
    if data['votes'][seat] is None:
        return 'vote'
    if data['votes'][1] is None or data['votes'][2] is None:
        return 'wait_votes'
    return 'result'


# ---------- Routes ----------

@app.context_processor
def inject_globals():
    return {'demo_mode': DEMO_MODE}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/create_session', methods=['POST'])
def create_session():
    with sessions_lock:
        purge_old_sessions()
        code = str(random.randint(1000, 9999))
        while code in sessions:
            code = str(random.randint(1000, 9999))
        sessions[code] = new_session_data()
        claim_seat(code)
    return redirect(url_for('session_page', session_code=code))


@app.route('/join_session', methods=['POST'])
def join_session():
    code = request.form.get('session_code', '').strip()
    if code not in sessions:
        flash(f'No session found with code "{code}". Check the code and try again.')
        return redirect(url_for('index'))
    return claim_seat_route(code)


@app.route('/session/<session_code>/join', methods=['POST'])
def claim_seat_route(session_code):
    if session_code not in sessions:
        flash('That session has expired or never existed. Start a new one.')
        return redirect(url_for('index'))
    with sessions_lock:
        seat = claim_seat(session_code)
    if seat is None:
        return render_template('full.html', session_code=session_code), 403
    return redirect(url_for('session_page', session_code=session_code))


@app.route('/session/<session_code>')
def session_page(session_code):
    """One URL per session; shows whichever step this person is on."""
    data = sessions.get(session_code)
    if not data:
        flash('That session has expired or never existed. Start a new one.')
        return redirect(url_for('index'))
    seat = seat_for(session_code)
    if seat is None:
        if data['seats'] >= 2:
            return render_template('full.html', session_code=session_code), 403
        return render_template('join.html', session_code=session_code)

    stage = stage_for(data, seat)
    share_url = url_for('session_page', session_code=session_code, _external=True)
    partner = 2 if seat == 1 else 1
    if stage == 'prefs':
        return render_template('session.html', session_code=session_code, share_url=share_url,
                               partner_joined=data['seats'] >= 2, cuisines=CUISINES,
                               radius_options=RADIUS_OPTIONS)
    if stage in ('wait_prefs', 'wait_votes'):
        return render_template('waiting.html', session_code=session_code, share_url=share_url,
                               stage=stage, partner_joined=data['seats'] >= 2)
    if stage == 'no_results':
        return render_template('no_results.html', session_code=session_code,
                               search_failed=data['search_failed'])
    if stage == 'vote':
        return render_template('voting.html', session_code=session_code, seat=seat,
                               restaurants=data['candidates'],
                               cuisine_overlap=data['cuisine_overlap'])
    ranked = rank_results(data)
    return render_template('result.html', session_code=session_code, seat=seat, partner=partner,
                           ranked=ranked, top=ranked[0])


@app.route('/session/<session_code>/status')
def session_status(session_code):
    data = sessions.get(session_code)
    seat = seat_for(session_code)
    if not data or seat is None:
        return jsonify({'stage': 'gone'}), 404
    return jsonify({'stage': stage_for(data, seat), 'partner_joined': data['seats'] >= 2})


@app.route('/session/<session_code>/prefs', methods=['POST'])
def submit_prefs(session_code):
    data = sessions.get(session_code)
    seat = seat_for(session_code)
    if not data or seat is None:
        return redirect(url_for('index'))

    lat, lng = request.form.get('lat'), request.form.get('lng')
    address = request.form.get('address', '').strip()
    if lat and lng:
        try:
            point = (float(lat), float(lng))
        except ValueError:
            point = None
    elif address:
        point = geocode(address)
    else:
        point = None
    if point is None:
        flash("We couldn't find that location. Use your current location or try a ZIP code.")
        return redirect(url_for('session_page', session_code=session_code))

    cuisines = [c for c in request.form.getlist('cuisine') if c in CUISINES]
    try:
        radius = float(request.form.get('radius', 5))
        max_price = int(request.form.get('max_price', 4))
    except ValueError:
        radius, max_price = 5.0, 4
    prefs = {
        'lat': point[0],
        'lng': point[1],
        'cuisines': cuisines,
        'radius': min(max(radius, 0.5), 30),
        'max_price': min(max(max_price, 1), 4),
        'open_now': request.form.get('open_now') == 'on',
    }

    with sessions_lock:
        data['prefs'][seat] = prefs
        both_in = data['prefs'][1] and data['prefs'][2]
        needs_build = both_in and data['candidates'] is None and not data['building']
        if needs_build:
            data['building'] = True  # So the partner's submit doesn't search again.
    if needs_build:
        try:
            build_candidates(data)
        finally:
            if data['candidates'] is None:
                data['candidates'] = []
            data['building'] = False
    return redirect(url_for('session_page', session_code=session_code))


@app.route('/session/<session_code>/vote', methods=['POST'])
def submit_vote(session_code):
    data = sessions.get(session_code)
    seat = seat_for(session_code)
    if not data or seat is None or not data['candidates']:
        return redirect(url_for('index'))
    votes = {}
    for place in data['candidates']:
        value = request.form.get(f"vote_{place['place_id']}", '0')
        votes[place['place_id']] = int(value) if value in ('0', '1', '2') else 0
    with sessions_lock:
        data['votes'][seat] = votes
    return redirect(url_for('session_page', session_code=session_code))


if __name__ == '__main__':
    if DEMO_MODE:
        print('GOOGLE_MAPS_API_KEY is not set: running in demo mode with sample restaurants.')
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
