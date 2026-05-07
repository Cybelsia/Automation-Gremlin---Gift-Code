import argparse
import asyncio
import base64
import hashlib
import json
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp

FID = "524303601"
GIFT_CODE = "ChildrensDay505"
SECRET = "tB87#kPtkxqOS2"
SITE_URL = "https://wos-giftcode.centurygame.com/"
API_BASE_URL = "https://wos-giftcode-api.centurygame.com/api"
PLAYER_URL = f"{API_BASE_URL}/player"
CAPTCHA_URL = f"{API_BASE_URL}/captcha"
GIFT_CODE_URL = f"{API_BASE_URL}/gift_code"
CAPTCHA_OUTPUT_DIR = Path("captcha_debug")


def md5_sign(sign_input):
    return hashlib.md5((sign_input + SECRET).encode("utf-8")).hexdigest()


def build_player_payload(fid):
    time_val = str(int(time.time()))
    sign_input = f"fid={fid}&time={time_val}"
    return sign_input, {"fid": fid, "time": time_val, "sign": md5_sign(sign_input)}


def build_gift_payload(fid, gift_code, captcha_fields, gift_sign_mode):
    time_val = str(int(time.time()))
    if gift_sign_mode == "include_captcha_last":
        sign_input = f"cdk={gift_code}&fid={fid}&time={time_val}&captcha_code={captcha_fields.get('captcha_code', '')}"
    elif gift_sign_mode == "captcha_first":
        sign_input = f"captcha_code={captcha_fields.get('captcha_code', '')}&cdk={gift_code}&fid={fid}&time={time_val}"
    else:
        sign_input = f"cdk={gift_code}&fid={fid}&time={time_val}"
    payload = {"cdk": gift_code, "fid": fid, "time": time_val, "sign": md5_sign(sign_input)}
    payload.update(captcha_fields)
    return sign_input, payload


def browser_headers(content_type="application/x-www-form-urlencoded"):
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": content_type,
        "origin": "https://wos-giftcode.centurygame.com",
        "referer": "https://wos-giftcode.centurygame.com/",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }


def sanitized_payload_shape(payload):
    return {
        "keys": list(payload.keys()),
        "types": {key: type(value).__name__ for key, value in payload.items()},
        "encoded_body": urlencode(payload),
    }


def sanitized_final_gift_payload_shape(payload):
    redacted_fields = {"captcha_code", "sign"}
    return {
        "keys": list(payload.keys()),
        "types": {key: type(value).__name__ for key, value in payload.items()},
        "string_lengths": {key: len(value) for key, value in payload.items() if isinstance(value, str)},
        "redacted_fields": sorted(key for key in payload if key in redacted_fields),
    }


def build_gift_sign_candidate_summary(fid, gift_code, captcha_code):
    time_val = str(int(time.time()))
    candidates = [
        ("legacy", f"cdk={gift_code}&fid={fid}&time={time_val}"),
        ("include_captcha_last", f"cdk={gift_code}&fid={fid}&time={time_val}&captcha_code={captcha_code}"),
        ("captcha_first", f"captcha_code={captcha_code}&cdk={gift_code}&fid={fid}&time={time_val}"),
        ("alphabetical_excluding_sign", f"captcha_code={captcha_code}&cdk={gift_code}&fid={fid}&time={time_val}"),
    ]
    seen = {}
    summary = []
    for name, sign_input in candidates:
        duplicate_of = seen.get(sign_input)
        if duplicate_of is None:
            seen[sign_input] = name
        summary.append({
            "name": name,
            "sign_input": sign_input.replace(f"captcha_code={captcha_code}", "captcha_code=<redacted>"),
            "md5": md5_sign(sign_input),
            "duplicate_of": duplicate_of,
        })
    return {"time": time_val, "candidates": summary}


