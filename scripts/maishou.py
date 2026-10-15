#!/usr/bin/env python3
"""Read-only Maishou candidate discovery; prices are never checkout evidence.

Adapted from aahl/skills (MIT); see ../references/maishou-license.txt.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINTS = {
    "search": "https://appapi.maishou88.com/api/v1/homepage/searchList",
    "detail": "https://appapi.maishou88.com/api/v3/goods/detail",
    "link": "https://msapi.maishou88.com/api/v1/share/getTargetUrl",
}
# Public upstream defaults, not the user's shopping-platform credentials.
DEFAULT_OPENID = "564bdce0fa408fc9e1d5d42fd022ef0b"
DEFAULT_INVITE_CODE = "6110440"
SEARCH_FIELDS = (
    "goodsId", "sourceType", "title", "shopName", "shopTypeName",
    "originalPrice", "actualPrice", "couponPrice", "couponConditions",
    "couponStartTime", "couponEndTime", "tagList", "commission",
    "monthSales", "picUrl", "activityId", "supplierCode",
)


class ProviderError(Exception):
    """Transport, authentication or response-shape failure, never no-results."""


def post(operation, payload, headers, timeout):
    form = operation == "search"
    body = urlencode(payload).encode() if form else json.dumps(payload).encode()
    request = Request(ENDPOINTS[operation], data=body, headers={
        **headers,
        "Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8-sig"))
    except HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError("Network failure or timeout; use browser fallback") from exc
    except (ValueError, UnicodeError) as exc:
        raise ProviderError("Provider returned invalid JSON") from exc
    return extract_data(result, operation)


def extract_data(result, operation):
    if not isinstance(result, dict):
        raise ProviderError("Provider response is not an object")
    if str(result.get("code")) != "200" or result.get("status") not in (None, "success"):
        raise ProviderError(f"Provider error {result.get('code')}: {result.get('message', 'unknown')}")
    data = result.get("data")
    expected = list if operation == "search" else dict
    if not isinstance(data, expected):
        raise ProviderError("Provider data has an unexpected shape")
    if operation == "search":
        if any(not isinstance(item, dict) or not item.get("goodsId") for item in data):
            raise ProviderError("Search result is missing a goodsId")
        return [{key: item[key] for key in SEARCH_FIELDS if key in item} for item in data]
    if operation == "detail" and not data.get("goodsId"):
        raise ProviderError("Detail is missing a goodsId")
    if operation == "link" and not any(data.get(key) for key in ("appUrl", "schemaUrl", "h5Url", "kl")):
        raise ProviderError("Provider returned no purchase or coupon entry")
    return data


def query(args):
    openid = os.environ.get("MAISHOU_OPENID") or DEFAULT_OPENID
    invite = os.environ.get("MAISHOU_INVITE_CODE") or DEFAULT_INVITE_CODE
    headers = {
        "Accept": "application/json",
        "Referer": "https://hnbc018.kuaizhan.com/",
        "User-Agent": "Mozilla/5.0 AppleWebKit/537 Chrome/143 Safari/537",
    }
    if args.operation == "search":
        headers.update({"User-Agent": "MaiShouApp/3.7.7 (iPhone; iOS 26.3; Scale/3.00)",
                        "openid": openid, "version": "3.7.7.2"})
        payload = {"isCoupon": 0, "keyword": args.keyword, "openid": openid,
                   "order": "desc", "page": args.page, "pddListId": "", "sort": "",
                   "sourceType": str(args.source), "user_id": ""}
    else:
        payload = {"goodsId": args.id, "sourceType": str(args.source),
                   "inviteCode": invite, "supplierCode": args.supplier_code,
                   "activityId": args.activity_id, "isShare": "1", "token": ""}
        payload.update({"keyword": "", "usageScene": 5} if args.operation == "detail"
                       else {"isDirectDetail": 0})
    data = post(args.operation, payload, headers, args.timeout)
    result = {
        "status": "ok", "provider": "maishou", "operation": args.operation,
        "endpoint": ENDPOINTS[args.operation],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source, "checkout_verified": False,
        "identity_config": "upstream_default" if openid == DEFAULT_OPENID else "custom",
        "referral_config": "upstream_default" if invite == DEFAULT_INVITE_CODE else "custom",
        "data": data,
    }
    if args.operation == "search":
        result.update(keyword=args.keyword, page=args.page)
    else:
        result["requested_goods_id"] = args.id
    if args.operation == "link":
        result["promotional_link"] = True
    return result


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ENDPOINTS:
        command = commands.add_parser(operation)
        command.add_argument("--source", type=int, choices=(1, 2), required=True,
                             help="1: Taobao/Tmall; 2: JD")
        command.add_argument("--timeout", type=positive_int, default=25,
                             help="network timeout in seconds; no automatic retries")
        if operation == "search":
            command.add_argument("--keyword", required=True)
            command.add_argument("--page", type=positive_int, default=1)
        else:
            command.add_argument("--id", required=True, help="opaque goodsId from this provider")
            command.add_argument("--activity-id", default="")
            command.add_argument("--supplier-code", default="")
    args = parser.parse_args(argv)
    try:
        result = query(args)
    except ProviderError as exc:
        print(json.dumps({"status": "error", "provider": "maishou",
                          "operation": args.operation, "message": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
