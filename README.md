# Dinner Decider

Two people, one restaurant. Each person shares where they are and what they're in the mood for. The app finds well-rated places halfway between you, you both vote privately, and it shows the place you both want, or the best compromise.

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. With no API key the app runs in **demo mode** with sample restaurants, which is handy for trying the flow. Use two different browsers (or one normal and one private window) to play both people.

## Real restaurants

Set a Google Maps Platform key with the **Places API** and **Geocoding API** enabled:

```bash
export GOOGLE_MAPS_API_KEY=your-key
export SECRET_KEY=some-long-random-string
python app.py
```

Never commit the key. Restrict it in Google Cloud Console to the APIs above, and to your server's IP if you deploy.

The `googlemaps` library uses the legacy Places API (Nearby Search). Newer Cloud projects may only offer "Places API (New)", so create the key in a project where the legacy **Places API** can be enabled, such as the one the original key came from. If the API is off or the key is wrong, the app says "Restaurant search isn't working" instead of "Nothing matched".

"Use my location" only works on `https://` or `localhost`. Elsewhere, people can type a ZIP code or address.

## Deploying

Sessions live in memory and expire after 24 hours, so run a single worker process:

```bash
gunicorn -w 1 --threads 8 app:app
```

## How a pick is made

1. Searches cuisines you both chose. If you chose none in common, it searches both people's picks. If nothing turns up, it widens the radius once.
2. Uses the lower of your two budgets. It only shows open places if either of you asked for that.
3. Shows up to 12 places, best rated first. Rating is weighted by review count.
4. Each person votes Nah, Sure, or Love it. The winner is the place you both said yes to with the highest combined score. If there isn't one, it's the best compromise.