def sanitized_response_shape(status, text):
    shape = {"http_status": status, "raw_prefix": text[:240]}
    try:
        data = json.loads(text)
        shape["json_keys"] = list(data.keys()) if isinstance(data, dict) else None
        shape["msg"] = data.get("msg") if isinstance(data, dict) else None
        shape["err_code"] = data.get("err_code") if isinstance(data, dict) else None
        shape["code"] = data.get("code") if isinstance(data, dict) else None
        shape["data_type"] = type(data.get("data")).__name__ if isinstance(data, dict) else None
    except json.JSONDecodeError:
        shape["json_keys"] = None
    return shape


def print_json(label, value):
    print(label)
    print(json.dumps(value, indent=2, sort_keys=False))


def extract_captcha_candidates(data):
    candidates = {}
    if not isinstance(data, dict):
        return candidates

    search_items = []
    search_items.append(([], data))
    if isinstance(data.get("data"), dict):
        search_items.append((["data"], data["data"]))

    image_keys = {"img", "image", "captcha", "captcha_img", "captcha_image", "base64", "src"}
    token_keys = {"captcha_id", "captchaId", "id", "token", "key", "uuid", "captcha_key"}

    for prefix, obj in search_items:
        for key, value in obj.items():
            path = ".".join(prefix + [key])
            if key in image_keys and isinstance(value, str):
                candidates.setdefault("image_fields", {})[path] = value[:80]
            if key in token_keys and isinstance(value, (str, int)):
                candidates.setdefault("token_fields", {})[path] = value
    return candidates


def summarize_captcha_data(data):
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        return {"data_keys": [], "data_value_types": {}, "string_lengths": {}}
    captcha_data = data["data"]
    return {
        "data_keys": list(captcha_data.keys()),
        "data_value_types": {key: type(value).__name__ for key, value in captcha_data.items()},
        "string_lengths": {key: len(value) for key, value in captcha_data.items() if isinstance(value, str)},
    }


def save_possible_captcha_image(data):
    if not isinstance(data, dict):
        return None

    values = []
    if isinstance(data.get("data"), dict):
        values.extend(data["data"].values())
    values.extend(data.values())

    for value in values:
        if not isinstance(value, str):
            continue
        image_data = value
        if "," in image_data and "base64" in image_data[:50]:
            image_data = image_data.split(",", 1)[1]
        try:
            decoded = base64.b64decode(image_data, validate=True)
        except Exception:
            continue
        if len(decoded) < 100:
            continue
        CAPTCHA_OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = CAPTCHA_OUTPUT_DIR / f"captcha_{int(time.time())}.png"
        output_path.write_bytes(decoded)
        return str(output_path)
    return None


async def post_form(session, url, payload):
    async with session.post(url, headers=browser_headers(), data=payload) as response:
        text = await response.text()
        return response.status, text


async def fetch_captcha(session, method):
    headers = browser_headers()
    if method == "get":
        async with session.get(CAPTCHA_URL, headers=headers) as response:
            text = await response.text()
            return response.status, text
    if method == "post_empty":
        async with session.post(CAPTCHA_URL, headers=headers, data={}) as response:
            text = await response.text()
            return response.status, text
    if method == "post_fid":
        async with session.post(CAPTCHA_URL, headers=headers, data={"fid": FID}) as response:
            text = await response.text()
            return response.status, text
    if method == "post_fid_signed":
        _, payload = build_player_payload(FID)
        async with session.post(CAPTCHA_URL, headers=headers, data=payload) as response:
            text = await response.text()
            return response.status, text
    raise ValueError(f"Unknown captcha method: {method}")


