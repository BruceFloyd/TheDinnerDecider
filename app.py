
from flask import Flask, render_template, request, redirect, url_for, session
import random
import googlemaps

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Needed for session management

# Google Maps API Key
API_KEY = 'AIzaSyASCmU4wU_juG9E5lVjBSG3QhHnkarlzk0'
gmaps = googlemaps.Client(key=API_KEY)

sessions = {}

# ... (rest of the routes)

@app.route('/share_location/<session_code>', methods=['POST'])
def share_location(session_code):
    if session_code in sessions:
        user_id = session.get('user_id')
        if user_id:
            location = request.get_json()
            sessions[session_code][f'user{user_id}_location'] = location
            return {'status': 'success'}
    return {'status': 'error'}


# Placeholder for restaurant suggestions (will be generated dynamically later)
RESTAURANTS = [
    {"name": "Italian Delight", "cuisine": "Italian", "dietary": "none", "spice_level": "mild"},
    {"name": "Spicy Thai", "cuisine": "Thai", "dietary": "none", "spice_level": "hot"},
    {"name": "Green Garden", "cuisine": "Vegetarian", "dietary": "vegetarian", "spice_level": "mild"},
    {"name": "Burger Joint", "cuisine": "American", "dietary": "none", "spice_level": "medium"},
    {"name": "Vegan Paradise", "cuisine": "Vegan", "dietary": "vegan", "spice_level": "mild"},
]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_session', methods=['POST'])
def create_session():
    session_code = str(random.randint(1000, 9999))
    while session_code in sessions:
        session_code = str(random.randint(1000, 9999))
    
    sessions[session_code] = {
        'user1_responses': None,
        'user2_responses': None,
        'user1_votes': [],
        'user2_votes': [],
        'users': 0,
        'user1_location': None,
        'user2_location': None
    }
    return redirect(url_for('join_session_with_code', session_code=session_code))

@app.route('/join_session', methods=['POST'])
def join_session():
    session_code = request.form['session_code']
    if session_code in sessions:
        return redirect(url_for('join_session_with_code', session_code=session_code))
    else:
        return redirect(url_for('index'))

@app.route('/session/<session_code>')
def join_session_with_code(session_code):
    if session_code in sessions:
        if 'user_id' not in session:
            sessions[session_code]['users'] += 1
            session['user_id'] = sessions[session_code]['users']
        
        return render_template('session.html', session_code=session_code, user_id=session['user_id'])
    else:
        return redirect(url_for('index'))

CUISINES = ['American', 'Chinese', 'Indian', 'Italian', 'Japanese', 'Mexican', 'Thai', 'Vegetarian', 'Vegan']

@app.route('/questionnaire/<session_code>')
def questionnaire(session_code):
    if session_code in sessions:
        return render_template('questionnaire.html', session_code=session_code, cuisines=CUISINES)
    else:
        return redirect(url_for('index'))

@app.route('/submit_questionnaire/<session_code>', methods=['POST'])
def submit_questionnaire(session_code):
    if session_code in sessions:
        user_id = session.get('user_id')
        if user_id:
            responses = {
                'cuisine': request.form.getlist('cuisine'),
                'dietary': request.form['dietary'],
                'spice_level': request.form['spice_level'],
                'radius': float(request.form['radius'])
            }
            sessions[session_code][f'user{user_id}_responses'] = responses
            
            return redirect(url_for('waiting', session_code=session_code))
    return redirect(url_for('index'))

@app.route('/waiting/<session_code>')
def waiting(session_code):
    if session_code in sessions:
        print(f"Waiting page for session {session_code}: {sessions[session_code]}")
        # Check if both users have submitted and shared their location
        if (sessions[session_code]['user1_responses'] and
                sessions[session_code]['user2_responses'] and
                sessions[session_code]['user1_location'] and
                sessions[session_code]['user2_location']):
            return redirect(url_for('voting', session_code=session_code))
        return render_template('waiting.html', session_code=session_code)
    return redirect(url_for('index'))

@app.route('/voting/<session_code>')
def voting(session_code):
    if session_code in sessions:
        user1_location = sessions[session_code].get('user1_location')
        user2_location = sessions[session_code].get('user2_location')

        if user1_location and user2_location:
            # Calculate midpoint
            midpoint_lat = (user1_location['lat'] + user2_location['lat']) / 2
            midpoint_lng = (user1_location['lng'] + user2_location['lng']) / 2

            # Get preferences
            user1_prefs = sessions[session_code]['user1_responses']
            user2_prefs = sessions[session_code]['user2_responses']

            common_cuisines = list(set(user1_prefs['cuisine']) & set(user2_prefs['cuisine']))

            if not common_cuisines:
                return render_template('no_common_cuisine.html', session_code=session_code)

            # Use the smaller of the two radii and convert miles to meters
            radius_miles = min(user1_prefs['radius'], user2_prefs['radius'])
            radius_meters = int(radius_miles * 1609.34)

            all_restaurants = []
            for cuisine in common_cuisines:
                keyword = f'{cuisine} restaurant'
                print(f"Google Maps API keyword: {keyword}")
                places_result = gmaps.places_nearby(
                    location=(midpoint_lat, midpoint_lng),
                    radius=radius_meters,
                    keyword=keyword,
                    type='restaurant'
                )
                all_restaurants.extend(places_result.get('results', []))

            # Remove duplicates
            restaurants = []
            seen_restaurant_ids = set()
            for restaurant in all_restaurants:
                if restaurant['place_id'] not in seen_restaurant_ids:
                    restaurants.append(restaurant)
                    seen_restaurant_ids.add(restaurant['place_id'])

            # Further filter by dietary restrictions (this is a simplified example)
            # A more robust solution would involve more detailed filtering
            filtered_restaurants = []
            for restaurant in restaurants:
                # Here you could add more sophisticated filtering based on dietary needs
                # For now, we just pass the top results
                filtered_restaurants.append({'name': restaurant['name'], 'vicinity': restaurant.get('vicinity', '')})

            return render_template('voting.html', session_code=session_code, restaurants=filtered_restaurants)
        else:
            # Handle case where locations are not yet available
            return render_template('waiting_for_location.html', session_code=session_code)
    else:
        return redirect(url_for('index'))

@app.route('/submit_vote/<session_code>', methods=['POST'])
def submit_vote(session_code):
    if session_code in sessions:
        user_id = session.get('user_id')
        if user_id:
            selected_restaurants = request.form.getlist('restaurant')
            sessions[session_code][f'user{user_id}_votes'] = selected_restaurants

            return redirect(url_for('waiting_for_vote', session_code=session_code))
    return redirect(url_for('index'))

@app.route('/waiting_for_vote/<session_code>')
def waiting_for_vote(session_code):
    if session_code in sessions:
        # Check if both users have voted, if so, redirect to result
        if sessions[session_code]['user1_votes'] and sessions[session_code]['user2_votes']:
            return redirect(url_for('result', session_code=session_code))
        return render_template('waiting_for_vote.html', session_code=session_code)
    return redirect(url_for('index'))

@app.route('/result/<session_code>')
def result(session_code):
    if session_code in sessions:
        # Logic to determine the best restaurant based on votes and preferences
        user1_votes = sessions[session_code]['user1_votes']
        user2_votes = sessions[session_code]['user2_votes']

        common_votes = list(set(user1_votes) & set(user2_votes))

        if common_votes:
            chosen_restaurant = random.choice(common_votes) # Randomly pick one from the common ones
        else:
            chosen_restaurant = "No common preferences found. Please try again!"

        return render_template('result.html', session_code=session_code, chosen_restaurant=chosen_restaurant)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
