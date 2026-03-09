import json
import os
import uuid
import base64
import urllib.request
import urllib.error

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API = "https://api.openai.com/v1"

CHAT_MODEL = "gpt-4o-mini"
IMAGE_MODEL = "dall-e-3"


def _openai_request(endpoint, payload):
    """Send a request to the OpenAI API."""
    url = f"{OPENAI_API}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_multipart_request(endpoint, fields, files):
    """Send a multipart/form-data POST to the OpenAI API."""
    boundary = uuid.uuid4().hex
    url = f"{OPENAI_API}/{endpoint}"

    body = b""
    for name, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
    for name, (filename, data, content_type) in files.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _chat(messages, max_tokens=1024):
    """Run a chat completion and return the response text."""
    result = _openai_request("chat/completions", {
        "model": CHAT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    })
    return result["choices"][0]["message"]["content"]


def _parse_json_response(text):
    """Extract JSON from LLM response (handles markdown code fences)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


def analyze_image(image_bytes):
    """Analyze an uploaded image with GPT-4o-mini vision to detect products."""
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Analyze this product image for a retail store. "
                    "Return ONLY valid JSON with this exact structure, no extra text:\n"
                    '{"items": [{"name": "...", "description": "...", "suggested_price": 0.00}], '
                    '"suggested_tags": ["tag1", "tag2", "tag3"]}'
                )},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "low",
                }},
            ]
        }]
        text = _chat(messages)
        return _parse_json_response(text)
    except Exception:
        return {
            "items": [{"name": "Product Item", "description": "A quality item from your store", "suggested_price": 29.99}],
            "suggested_tags": ["retail", "newstock", "musthave"]
        }


def generate_ad_copy(product_info, tone="promotional"):
    """Generate advertising copy for a product using OpenAI."""
    try:
        name = product_info.get("name", "Amazing Product")
        description = product_info.get("description", "")
        price = product_info.get("price", "")
        messages = [
            {"role": "system", "content": "You are an expert social media marketer. Return ONLY valid JSON."},
            {"role": "user", "content": (
                f"Generate {tone} advertising copy for this product:\n"
                f"Name: {name}\n"
                f"Description: {description}\n"
                f"Price: {price}\n\n"
                "Return ONLY valid JSON with this exact structure, no extra text:\n"
                '{"headline": "catchy headline", "body": "compelling ad body text (2-3 sentences)", '
                '"hashtags": ["#Tag1", "#Tag2", "#Tag3"]}'
            )},
        ]
        text = _chat(messages)
        return _parse_json_response(text)
    except Exception:
        return {
            "headline": f"New Arrival: {product_info.get('name', 'Amazing Product')}!",
            "body": "Don't miss out on this incredible deal. Limited stock available!",
            "hashtags": ["#ShopLocal", "#NewArrival", "#LimitedStock"]
        }


def generate_event_description(event_info):
    """Generate an event description using OpenAI."""
    try:
        title = event_info.get("title", "our special event")
        location = event_info.get("location", "")
        date = event_info.get("event_date", "")
        messages = [
            {"role": "system", "content": "You are an expert event marketer. Return ONLY valid JSON."},
            {"role": "user", "content": (
                f"Generate an engaging event description for a retail store event:\n"
                f"Title: {title}\n"
                f"Location: {location}\n"
                f"Date: {date}\n\n"
                "Return ONLY valid JSON with this exact structure, no extra text:\n"
                '{"description": "engaging event description (2-3 sentences)", '
                '"design_notes": "suggested visual design notes for the event poster"}'
            )},
        ]
        text = _chat(messages)
        return _parse_json_response(text)
    except Exception:
        return {
            "description": f"Join us for {event_info.get('title', 'our special event')}! An experience you won't want to miss.",
            "design_notes": "Suggested: Bold headline, warm colors, event date prominent"
        }


def analyze_logo(image_bytes):
    """Analyze a logo to extract brand colors, style, typography, and mood."""
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Analyze this brand logo image. "
                    "Return ONLY valid JSON with this exact structure, no extra text:\n"
                    '{"colors": ["#hex1", "#hex2", "#hex3"], '
                    '"style": "brief visual style (e.g. modern minimalist, bold geometric, elegant luxury)", '
                    '"font_style": "typography feel if visible (e.g. bold sans-serif, elegant serif, handwritten)", '
                    '"mood": "overall brand mood (e.g. professional, playful, premium, energetic)"}'
                )},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                }},
            ]
        }]
        text = _chat(messages)
        return _parse_json_response(text)
    except Exception:
        return {
            "colors": ["#000000", "#ffffff"],
            "style": "professional",
            "font_style": "clean sans-serif",
            "mood": "professional",
        }


def generate_ad_image(image_bytes, product_name="", style="promotional",
                      background_text="", overlay_text="",
                      brand_colors=None, brand_style="", brand_mood=""):
    """Generate an AI ad image using the OpenAI Images Edit API (gpt-image-1).

    Sends the user's actual photo to /images/edits, which transforms it into
    a styled ad version while preserving the real product appearance.
    Returns {"image_base64": "...", "mime_type": "..."} or {"error": "..."}.
    """
    try:
        # Detect file type from magic bytes
        if image_bytes[:4] == b"\x89PNG":
            filename, mime_type = "image.png", "image/png"
        else:
            filename, mime_type = "image.jpg", "image/jpeg"

        bg_part = (
            f"Background: {background_text}. "
            if background_text
            else "clean studio background with professional lighting. "
        )
        text_part = (
            f"Add this text on the image in bold, eye-catching ad typography with strong contrast: \"{overlay_text}\". "
            f"Place the text in a natural ad composition (top, bottom, or overlaid on a color band). "
            if overlay_text
            else "Do not add any text or words on the image. "
        )
        brand_part = ""
        if brand_colors or brand_style:
            color_str = ", ".join(brand_colors) if brand_colors else ""
            brand_part = (
                f"Brand identity: {brand_style}. "
                f"{f'Brand mood: {brand_mood}. ' if brand_mood else ''}"
                f"{f'Use these brand colors as inspiration: {color_str}. ' if color_str else ''}"
            )

        prompt = (
            f"Transform this product photo into a professional, polished {style} "
            f"advertising image for social media (Instagram/Facebook). "
            f"{f'Product: {product_name}. ' if product_name else ''}"
            f"Keep the SAME product exactly as it appears — same shape, color, details. "
            f"{bg_part}"
            f"{brand_part}"
            f"Vibrant colors, premium commercial feel. "
            f"{text_part}"
        )

        result = _openai_multipart_request(
            "images/edits",
            fields={
                "model": "gpt-image-1",
                "prompt": prompt,
                "n": "3",
                "size": "1024x1024",
            },
            files={
                "image": (filename, image_bytes, mime_type),
            },
        )

        data = result.get("data", [])
        if not data:
            return {"error": "No image was returned by the API."}

        images = []
        for item in data:
            if "b64_json" in item:
                images.append({"image_base64": item["b64_json"], "mime_type": "image/png"})
            elif "url" in item:
                images.append({"image_url": item["url"]})

        if not images:
            return {"error": "No image was returned by the API."}

        return {"images": images}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")[:300]
        return {"error": f"AI service error ({e.code}): {error_body}"}
    except Exception as e:
        return {"error": str(e)}
