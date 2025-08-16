
import time, hmac, hashlib, requests
from urllib.parse import urlencode

HOST = "https://partner.shopeemobile.com"

def _sign(partner_id:int, path:str, timestamp:int, partner_key:str, access_token:str=None, shop_id:int=None):
    base = f"{partner_id}{path}{timestamp}"
    if access_token is not None:
        base += access_token
    if shop_id is not None:
        base += str(shop_id)
    sign = hmac.new(bytes(partner_key, 'utf-8'), bytes(base, 'utf-8'), hashlib.sha256).hexdigest()
    return sign

def auth_partner_link(partner_id:int, partner_key:str, redirect_url:str):
    path = "/api/v2/shop/auth_partner"
    ts = int(time.time())
    sign = _sign(partner_id, path, ts, partner_key)
    q = {"partner_id": partner_id, "timestamp": ts, "sign": sign, "redirect": redirect_url}
    return f"{HOST}{path}?{urlencode(q)}"

def get_access_token(partner_id:int, partner_key:str, code:str, shop_id:int):
    path = "/api/v2/auth/get_access_token"
    ts = int(time.time())
    sign = _sign(partner_id, path, ts, partner_key)
    url = f"{HOST}{path}?{urlencode({'partner_id':partner_id,'timestamp':ts,'sign':sign})}"
    payload = {"code": code, "shop_id": int(shop_id), "partner_id": int(partner_id)}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def refresh_access_token(partner_id:int, partner_key:str, refresh_token:str, shop_id:int):
    path = "/api/v2/auth/refresh_access_token"
    ts = int(time.time())
    sign = _sign(partner_id, path, ts, partner_key)
    url = f"{HOST}{path}?{urlencode({'partner_id':partner_id,'timestamp':ts,'sign':sign})}"
    payload = {"refresh_token": refresh_token, "shop_id": int(shop_id), "partner_id": int(partner_id)}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def get_order_list(partner_id:int, partner_key:str, access_token:str, shop_id:int,
                   time_from:int, time_to:int, page_size:int=50, cursor:str=None):
    path = "/api/v2/order/get_order_list"
    ts = int(time.time())
    sign = _sign(partner_id, path, ts, partner_key, access_token, shop_id)
    params = {"partner_id": partner_id, "timestamp": ts, "sign": sign,
              "access_token": access_token, "shop_id": shop_id,
              "time_range_field":"create_time","time_from": time_from,"time_to": time_to,"page_size":page_size}
    if cursor: params["cursor"] = cursor
    url = f"{HOST}{path}?{urlencode(params)}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def get_order_detail(partner_id:int, partner_key:str, access_token:str, shop_id:int, order_sn_list:list):
    path = "/api/v2/order/get_order_detail"
    ts = int(time.time())
    sign = _sign(partner_id, path, ts, partner_key, access_token, shop_id)
    params = {"partner_id": partner_id, "timestamp": ts, "sign": sign,
              "access_token": access_token, "shop_id": shop_id}
    url = f"{HOST}{path}?{urlencode(params)}"
    payload = {"order_sn_list": order_sn_list}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()
