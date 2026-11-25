#!/usr/bin/env python3
"""Photo-to-listing agent for artisan textiles.

Pipeline: one product photo in ->
  1. Muse Ember (Meta Model API, Responses API) drafts a structured,
     buyer-searchable listing: title, tradition, motifs, colors, tags,
     description.
  2. eBay Browse API search_by_image returns live comparable listings for
     the same photo, grounding the price range and the words sellers
     actually use -- including mislabeled ones (a suzani listed as a
     "tapestry", a Kantha as a "quilt").
  3. One combined Markdown draft is written next to the photo as
     <photo-name>-listing.md, with the raw responses in
     <photo-name>-listing.json.

The listing is a DRAFT. Model labels come from unverified web-scale
training; a human verifies before anything publishes.

Keys come from environment variables only and are never written to files
or output:
  META_API_KEY        Meta Model API key (required)
  EBAY_CLIENT_ID      eBay developer app ID / Client ID (optional)
  EBAY_CLIENT_SECRET  eBay developer Cert ID / Client Secret (optional)
Without the eBay keys the agent still writes the listing draft, minus comps.

Usage:
  python3 listing_agent.py photo.jpg [--limit 10]
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------
# Ember listing call (Meta Model API, Responses API)
# Pattern: cookbook vision input (base64 data URL) + structured output
# (text.format json_schema) + 512 px image, minimal reasoning effort.
# --------------------------------------------------------------------------

MODEL = "muse-ember-1.0"
RESPONSES_URL = "https://api.meta.ai/v1/responses"
MAX_OUTPUT_TOKENS = 16384

LISTING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "tradition": {"type": "string"},
        "motifs": {"type": "array", "items": {"type": "string"}},
        "colors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "description", "tags", "tradition", "motifs", "colors"],
    "additionalProperties": False,
}

PROMPT = (
    "You are a listing agent for Brieblue, an importer of Asian artisan textiles. "
    "Look at the textile in the photo and write a structured shop listing for it. "
    "Use words buyers and AI shopping agents already search for. Describe what is "
    "actually visible — the tradition it comes from, the motifs, the colors. "
    "Do not invent a price, dimensions, materials, or age you cannot see. "
    "Tags must be clean buyer-facing search phrases, with no hedged wording "
    "(no 'looking', 'style', or 'inspired' in tags). "
    "Return ONLY the listing as JSON with keys: title, description, tags "
    "(buyer-searchable keywords), tradition, motifs, colors."
)


def image_data_url(photo_path):
    """Base64 data URL for the photo, downscaled to 512 px wide if PIL is
    available (the cookbook's cheap vision setting); original bytes otherwise."""
    with open(photo_path, "rb") as f:
        raw = f.read()
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.width > 512:
            img = img.resize((512, round(img.height * 512 / img.width)))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=85)
            raw = buf.getvalue()
    except Exception:
        pass  # No PIL or unreadable as image: send the original bytes.
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def _extract_text(payload):
    text = ""
    for item in payload.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text += c.get("text", "")
    return text.strip()


