import hashlib
from urllib.parse import urlencode

SECRET = "tB87#kPtkxqOS2"


def md5_sign(sign_input):
    return hashlib.md5((sign_input + SECRET).encode("utf-8")).hexdigest()


def render_pairs(pairs, separator="&", key_value_separator="="):
    return separator.join(f"{key}{key_value_separator}{value}" for key, value in pairs)


def build_variant(name, ordered_pairs, sign_pairs=None, separator="&", key_value_separator="="):
    sign_pairs = sign_pairs or ordered_pairs
    sign_input = render_pairs(sign_pairs, separator=separator, key_value_separator=key_value_separator)
    sign = md5_sign(sign_input)
    body_pairs = []
    for key, value in ordered_pairs:
        body_pairs.append((key, sign if key == "sign" else value))
    body_dict = dict(body_pairs)
    print(f"VARIANT {name}")
    print(f"sign_input={sign_input}")
    print(f"md5_sign={sign}")
    print(f"body_keys={list(body_dict.keys())}")
    print(f"body_value_types={{{', '.join(f'{repr(k)}: {type(v).__name__!r}' for k, v in body_dict.items())}}}")
    print(f"encoded_form_body={urlencode(body_pairs)}")
    print()


def main():
    code = "ChildrensDay505"
    fid = "524303601"
    time_val = "1778129989"
    body_order = [("cdk", code), ("fid", fid), ("time", time_val), ("sign", "")]

    print("SAMPLE")
    print(f"code={code}")
    print(f"fid={fid}")
    print(f"time={time_val}")
    print()

    build_variant(
        "current_sign_base_cdk_fid_time_body_cdk_fid_time_sign",
        body_order,
        [("cdk", code), ("fid", fid), ("time", time_val)],
    )
    sign_input = f"cdk={code}&fid={fid}&time={time_val}"
    sign = md5_sign(sign_input)
    raw_body = f"cdk={code}&fid={fid}&time={time_val}&sign={sign}"
    print("VARIANT raw_prebuilt_form_string_cdk_fid_time_sign")
    print(f"sign_input={sign_input}")
    print(f"md5_sign={sign}")
    print("body_keys=['cdk', 'fid', 'time', 'sign']")
    print("body_value_types={'cdk': 'str', 'fid': 'str', 'time': 'str', 'sign': 'str'}")
    print(f"encoded_form_body={raw_body}")
    print()

    build_variant(
        "alternate_sign_base_fid_cdk_time",
        body_order,
        [("fid", fid), ("cdk", code), ("time", time_val)],
    )
    build_variant(
        "alternate_sign_base_time_fid_cdk",
        body_order,
        [("time", time_val), ("fid", fid), ("cdk", code)],
    )
    build_variant(
        "sorted_key_order_cdk_fid_time",
        body_order,
        [("cdk", code), ("fid", fid), ("time", time_val)],
    )
    build_variant(
        "alternate_separator_pipe_between_fields",
        body_order,
        [("cdk", code), ("fid", fid), ("time", time_val)],
        separator="|",
    )
    build_variant(
        "alternate_no_separator_between_fields",
        body_order,
        [("cdk", code), ("fid", fid), ("time", time_val)],
        separator="",
    )
    build_variant(
        "alternate_colon_key_value_separator",
        body_order,
        [("cdk", code), ("fid", fid), ("time", time_val)],
        key_value_separator=":",
    )
    build_variant(
        "alternate_uppercase_code_normalization",
        [("cdk", code.upper()), ("fid", fid), ("time", time_val), ("sign", "")],
        [("cdk", code.upper()), ("fid", fid), ("time", time_val)],
    )
    build_variant(
        "alternate_lowercase_code_normalization",
        [("cdk", code.lower()), ("fid", fid), ("time", time_val), ("sign", "")],
        [("cdk", code.lower()), ("fid", fid), ("time", time_val)],
    )

    print("PROJECT_HISTORY_CANONICAL_RULES")
    print("player_endpoint_sign_base=fid={fid}&time={unix_seconds}")
    print("player_endpoint_secret_handling=append_secret_directly_then_md5")
    print("player_endpoint_body_examples=fid={fid}&sign={sign}&time={time}")
    print("gift_endpoint_history_sign_base=cdk={gift_code}&fid={fid}&time={unix_seconds}")
    print("gift_endpoint_history_body_examples=cdk={gift_code}&fid={fid}&sign={sign}&time={time}")
    print("path_or_endpoint_in_signature=not_found_in_project_history")
    print("milliseconds_timestamp=found_in_old_player_logic_but_replaced_by_unix_seconds")


if __name__ == "__main__":
    main()
