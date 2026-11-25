import json, getpass, requests, urllib3
urllib3.disable_warnings()

PWD = getpass.getpass("Mot de passe Bbox: ")

bases = [
    "http://192.168.1.254",
    "https://192.168.1.254",
    "https://mabbox.bytel.fr",
    "http://mabbox.bytel.fr",
]

for base in bases:
    print("\n=====", base)
    try:
        s = requests.Session()
        r = s.post(f"{base}/api/v1/login", data={"password": PWD},
                   timeout=5, verify=False)
        print("login:", r.status_code, r.text[:200].replace("\n", " "))
        print("cookies:", list(s.cookies.keys()))
        if r.status_code == 200:
            h = s.get(f"{base}/api/v1/hosts", timeout=5, verify=False)
            print("hosts:", h.status_code)
            print(json.dumps(h.json(), indent=2, ensure_ascii=False)[:1500])
            break
    except Exception as e:
        print("erreur:", e)
