import plistlib as plist
import json
import uuid
import hashlib
import hmac
import base64
import locale
from datetime import datetime
import pbkdf2
import requests
import srp._pysrp as srp
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from Crypto.Hash import SHA256

# Created here so that it is consistent
USER_ID = uuid.uuid4()
DEVICE_ID = uuid.uuid4()

# Configure SRP library for compatibility with Apple's implementation
srp.rfc5054_enable()
srp.no_username_in_x()

# Disable SSL Warning
import urllib3
urllib3.disable_warnings()

ANISETTE_URL = 'http://127.0.0.1:6969'  # https://github.com/Dadoum/anisette-v3-server

def icloud_login_mobileme(username, password, second_factor='sms'):
    g = gsa_authenticate(username, password, second_factor)
    pet = g["t"]["com.apple.gs.idms.pet"]["token"]
    adsid = g["adsid"]

    data = {
        "apple-id": username,
        "delegates": {"com.apple.mobileme":{}},
        "password": pet,
        "client-id": str(USER_ID),
    }
    data = plist.dumps(data)

    headers = {
        "X-Apple-ADSID": adsid,
        "User-Agent": "com.apple.iCloudHelper/282 CFNetwork/1408.0.4 Darwin/22.5.0",
        "X-Mme-Client-Info": '<MacBookPro18,3> <Mac OS X;13.4.1;22F8> <com.apple.AOSKit/282 (com.apple.accountsd/113)>'
    }
    headers.update(generate_anisette_headers())

    r = requests.post(
        "https://setup.icloud.com/setup/iosbuddy/loginDelegates",
        auth=(username, pet),
        data=data,
        headers=headers,
        verify=False,
    )

    return plist.loads(r.content)

def gsa_authenticate(username, password, second_factor='sms'):
    # Password is None as we'll provide it later
    usr = srp.User(username, bytes(), hash_alg=srp.SHA256, ng_type=srp.NG_2048)
    _, A = usr.start_authentication()

    r = gsa_authenticated_request({"A2k": A, "ps": ["s2k", "s2k_fo"], "u": username, "o": "init"})

    if r["sp"] not in ["s2k", "s2k_fo"]:
        raise Exception(f"This implementation only supports s2k and sk2_fo. Server returned {r['sp']}")

    # Change the password out from under the SRP library, as we couldn't calculate it without the salt.
    usr.p = encrypt_password(password, r["s"], r["i"], r["sp"])

    M = usr.process_challenge(r["s"], r["B"])

    # Make sure we processed the challenge correctly
    if M is None:
        raise Exception("Failed to process challenge")

    r = gsa_authenticated_request({"c": r["c"], "M1": M, "u": username, "o": "complete"})

    # Make sure that the server's session key matches our session key (and thus that they are not an imposter)
    usr.verify_session(r["M2"])
    if not usr.authenticated():
        raise Exception("Failed to verify session")

    spd = decrypt_cbc(usr, r["spd"])
    # For some reason plistlib doesn't accept it without the header...
    PLISTHEADER = b"""\
<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE plist PUBLIC '-//Apple//DTD PLIST 1.0//EN' 'http://www.apple.com/DTDs/PropertyList-1.0.dtd'>
"""
    spd = plist.loads(PLISTHEADER + spd)

    if "au" in r["Status"] and r["Status"]["au"] in ["trustedDeviceSecondaryAuth","secondaryAuth"]:
        print("2FA required, requesting code")
        # Replace bytes with strings
        for k, v in spd.items():
            if isinstance(v, bytes):
                spd[k] = base64.b64encode(v).decode()
        headers = generate_second_factor_code_headers(spd["adsid"], spd["GsIdmsToken"])

        request_second_factor_code(headers,second_factor=='sms')
        send_second_factor_code(headers,second_factor=='sms', input(f"{second_factor} code:"))

        return gsa_authenticate(username, password)
    elif "au" in r["Status"]:
        print(f"Unknown auth value {r['Status']['au']}")
        return
    else:
        return spd

def gsa_authenticated_request(parameters):
    body = {
        "Header": {"Version": "1.0.1"},
        "Request": {"cpd": generate_cpd()},
    }
    body["Request"].update(parameters)

    headers = {
        "Content-Type": "text/x-xml-plist",
        "Accept": "*/*",
        "User-Agent": "akd/1.0 CFNetwork/978.0.7 Darwin/18.7.0",
        "X-MMe-Client-Info": '<MacBookPro18,3> <Mac OS X;13.4.1;22F8> <com.apple.AOSKit/282 (com.apple.dt.Xcode/3594.4.19)>'
    }

    resp = requests.post(
        "https://gsa.apple.com/grandslam/GsService2",
        headers=headers,
        data=plist.dumps(body),
        verify=False,
        timeout=5,
    )

    return plist.loads(resp.content)["Response"]