def _parse_listing(text):
    """Return (parsed_dict_or_None, note). Strips a markdown fence if present."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        return None, "json.loads failed: %s" % str(e)[:120]
    missing = [k for k in LISTING_SCHEMA["required"] if k not in data]
    if missing:
        return None, "missing keys: %s" % ", ".join(missing)
    return data, "ok"


def _ember_call(api_key, data_url, variant):
    body = {
        "model": MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    if variant in ("full", "format_only"):
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": "shop_listing",
                "strict": True,
                "schema": LISTING_SCHEMA,
            }
        }
    if variant == "full":
        body["reasoning"] = {"effort": "minimal"}
    req = urllib.request.Request(
        RESPONSES_URL,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {
            "variant": variant,
            "seconds": round(time.time() - t0, 2),
            "http_status": e.code,
            "error": (e.read().decode(errors="replace") or "")[:400],
        }
    except Exception as e:
        return {
            "variant": variant,
            "seconds": round(time.time() - t0, 2),
            "error": type(e).__name__ + ": " + str(e)[:300],
        }
    text = _extract_text(payload)
    parsed, note = _parse_listing(text) if text else (None, "empty output_text")
    return {
        "variant": variant,
        "seconds": round(time.time() - t0, 2),
        "http_status": 200,
        "usage": payload.get("usage") or {},
        "parsed": parsed,
        "parse_note": note,
        "ok": parsed is not None,
    }


def ember_listing(api_key, data_url):
    """Try the call variants cheapest first; return (listing, meta) or raise."""
    attempts = []
    for variant in ("full", "format_only", "plain"):
        rec = _ember_call(api_key, data_url, variant)
        attempts.append(rec)
        if rec.get("ok"):
            meta = {k: rec.get(k) for k in ("variant", "seconds", "usage")}
            return rec["parsed"], meta
    raise RuntimeError("Ember listing failed: %s" % json.dumps(attempts)[:500])


# --------------------------------------------------------------------------
# eBay comps call (Browse API search_by_image)
# Auth: Application access token via OAuth2 client-credentials grant.
# --------------------------------------------------------------------------

EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search_by_image"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"


def ebay_app_token(client_id, client_secret):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": EBAY_SCOPE}
    ).encode()
    req = urllib.request.Request(
        EBAY_TOKEN_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def ebay_search_by_image(token, photo_path, limit=10):
    with open(photo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = json.dumps({"image": b64}).encode()
    req = urllib.request.Request(
        f"{EBAY_SEARCH_URL}?limit={limit}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def summarize_comps(ebay_raw):
    """Reduce the raw eBay response to title / price / currency / URL rows."""
    comps = []
    for it in ebay_raw.get("itemSummaries", []):
        price = it.get("price") or {}
        try:
            value = float(price.get("value"))
        except (TypeError, ValueError):
            value = None
        comps.append(
            {
                "title": it.get("title"),
                "price": value,
                "currency": price.get("currency"),
                "url": it.get("itemWebUrl"),
            }
        )
    return comps


def comp_price_range(comps):
    prices = [c["price"] for c in comps if c["price"] is not None]
    if not prices:
        return None
    return min(prices), max(prices)


# --------------------------------------------------------------------------
# Draft output
# --------------------------------------------------------------------------


def render_markdown(photo_path, listing, ember_meta, comps, price_range):
    lines = []
    lines.append("# %s" % listing["title"])
    lines.append("")
    lines.append("**Tradition:** %s" % listing["tradition"])
    lines.append("")
    lines.append("**Motifs:** %s" % ", ".join(listing["motifs"]))
    lines.append("")
    lines.append("**Colors:** %s" % ", ".join(listing["colors"]))
    lines.append("")
    lines.append("**Tags:** %s" % ", ".join(listing["tags"]))
    lines.append("")
    lines.append("## Description")
    lines.append("")
    lines.append(listing["description"])
    lines.append("")
    if comps:
        lines.append("## Comparable live listings (eBay image search)")
        lines.append("")
        for c in comps:
            price = (
                "$%.2f" % c["price"] if c["price"] is not None else "no price"
            )
            lines.append("- %s — %s — %s" % (c["title"], price, c["url"]))
        lines.append("")
        if price_range:
            lines.append(
                "**Comp price range:** $%.2f–$%.2f across %d listings"
                % (price_range[0], price_range[1], len(comps))
            )
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Draft generated by the Brieblue listing agent (Muse Ember, %s, "
        "%ss). Model tradition/motif labels are drafts from unverified "
        "web-scale training — a human verifies this listing before it "
        "publishes._"
        % (ember_meta.get("variant"), ember_meta.get("seconds"))
    )
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Photo-to-listing agent")
    ap.add_argument("photo", help="Path to the product photo")
    ap.add_argument("--limit", type=int, default=10, help="Max eBay comps")
    args = ap.parse_args()

    meta_key = os.environ.get("META_API_KEY")
    if not meta_key:
        print("Missing META_API_KEY env var.", file=sys.stderr)
        return 2
    if not os.path.isfile(args.photo):
        print("Photo not found: %s" % args.photo, file=sys.stderr)
        return 2

    # 1. Ember listing
    listing, ember_meta = ember_listing(meta_key, image_data_url(args.photo))
    print("Listing drafted: %s" % listing["title"])

    # 2. eBay comps (optional)
    comps, price_range, ebay_raw = [], None, None
    ebay_id = os.environ.get("EBAY_CLIENT_ID")
    ebay_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if ebay_id and ebay_secret:
        try:
            token = ebay_app_token(ebay_id, ebay_secret)
            ebay_raw = ebay_search_by_image(token, args.photo, args.limit)
            comps = summarize_comps(ebay_raw)
            price_range = comp_price_range(comps)
            print("eBay comps: %d listings" % len(comps))
            if price_range:
                print(
                    "Comp price range: $%.2f-$%.2f"
                    % (price_range[0], price_range[1])
                )
        except urllib.error.HTTPError as e:
            print(
                "eBay search failed (HTTP %d) — draft written without comps."
                % e.code,
                file=sys.stderr,
            )
    else:
        print("No eBay keys set — draft written without comps.")

    # 3. Write the draft + raw JSON next to the photo
    stem = os.path.splitext(os.path.abspath(args.photo))[0]
    md_path = stem + "-listing.md"
    json_path = stem + "-listing.json"
    with open(md_path, "w") as f:
        f.write(render_markdown(args.photo, listing, ember_meta, comps, price_range))
    with open(json_path, "w") as f:
        json.dump(
            {
                "photo": os.path.basename(args.photo),
                "model": MODEL,
                "ember": ember_meta,
                "listing": listing,
                "ebay_comps": comps,
                "ebay_raw": ebay_raw,
            },
            f,
            indent=2,
        )
    print("Wrote %s" % md_path)
    print("Wrote %s" % json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
