import requests

url = "https://api.themoviedb.org/3/watch/providers/movie?language=en-US&watch_region=US"

headers = {
    "accept": "application/json",
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5ZDgwNmMxOTk5MTJhZjIwMWM3M2NhOGIwZDNlMjE0NSIsIm5iZiI6MTc0MzQ2MjE1OS41MjYsInN1YiI6IjY3ZWIxZjBmZDk5ODFmZGExODdhOWNhMiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ._wPVOd7WcDwphfcdi-jzsjqkd_xO35lRpTufilTMKcY"
}

response = requests.get(url, headers=headers)

results = response.json().get("results", [])
providers = []
for r in results:
    provider = {}
    provider['provider_id'] = r.get("provider_id", [])
    provider['provider_name'] = r.get("provider_name", [])
    logo_path = "https://media.themoviedb.org/t/p/original/" + r.get("logo_path", [])
    provider['logo_path'] = logo_path
    providers.append(provider)



# for r in results:
#     provider = {}
#     provider['provider_id'] = r.get("provider_id", [])
#     provider['provider_name'] = r.get("provider_name", [])
#     logo_path = "https://media.themoviedb.org/t/p/original/" + r.get("logo_path", [])
#     provider['logo_path'] = logo_path
#     providers[provider['provider_name']] = provider
    
print (providers)

len(providers)