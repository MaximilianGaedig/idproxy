#!/usr/bin/env python3
import os, argparse, json
from typing import Annotated, Any
import requests
from fastapi import Body, FastAPI
from pypush_gsa_icloud import icloud_login_mobileme, generate_anisette_headers

auth_info = "/data/auth.json"
j: dict[str,str] = {}

def authenticate(second_factor='sms'):
    username = input("username:")
    password = input("password:")

    mobileme = icloud_login_mobileme(username,password,second_factor=second_factor)
    j = {'dsid': mobileme['dsid'], 'searchPartyToken': mobileme['delegates']['com.apple.mobileme']['service-data']['tokens']['searchPartyToken']}
    with open(auth_info, "w") as f: json.dump(j, f)
    return j

if __name__ == "__main__":
    socket = '/socket/idproxy.sock'

    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--auth', help='authenticate instead of starting a server', action='store_true')
    parser.add_argument('-t', '--trusteddevice', help='use trusted device for 2FA instead of SMS', action='store_true')
    args = parser.parse_args()

    if args.auth:
        auth = authenticate(second_factor='trusted_device' if args.trusteddevice else 'sms')
        print(auth)
        exit(0)
    
    app = FastAPI()

    @app.put("/")
    async def root(url: Annotated[str,Body()],data: Annotated[dict[Any,Any],Body()]):
        print(f"requesting {url} with data {data}")
        
        if not os.path.exists(auth_info):
            raise Exception("not authenticated")
        with open(auth_info, "r") as f:
            j = json.load(f)
        
        r = requests.post(url,
                auth=(j['dsid'],j['searchPartyToken']),
                headers=generate_anisette_headers(),
                json=data)
        decoded = r.content.decode()

        print(f"response for {url} with data {data}: {decoded}")

        return decoded
    
    import uvicorn
    uvicorn.run(app, uds=socket)