def request_second_factor_code(headers: dict[str,str], auth_type_sms: bool):
    if auth_type_sms:
        # TODO: Actually get the correct id, probably in the above GET
        body = {"phoneNumber":{"id":1},"mode":"sms"}

        # This will trigger the 2FA prompt on trusted devices
        # We don't care about the response, it's just some HTML with a form for entering the code
        requests.put(
            "https://gsa.apple.com/auth/verify/phone/",
            json=body,
            headers=headers,
            verify=False,
            timeout=5
        )
    else:
        # This will trigger the 2FA prompt on trusted devices
        # We don't care about the response, it's just some HTML with a form for entering the code
        requests.get(
            "https://gsa.apple.com/auth/verify/trusteddevice",
            headers=headers,
            verify=False,
            timeout=10,
        )

def send_second_factor_code(headers: dict[str,str], auth_type_sms: bool, code: str):
    resp = None
    if auth_type_sms:
        body = {"phoneNumber":{"id":1},"mode":"sms"}
        body['securityCode'] = {'code': code}

        # Send the 2FA code to Apple
        resp = requests.post(
            "https://gsa.apple.com/auth/verify/phone/securitycode",
            json=body,
            headers=headers,
            verify=False,
            timeout=5,
        )
    else:
        headers = headers.copy()
        headers["Content-Type"] = "text/x-xml-plist"
        headers["Accept"] = "text/x-xml-plist"
        headers["security-code"] = code
        # Send the 2FA code to Apple
        resp = requests.get(
            "https://gsa.apple.com/grandslam/GsService2/validate",
            headers=headers,
            verify=False,
            timeout=10,
        )

    if not resp.ok:
        raise Exception(f"2FA code not accepted: {resp.text}")

# headers
def generate_cpd():
    cpd = {
        # Many of these values are not strictly necessary, but may be tracked by Apple
        "bootstrap": True,  # All implementations set this to true
        "icscrec": True,  # Only AltServer sets this to true
        "pbe": False,  # All implementations explicitly set this to false
        "prkgen": True,  # I've also seen ckgen
        "svct": "iCloud",  # In certian circumstances, this can be 'iTunes' or 'iCloud'
    }

    cpd.update(generate_anisette_headers())
    return cpd

def generate_second_factor_code_headers(dsid: str, idms_token: str):
    identity_token = base64.b64encode((dsid + ":" + idms_token).encode()).decode()

    headers = {
        "User-Agent": "Xcode",
        "Accept-Language": "en-us",
        "X-Apple-Identity-Token": identity_token,
        "X-Apple-App-Info": "com.apple.gs.xcode.auth",
        "X-Xcode-Version": "11.2 (11B41)",
        "X-Mme-Client-Info": '<MacBookPro18,3> <Mac OS X;13.4.1;22F8> <com.apple.AOSKit/282 (com.apple.dt.Xcode/3594.4.19)>'
    }

    headers.update(generate_anisette_headers())

    return headers

def generate_anisette_headers():
    print(f'querying {ANISETTE_URL} for an anisette server')
    h = json.loads(requests.get(ANISETTE_URL, timeout=5).text)
    a = {"X-Apple-I-MD": h["X-Apple-I-MD"], "X-Apple-I-MD-M": h["X-Apple-I-MD-M"]}
    a.update(generate_meta_headers())
    return a

def generate_meta_headers():
    return {
        "X-Apple-I-Client-Time": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "X-Apple-I-TimeZone": str(datetime.utcnow().astimezone().tzinfo),
        "loc": locale.getdefaultlocale()[0] or "en_US",
        "X-Apple-Locale": "en_US",
        "X-Apple-I-MD-RINFO": "17106176",  # either 17106176 or 50660608
        "X-Apple-I-MD-LU": base64.b64encode(str(USER_ID).upper().encode()).decode(),
        "X-Mme-Device-Id": str(DEVICE_ID).upper(),
        "X-Apple-I-SRL-NO": "0",  # Serial number
    }

# utils

def encrypt_password(password, salt, iterations, protocol):
    assert protocol in ["s2k", "s2k_fo"]
    p = hashlib.sha256(password.encode("utf-8")).digest()
    if protocol == "s2k_fo":
        p = p.hex().encode("utf-8")
    return pbkdf2.PBKDF2(p, salt, iterations, SHA256).read(32)

def create_session_key(usr, name):
    k = usr.get_session_key()
    if k is None:
        raise Exception("No session key")
    return hmac.new(k, name.encode(), hashlib.sha256).digest()

def decrypt_cbc(usr, data):
    extra_data_key = create_session_key(usr, "extra data key:")
    extra_data_iv = create_session_key(usr, "extra data iv:")
    # Get only the first 16 bytes of the iv
    extra_data_iv = extra_data_iv[:16]

    # Decrypt with AES CBC
    cipher = Cipher(algorithms.AES(extra_data_key), modes.CBC(extra_data_iv))
    decryptor = cipher.decryptor()
    data = decryptor.update(data) + decryptor.finalize()
    # Remove PKCS#7 padding
    padder = padding.PKCS7(128).unpadder()
    return padder.update(data) + padder.finalize()
