from geopy.geocoders import Nominatim
geolocator = Nominatim(user_agent="shipkore")
location = geolocator.geocode("Delhi_NangliSkrwati_I (Delhi)")