async def main():
    parser = argparse.ArgumentParser(description="Standalone WOS captcha-aware protocol prototype")
    parser.add_argument("--skip-site-preflight", action="store_true")
    parser.add_argument("--skip-player", action="store_true")
    parser.add_argument("--captcha-method", choices=["get", "post_empty", "post_fid", "post_fid_signed"], default="get")
    parser.add_argument("--submit-final", action="store_true", help="Allow one final /api/gift_code submission after manual captcha input")
    parser.add_argument("--print-gift-sign-candidates", action="store_true")
    parser.add_argument("--gift-sign-mode", choices=["legacy", "include_captcha_last", "captcha_first"], default="legacy")
    parser.add_argument("--captcha-field", default="captcha_code", help="Field name to send the manual captcha solution under")
    parser.add_argument("--captcha-token-field", default=None, help="Optional token/id field name to include in gift submission")
    parser.add_argument("--captcha-token-value", default=None, help="Optional token/id value to include in gift submission")
    args = parser.parse_args()

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        print_json("SAMPLE", {"fid": FID, "gift_code": GIFT_CODE})

        if not args.skip_site_preflight:
            async with session.get(SITE_URL, headers=browser_headers(content_type="text/plain")) as response:
                text = await response.text()
                print_json("SITE_PREFLIGHT", {
                    "http_status": response.status,
                    "body_prefix": text[:120],
                    "cookie_count": len(session.cookie_jar.filter_cookies(SITE_URL)),
                })

        if not args.skip_player:
            sign_input, player_payload = build_player_payload(FID)
            print_json("PLAYER_REQUEST_SHAPE", {
                "endpoint": PLAYER_URL,
                "sign_input": sign_input,
                "payload_shape": sanitized_payload_shape(player_payload),
            })
            status, text = await post_form(session, PLAYER_URL, player_payload)
            print_json("PLAYER_RESPONSE_SHAPE", sanitized_response_shape(status, text))

        status, text = await fetch_captcha(session, args.captcha_method)
        print_json("CAPTCHA_RESPONSE_SHAPE", sanitized_response_shape(status, text))

        captcha_data = None
        try:
            captcha_data = json.loads(text)
        except json.JSONDecodeError:
            pass

        print_json("CAPTCHA_CANDIDATES", extract_captcha_candidates(captcha_data))
        print_json("CAPTCHA_DATA_SUMMARY", summarize_captcha_data(captcha_data))
        image_path = save_possible_captcha_image(captcha_data)
        print_json("CAPTCHA_IMAGE", {"saved_path": image_path})

        if not args.submit_final and not args.print_gift_sign_candidates:
            print_json("FINAL_SUBMISSION", {"skipped": True, "reason": "--submit-final not provided"})
            return

        captcha_solution = input(f"Enter manual captcha solution for field '{args.captcha_field}': ").strip()
        if not captcha_solution:
            print_json("FINAL_SUBMISSION", {"skipped": True, "reason": "empty captcha solution"})
            return

        if args.print_gift_sign_candidates:
            print_json("GIFT_SIGN_CANDIDATES", build_gift_sign_candidate_summary(FID, GIFT_CODE, captcha_solution))
            print_json("FINAL_SUBMISSION", {"skipped": True, "reason": "print_gift_sign_candidates"})
            return

        captcha_fields = {args.captcha_field: captcha_solution}
        if args.captcha_token_field and args.captcha_token_value:
            captcha_fields[args.captcha_token_field] = args.captcha_token_value

        sign_input, gift_payload = build_gift_payload(FID, GIFT_CODE, captcha_fields, args.gift_sign_mode)
        print_json("GIFT_REQUEST_SHAPE", {
            "endpoint": GIFT_CODE_URL,
            "sign_input": sign_input,
            "payload_shape": sanitized_final_gift_payload_shape(gift_payload),
            "cookie_count": len(session.cookie_jar.filter_cookies(SITE_URL)),
        })
        confirm = input("Type YES to submit final gift request: ").strip()
        if confirm != "YES":
            print_json("FINAL_SUBMISSION", {"skipped": True, "reason": "confirmation_not_yes"})
            return
        status, text = await post_form(session, GIFT_CODE_URL, gift_payload)
        print_json("GIFT_RESPONSE_SHAPE", sanitized_response_shape(status, text))


if __name__ == "__main__":
    asyncio.run(main())
